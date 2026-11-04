"""SQLite tracking: one row per certificate, keyed by certificate ID.

Owner: Person C (email + tracking)
Rules covered: 11 (status tracking), 12 (retry), 13 (duplicate-send prevention).
Statuses: Pending -> Generated -> Sending -> Sent / Failed
"""
import datetime
import os
import sqlite3
from contextlib import contextmanager

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "certiflow.db")


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _now():
    return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS certificates (
            cert_id TEXT PRIMARY KEY, name TEXT, student_id TEXT, email TEXT, event TEXT,
            achievement TEXT, date TEXT, cert_type TEXT, file_path TEXT,
            status TEXT, error TEXT DEFAULT '', attempts INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT, sent_at TEXT)""")


def get(cert_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
        return dict(row) if row else None


def upsert(rec, file_path, status):
    """Create or refresh a record. A record already 'Sent' keeps that status (no accidental resend)."""
    existing = get(rec["CERT_ID"])
    if existing and existing["status"] == "Sent":
        return "Sent"
    with _conn() as c:
        c.execute("""INSERT INTO certificates
            (cert_id, name, student_id, email, event, achievement, date, cert_type, file_path, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cert_id) DO UPDATE SET file_path=excluded.file_path, status=excluded.status,
                error='', updated_at=excluded.updated_at""",
            (rec["CERT_ID"], rec["NAME"], rec["ID"], rec["EMAIL"], rec["EVENT"], rec["ACHIEVEMENT"],
             rec["DATE"], rec["CERT_TYPE"], file_path, status, _now(), _now()))
    return status


def set_status(cert_id, status, error=""):
    with _conn() as c:
        c.execute("""UPDATE certificates SET status=?, error=?, updated_at=?,
                     attempts = attempts + CASE WHEN ? IN ('Sent','Failed') THEN 1 ELSE 0 END,
                     sent_at = CASE WHEN ?='Sent' THEN ? ELSE sent_at END
                     WHERE cert_id=?""",
                  (status, error, _now(), status, status, _now(), cert_id))


def records(cert_ids=None):
    with _conn() as c:
        if cert_ids is None:
            rows = c.execute("SELECT * FROM certificates ORDER BY updated_at DESC").fetchall()
        else:
            ids = list(cert_ids)
            if not ids:
                return pd.DataFrame()
            marks = ",".join("?" * len(ids))
            rows = c.execute(f"SELECT * FROM certificates WHERE cert_id IN ({marks})", ids).fetchall()
    return pd.DataFrame([dict(r) for r in rows])
