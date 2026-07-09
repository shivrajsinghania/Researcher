import json
import re
import sqlite3
from datetime import datetime

import config


def _get_conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = _get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS research_jobs (
            id          TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            state       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            progress    TEXT,
            result_json TEXT,
            error       TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS approved_records (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            service_key  TEXT NOT NULL UNIQUE,
            service_name TEXT NOT NULL,
            state        TEXT NOT NULL,
            record_json  TEXT NOT NULL,
            job_id       TEXT,
            approved_at  TEXT DEFAULT (datetime('now')),
            version      INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS record_versions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            service_key  TEXT NOT NULL,
            version      INTEGER NOT NULL,
            record_json  TEXT NOT NULL,
            change_summary TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def upsert_job(job_id: str, service_name: str, state: str, status: str = "pending",
               progress: str = None, result: dict = None, error: str = None):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO research_jobs (id, service_name, state, status, progress, result_json, error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,
            progress=excluded.progress,
            result_json=excluded.result_json,
            error=excluded.error,
            updated_at=datetime('now')
    """, (
        job_id, service_name, state, status,
        progress,
        json.dumps(result, ensure_ascii=False) if result is not None else None,
        error,
    ))
    conn.commit()
    conn.close()


def get_job(job_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM research_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    else:
        d["result"] = None
    return d


def list_jobs(limit=50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM research_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    out = []
    for row in rows:
        d = dict(row)
        d["result"] = json.loads(d["result_json"]) if d.get("result_json") else None
        out.append(d)
    return out


def save_approved(service_key: str, service_name: str, state: str,
                  record: dict, job_id: str = None, change_summary: str = None):
    conn = _get_conn()
    existing = conn.execute(
        "SELECT version, record_json FROM approved_records WHERE service_key=?",
        (service_key,),
    ).fetchone()

    if existing:
        version = existing["version"] + 1
        conn.execute("""
            INSERT INTO record_versions (service_key, version, record_json, change_summary)
            VALUES (?, ?, ?, ?)
        """, (service_key, existing["version"], existing["record_json"], change_summary))
        conn.execute("""
            UPDATE approved_records
            SET service_name=?, state=?, record_json=?, job_id=?,
                approved_at=datetime('now'), version=?
            WHERE service_key=?
        """, (service_name, state, json.dumps(record, ensure_ascii=False),
              job_id, version, service_key))
    else:
        version = 1
        conn.execute("""
            INSERT INTO approved_records (service_key, service_name, state, record_json, job_id, version)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (service_key, service_name, state, json.dumps(record, ensure_ascii=False), job_id))

    conn.commit()
    conn.close()
    return version


def get_approved(service_key: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM approved_records WHERE service_key=?", (service_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["record"] = json.loads(d["record_json"])
    return d


def list_approved(limit=200) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT service_key, service_name, state, approved_at, version FROM approved_records ORDER BY approved_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
