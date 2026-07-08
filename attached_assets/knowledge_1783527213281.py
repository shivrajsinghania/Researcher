import json
import re
import sqlite3
from datetime import datetime, timedelta

from config.database import get_connection


def _slugify(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _parse_json(value, default):
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _row_to_record(row):
    if row is None:
        return None

    record = dict(row)
    record["documents"] = _parse_json(record.pop("documents_json", "[]"), [])
    record["steps"] = _parse_json(record.pop("application_steps_json", "[]"), [])
    record["sources"] = _parse_json(record.pop("sources_json", "[]"), [])
    record["manual_review_needed"] = bool(record.get("manual_review_needed", 0))
    record["active"] = bool(record.get("active", 1))
    return record


def _service_key_from_data(data):
    key = data.get("service_key") or data.get("service_name") or data.get("service") or ""
    return _slugify(key)


def _service_name_from_key(service_key):
    return str(service_key or "").replace("-", " ").strip().title() or "Unnamed Service"


def _jurisdiction_type(state, incoming=None):
    if incoming:
        return str(incoming).strip().lower()
    state_text = str(state or "").strip().lower()
    if state_text in {"central", "india", "all india", "pan india"}:
        return "central"
    return "state"


# ─── Confidence score ──────────────────────────────────────
# Auto-computed from how complete a service record is — never taken
# from client input. Admin-facing only (signals how filled-in the
# knowledge base entry is), never shown to end users.
_CONFIDENCE_FIELD_WEIGHTS = {
    "department": 8,
    "portal_name": 8,
    "portal_url": 8,
    "apply_url": 6,
    "eligibility": 8,
    "fees": 8,
    "timeline": 8,
    "validity": 6,
    "category": 4,
}


def _compute_confidence_score(payload):
    """Compute a 0-100 confidence score from how complete a service
    record is. `payload` uses the same normalized shape as the rest of
    save_service_knowledge (documents/steps/sources as lists, etc.)."""
    score = 0

    for field, weight in _CONFIDENCE_FIELD_WEIGHTS.items():
        if str(payload.get(field) or "").strip():
            score += weight

    if payload.get("documents"):
        score += 12
    if payload.get("steps"):
        score += 12
    if payload.get("sources"):
        score += 8

    if str(payload.get("photo_size") or "").strip():
        score += 3
    if str(payload.get("signature_size") or "").strip():
        score += 3
    if str(payload.get("upload_limits") or "").strip():
        score += 2
    if str(payload.get("notes") or "").strip():
        score += 2

    # Verified recently -> small trust bonus. Flagged for manual review
    # -> small penalty (signals the data may be incomplete/stale).
    if str(payload.get("last_verified") or "").strip():
        score += 4
    if payload.get("manual_review_needed"):
        score -= 5

    return max(0, min(100, score))


def get_service_knowledge(service, state=None):
    service_text = str(service or "").strip()
    if not service_text:
        return None

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    key = _slugify(service_text)

    if state:
        cursor.execute(
            """
            SELECT *
            FROM service_knowledge
            WHERE lower(service_key)=lower(?)
               OR (lower(service_name)=lower(?) AND lower(state)=lower(?))
            LIMIT 1
            """,
            (key, service_text, str(state).strip()),
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM service_knowledge
            WHERE lower(service_key)=lower(?)
               OR lower(service_name)=lower(?)
            LIMIT 1
            """,
            (key, service_text),
        )

    row = cursor.fetchone()
    conn.close()
    return _row_to_record(row)


def list_service_knowledge(state=None, category=None, query=None, active=None, limit=200):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    sql = "SELECT * FROM service_knowledge WHERE 1=1"
    params = []

    if state:
        sql += " AND lower(state)=lower(?)"
        params.append(str(state).strip())

    if category:
        sql += " AND lower(category)=lower(?)"
        params.append(str(category).strip())

    if active is not None:
        sql += " AND active=?"
        params.append(1 if active else 0)

    if query:
        q = f"%{str(query).strip().lower()}%"
        sql += """
            AND (
                lower(service_name) LIKE ?
                OR lower(service_key) LIKE ?
                OR lower(portal_name) LIKE ?
                OR lower(department) LIKE ?
                OR lower(notes) LIKE ?
            )
        """
        params.extend([q, q, q, q, q])

    sql += " ORDER BY active DESC, state ASC, category ASC, service_name ASC"

    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_record(row) for row in rows]


def list_public_services(state=None):
    """Active services only, shaped for the public service-picker
    dropdown (grouped by category within a jurisdiction). Powers
    /api/services — the same source of truth the admin panel edits."""
    records = list_service_knowledge(state=state, active=True, limit=1000)

    groups = {}
    order = []
    for r in records:
        group_name = r.get("category") or "Other"
        if group_name not in groups:
            groups[group_name] = []
            order.append(group_name)
        groups[group_name].append({
            "value": r.get("service_key"),
            "label": r.get("service_name"),
            "icon": r.get("icon") or "📄",
        })

    return [{"group": name, "items": groups[name]} for name in order]


def get_due_service_reviews(days=7):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM service_knowledge
        WHERE active=1
          AND (
                manual_review_needed=1
                OR last_verified IS NULL
                OR TRIM(last_verified) = ''
                OR datetime(last_verified) <= datetime('now', ?)
          )
        ORDER BY
            CASE
                WHEN last_verified IS NULL OR TRIM(last_verified) = '' THEN 0
                ELSE 1
            END,
            datetime(last_verified) ASC,
            service_name ASC
        """,
        (f"-{int(days)} days",),
    )

    rows = cursor.fetchall()
    conn.close()
    return [_row_to_record(row) for row in rows]


def save_service_knowledge(data, changed_by=None):
    service_key = _service_key_from_data(data)
    if not service_key:
        raise ValueError("service_key or service_name is required")

    service_name = str(data.get("service_name") or data.get("service") or _service_name_from_key(service_key)).strip()
    state = str(data.get("state") or "Central").strip() or "Central"
    jurisdiction_type = _jurisdiction_type(state, data.get("jurisdiction_type"))
    category = (data.get("category") or "").strip() or None
    icon = (data.get("icon") or "").strip() or None
    department = (data.get("department") or "").strip() or None
    portal_name = (data.get("portal_name") or "").strip() or None
    portal_url = (data.get("portal_url") or "").strip() or None
    apply_url = (data.get("apply_url") or "").strip() or None
    eligibility = (data.get("eligibility") or "").strip() or None
    fees = (data.get("fees") or "").strip() or None
    timeline = (data.get("timeline") or "").strip() or None
    photo_size = (data.get("photo_size") or "").strip() or None
    signature_size = (data.get("signature_size") or "").strip() or None
    upload_limits = (data.get("upload_limits") or "").strip() or None
    validity = (data.get("validity") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    sources = data.get("sources") or data.get("sources_json") or []
    documents = data.get("documents") or data.get("documents_json") or []
    steps = data.get("steps") or data.get("application_steps_json") or []
    last_verified = (data.get("last_verified") or "").strip() or None
    manual_review_needed = 1 if data.get("manual_review_needed") else 0
    active = 1 if data.get("active", True) else 0

    # Confidence score is always computed server-side from record
    # completeness — client-supplied values are ignored so this can
    # never be gamed or left stale by a form field.
    confidence_score = _compute_confidence_score({
        "department": department,
        "portal_name": portal_name,
        "portal_url": portal_url,
        "apply_url": apply_url,
        "eligibility": eligibility,
        "fees": fees,
        "timeline": timeline,
        "validity": validity,
        "category": category,
        "photo_size": photo_size,
        "signature_size": signature_size,
        "upload_limits": upload_limits,
        "notes": notes,
        "documents": documents,
        "steps": steps,
        "sources": sources,
        "last_verified": last_verified,
        "manual_review_needed": bool(manual_review_needed),
    })
    updated_by = (changed_by or data.get("updated_by") or "").strip() or None
    change_summary = (data.get("change_summary") or "").strip() or None

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT version FROM service_knowledge WHERE service_key=? LIMIT 1",
        (service_key,),
    )
    existing = cursor.fetchone()
    version = int(existing["version"]) + 1 if existing else 1

    snapshot = {
        "service_key": service_key,
        "service_name": service_name,
        "state": state,
        "jurisdiction_type": jurisdiction_type,
        "category": category,
        "icon": icon,
        "department": department,
        "portal_name": portal_name,
        "portal_url": portal_url,
        "apply_url": apply_url,
        "documents": documents,
        "eligibility": eligibility,
        "fees": fees,
        "timeline": timeline,
        "photo_size": photo_size,
        "signature_size": signature_size,
        "upload_limits": upload_limits,
        "validity": validity,
        "steps": steps,
        "notes": notes,
        "sources": sources,
        "confidence_score": confidence_score,
        "last_verified": last_verified,
        "manual_review_needed": bool(manual_review_needed),
        "active": bool(active),
        "version": version,
        "updated_by": updated_by,
        "saved_at": datetime.utcnow().isoformat(timespec="seconds"),
    }

    if existing:
        cursor.execute(
            """
            UPDATE service_knowledge
            SET service_name=?,
                state=?,
                jurisdiction_type=?,
                category=?,
                icon=?,
                department=?,
                portal_name=?,
                portal_url=?,
                apply_url=?,
                documents_json=?,
                eligibility=?,
                fees=?,
                timeline=?,
                photo_size=?,
                signature_size=?,
                upload_limits=?,
                validity=?,
                application_steps_json=?,
                notes=?,
                sources_json=?,
                confidence_score=?,
                last_verified=?,
                manual_review_needed=?,
                active=?,
                version=?,
                updated_by=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE service_key=?
            """,
            (
                service_name,
                state,
                jurisdiction_type,
                category,
                icon,
                department,
                portal_name,
                portal_url,
                apply_url,
                json.dumps(documents, ensure_ascii=False),
                eligibility,
                fees,
                timeline,
                photo_size,
                signature_size,
                upload_limits,
                validity,
                json.dumps(steps, ensure_ascii=False),
                notes,
                json.dumps(sources, ensure_ascii=False),
                confidence_score,
                last_verified,
                manual_review_needed,
                active,
                version,
                updated_by,
                service_key,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO service_knowledge(
                service_key,
                service_name,
                state,
                jurisdiction_type,
                category,
                icon,
                department,
                portal_name,
                portal_url,
                apply_url,
                documents_json,
                eligibility,
                fees,
                timeline,
                photo_size,
                signature_size,
                upload_limits,
                validity,
                application_steps_json,
                notes,
                sources_json,
                confidence_score,
                last_verified,
                manual_review_needed,
                active,
                version,
                updated_by
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                service_key,
                service_name,
                state,
                jurisdiction_type,
                category,
                icon,
                department,
                portal_name,
                portal_url,
                apply_url,
                json.dumps(documents, ensure_ascii=False),
                eligibility,
                fees,
                timeline,
                photo_size,
                signature_size,
                upload_limits,
                validity,
                json.dumps(steps, ensure_ascii=False),
                notes,
                json.dumps(sources, ensure_ascii=False),
                confidence_score,
                last_verified,
                manual_review_needed,
                active,
                version,
                updated_by,
            ),
        )

    cursor.execute(
        """
        INSERT INTO service_versions(
            service_key,
            version,
            snapshot_json,
            change_summary,
            changed_by
        )
        VALUES(?,?,?,?,?)
        """,
        (
            service_key,
            version,
            json.dumps(snapshot, ensure_ascii=False),
            change_summary,
            updated_by,
        ),
    )

    conn.commit()
    conn.close()
    return get_service_knowledge(service_key)


def public_service_card(record):
    if not record:
        return None

    documents = record.get("documents") or []
    steps = record.get("steps") or []

    return {
        "service_key": record.get("service_key"),
        "service_name": record.get("service_name"),
        "state": record.get("state"),
        "jurisdiction_type": record.get("jurisdiction_type"),
        "category": record.get("category"),
        "department": record.get("department"),
        "portal_name": record.get("portal_name"),
        "portal_url": record.get("portal_url"),
        "apply_url": record.get("apply_url"),
        "documents": documents[:8],
        "eligibility": record.get("eligibility"),
        "fees": record.get("fees"),
        "timeline": record.get("timeline"),
        "photo_size": record.get("photo_size"),
        "signature_size": record.get("signature_size"),
        "upload_limits": record.get("upload_limits"),
        "validity": record.get("validity"),
        "steps": steps[:8],
        "notes": record.get("notes"),
        "active": bool(record.get("active", True)),
    }
    
def build_research_payload(record):
    """
    Convert a DB row into the exact shape the current frontend expects.
    This keeps the public UI unchanged while the backend reads from DB only.
    """
    if not record:
        return None

    documents = record.get("documents") or []
    steps = record.get("steps") or []
    sources = record.get("sources") or []

    analysis = {
        "service_name": record.get("service_name") or "",
        "state": record.get("state") or "",
        "department": record.get("department") or "",
        "portal_name": record.get("portal_name") or "",
        "portal_url": record.get("portal_url") or "",
        "apply_url": record.get("apply_url") or "",
        "fee": record.get("fees") or "",
        "processing_time": record.get("timeline") or "",
        "eligibility": record.get("eligibility") or "",
        "validity": record.get("validity") or "",
        "upload_limits": record.get("upload_limits") or "",
        "last_verified": record.get("last_verified") or "",
        "required_documents": documents,
        "application_steps": steps,
        "faq": [],
        "notes": record.get("notes") or "",
        "extra_important_items": [],
        "sources": sources,
        "pdf_sources": [],
        "photo_size": record.get("photo_size") or "",
        "signature_size": record.get("signature_size") or "",
    }

    return {
        "service": record.get("service_key") or record.get("service_name") or "",
        "state": record.get("state") or "",
        "url": record.get("portal_url") or record.get("apply_url") or "",
        "analysis": analysis,
    }