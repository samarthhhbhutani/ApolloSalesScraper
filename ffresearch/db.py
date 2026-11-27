"""SQLite persistence layer: intermediate checkpoints + resume support.

Every raw tool response that matters is first written to data/raw/*.json
(checkpoint), then ingested idempotently into data/research.db. Re-running the
ingest after an interruption simply upserts the same rows again.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "research.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    domain TEXT PRIMARY KEY,
    name TEXT,
    apollo_org_id TEXT,
    country TEXT,
    city TEXT,
    employees INTEGER,
    industry TEXT,
    linkedin_url TEXT,
    description TEXT,
    company_source TEXT,
    apollo_enriched INTEGER DEFAULT 0,
    apollo_keywords TEXT,
    email_stack TEXT,
    founded_year INTEGER
);
CREATE TABLE IF NOT EXISTS reviews (
    domain TEXT PRIMARY KEY,
    status TEXT,              -- qualified | excluded
    reason TEXT,
    independent INTEGER,
    air INTEGER,
    ocean INTEGER,
    agent_network INTEGER,    -- evidence of international agent relationships 0/1/2
    specialisation TEXT
);
CREATE TABLE IF NOT EXISTS people (
    linkedin_url TEXT PRIMARY KEY,
    name TEXT,
    title TEXT,
    domain TEXT,
    location TEXT,
    contact_source TEXT,
    batch TEXT,
    discovered_seq INTEGER
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, tool TEXT, query TEXT, results INTEGER, credits INTEGER, ts TEXT
);
CREATE TABLE IF NOT EXISTS credit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, action TEXT, credits_used INTEGER, balance_after INTEGER, note TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert(con: sqlite3.Connection, table: str, key: str, row: dict) -> None:
    """Insert or merge a row; non-null incoming values overwrite existing ones."""
    row = {k: v for k, v in row.items() if v is not None}
    if not row.get(key):
        return
    existing = con.execute(f"SELECT * FROM {table} WHERE {key}=?", (row[key],)).fetchone()
    if existing is None:
        cols = ",".join(row)
        con.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})",
                    list(row.values()))
    else:
        sets = ",".join(f"{k}=?" for k in row if k != key)
        if sets:
            con.execute(f"UPDATE {table} SET {sets} WHERE {key}=?",
                        [v for k, v in row.items() if k != key] + [row[key]])


def load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
