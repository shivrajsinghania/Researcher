import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "agent.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        app TEXT,
        target TEXT,
        message TEXT,
        query TEXT,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_queue(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_json TEXT,
        status TEXT,
        attempts INTEGER DEFAULT 0,
        error TEXT,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workflows(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        workflow_json TEXT,
        status TEXT,
        current_step INTEGER DEFAULT 0,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        action TEXT,
        result_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        user_id INTEGER,
        role TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_knowledge(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_key TEXT NOT NULL UNIQUE,
        service_name TEXT NOT NULL,
        state TEXT NOT NULL,
        jurisdiction_type TEXT NOT NULL DEFAULT 'state',
        category TEXT,
        icon TEXT,
        department TEXT,
        portal_name TEXT,
        portal_url TEXT,
        apply_url TEXT,
        documents_json TEXT DEFAULT '[]',
        eligibility TEXT,
        fees TEXT,
        timeline TEXT,
        photo_size TEXT,
        signature_size TEXT,
        upload_limits TEXT,
        validity TEXT,
        application_steps_json TEXT DEFAULT '[]',
        notes TEXT,
        sources_json TEXT DEFAULT '[]',
        confidence_score INTEGER DEFAULT 0,
        last_verified TEXT,
        manual_review_needed INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        version INTEGER DEFAULT 1,
        updated_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_versions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_key TEXT NOT NULL,
        version INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        change_summary TEXT,
        changed_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    def ensure_column(table_name, column_name, column_definition):
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row[1] for row in cursor.fetchall()}
        if column_name not in existing:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )

    ensure_column("service_knowledge", "service_key", "TEXT")
    ensure_column("service_knowledge", "service_name", "TEXT")
    ensure_column("service_knowledge", "state", "TEXT")
    ensure_column("service_knowledge", "jurisdiction_type", "TEXT DEFAULT 'state'")
    ensure_column("service_knowledge", "category", "TEXT")
    ensure_column("service_knowledge", "icon", "TEXT")
    ensure_column("service_knowledge", "department", "TEXT")
    ensure_column("service_knowledge", "portal_name", "TEXT")
    ensure_column("service_knowledge", "portal_url", "TEXT")
    ensure_column("service_knowledge", "apply_url", "TEXT")
    ensure_column("service_knowledge", "documents_json", "TEXT DEFAULT '[]'")
    ensure_column("service_knowledge", "eligibility", "TEXT")
    ensure_column("service_knowledge", "fees", "TEXT")
    ensure_column("service_knowledge", "timeline", "TEXT")
    ensure_column("service_knowledge", "photo_size", "TEXT")
    ensure_column("service_knowledge", "signature_size", "TEXT")
    ensure_column("service_knowledge", "upload_limits", "TEXT")
    ensure_column("service_knowledge", "validity", "TEXT")
    ensure_column("service_knowledge", "application_steps_json", "TEXT DEFAULT '[]'")
    ensure_column("service_knowledge", "notes", "TEXT")
    ensure_column("service_knowledge", "sources_json", "TEXT DEFAULT '[]'")
    ensure_column("service_knowledge", "confidence_score", "INTEGER DEFAULT 0")
    ensure_column("service_knowledge", "last_verified", "TEXT")
    ensure_column("service_knowledge", "manual_review_needed", "INTEGER DEFAULT 0")
    ensure_column("service_knowledge", "active", "INTEGER DEFAULT 1")
    ensure_column("service_knowledge", "version", "INTEGER DEFAULT 1")
    ensure_column("service_knowledge", "updated_by", "TEXT")

    conn.commit()
    cursor.close()
    conn.close()