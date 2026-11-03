"""Database connection and schema for the Orbit Air baggage desk.

This module owns the schema and nothing else.
"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    passenger   TEXT NOT NULL CHECK (length(trim(passenger)) > 0),
    flight      TEXT NOT NULL CHECK (length(trim(flight)) > 0),
    claim_type  TEXT NOT NULL CHECK (claim_type IN ('delayed', 'lost', 'damaged')),
    tier        TEXT NOT NULL CHECK (tier IN ('standard', 'silver', 'gold')),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'assigned', 'escalated', 'resolved', 'closed')),
    agent       TEXT,
    note        TEXT,
    filed_at    TEXT NOT NULL,
    deadline    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id    INTEGER NOT NULL REFERENCES claims(id),
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    changed_by  TEXT NOT NULL,
    changed_at  TEXT NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open a connection with Row access and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the claims and history tables if they do not exist."""
    with conn:
        conn.executescript(SCHEMA)
