"""
Flask application — provides the review UI and API endpoints for the
Gov Service Research Tool. Runs as a standalone service on Render.
"""
import json
import threading
import uuid
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
import storage
from pipeline import orchestrator

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

storage.init_db()


# ─── Home / Input form ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    approved = storage.list_approved(limit=30)
    return render_template("index.html",
                           scopes=list(config.WHITELIST.keys()),
                           categories=config.CATEGORIES,
                           approved=approved)


# ─── Start research job ────────────────────────────────────────────────────────

@app.route("/research", methods=["POST"])
def start_research():
    service_name = (request.form.get("service_name") or "").strip()
    state = (request.form.get("state") or "").strip()

    if not service_name or not state:
        return "service_name and state are required", 400
    if state not in config.WHITELIST:
        return f"Unknown scope: {state}", 400

    job_id = str(uuid.uuid4())[:12]
    storage.upsert_job(job_id, service_name, state, status="pending",
                       progress="Queued...")

    t = threading.Thread(
        target=orchestrator.run,
        args=(job_id, service_name, state),
        daemon=True,
    )
    t.start()

    return redirect(url_for("status", job_id=job_id))


# ─── Re-verify existing record ─────────────────────────────────────────────────

@app.route("/re-verify/<service_key>", methods=["POST"])
def re_verify(service_key):
    existing = storage.get_approved(service_key)
    if not existing:
        return f"No approved record found for: {service_key}", 404

    service_name = existing["service_name"]
    state = existing["state"]
    old_record = existing["record"]

    job_id = str(uuid.uuid4())[:12]
    storage.upsert_job(job_id, service_name, state, status="pending",
                       progress="Queued for re-verification...")

    t = threading.Thread(
        target=orchestrator.run,
        args=(job_id, service_name, state, old_record),
        daemon=True,
    )
    t.start()

    return redirect(url_for("status", job_id=job_id))


# ─── Status polling ────────────────────────────────────────────────────────────

@app.route("/status/<job_id>")
def status(job_id):
    job = storage.get_job(job_id)
    if not job:
        return "Job not found", 404
    return render_template("status.html", job=job)


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = storage.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "status": job["status"],
        "progress": job.get("progress"),
        "service_name": job["service_name"],
        "state": job["state"],
        "error": job.get("error"),
    })


# ─── Review screen ─────────────────────────────────────────────────────────────

@app.route("/review/<job_id>")
def review(job_id):
    job = storage.get_job(job_id)
    if not job:
        return "Job not found", 404
    if job["status"] != "done":
        return redirect(url_for("status", job_id=job_id))

    record = job["result"]
    field_status = record.get("field_status", {})
    is_reverify = record.get("_is_reverify", False)
    diff = record.get("_diff", {})

    schema_fields = [
        ("service_name",    "Service Name",        "text",     True),
        ("state",           "Scope",               "text",     True),
        ("category",        "Category",            "text",     False),
        ("department",      "Department",          "text",     True),
        ("portal_name",     "Portal Name",         "text",     True),
        ("portal_url",      "Portal URL",          "url",      True),
        ("apply_url",       "Apply Online URL",    "url",      False),
        ("eligibility",     "Eligibility",         "textarea", True),
        ("fees",            "Fees",                "text",     True),
        ("timeline",        "Timeline",            "text",     True),
        ("validity",        "Validity",            "text",     False),
        ("photo_size",      "Photo Size / Specs",  "text",     False),
        ("signature_size",  "Signature Specs",     "text",     False),
        ("upload_limits",   "Upload Limits",       "text",     False),
        ("documents",       "Documents Required",  "list",     True),
        ("steps",           "Application Steps",   "list",     True),
        ("notes",           "Notes",               "textarea", False),
        ("sources",         "Sources",             "list",     True),
    ]

    return render_template(
        "review.html",
        job=job,
        record=record,
        field_status=field_status,
        schema_fields=schema_fields,
        is_reverify=is_reverify,
        diff=diff,
    )


# ─── Approve and save ──────────────────────────────────────────────────────────

@app.route("/approve/<job_id>", methods=["POST"])
def approve(job_id):
    job = storage.get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    base = job["result"] or {}
    data = request.get_json(force=True) or {}

    record = {**base, **data}

    for list_field in ("documents", "steps", "sources"):
        val = record.get(list_field)
        if isinstance(val, str):
            record[list_field] = [
                line.strip() for line in val.split("\n") if line.strip()
            ]

    record.pop("_diff", None)
    record.pop("_is_reverify", None)
    record.pop("field_status", None)

    service_key = storage.slugify(record.get("service_name", "unknown"))
    service_name = record.get("service_name", "")
    state = record.get("state", job["state"])
    record["service_key"] = service_key
    record["last_verified"] = datetime.utcnow().date().isoformat()

    is_reverify = bool(job["result"].get("_is_reverify"))
    change_summary = "Re-verified" if is_reverify else "Initial research"

    version = storage.save_approved(
        service_key=service_key,
        service_name=service_name,
        state=state,
        record=record,
        job_id=job_id,
        change_summary=change_summary,
    )

    return jsonify({"ok": True, "service_key": service_key, "version": version})


# ─── Export JSON ───────────────────────────────────────────────────────────────

@app.route("/export/<service_key>")
def export_json(service_key):
    rec = storage.get_approved(service_key)
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify(rec["record"]), 200, {
        "Content-Disposition": f'attachment; filename="{service_key}.json"',
        "Content-Type": "application/json",
    }


@app.route("/export-all")
def export_all():
    records = storage.list_approved(limit=1000)
    out = []
    for r in records:
        approved = storage.get_approved(r["service_key"])
        if approved:
            out.append(approved["record"])
    return jsonify(out), 200, {
        "Content-Disposition": 'attachment; filename="all_services.json"',
        "Content-Type": "application/json",
    }


# ─── History ───────────────────────────────────────────────────────────────────

@app.route("/history")
def history():
    jobs = storage.list_jobs(limit=50)
    approved = storage.list_approved(limit=200)
    return render_template("history.html", jobs=jobs, approved=approved)


# ─── Health check (Render pings this) ─────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
