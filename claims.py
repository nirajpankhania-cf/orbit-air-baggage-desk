"""Business rules for Orbit Air baggage claims.

No function here reads the system clock; `now` is always passed in.
"""

import sqlite3
from datetime import datetime, timedelta

CLAIM_TYPES = ("delayed", "lost", "damaged")
TIERS = ("standard", "silver", "gold")
DEADLINE_HOURS = {"gold": 4, "silver": 24, "standard": 72}


def _validate_claim(passenger: str, flight: str, claim_type: str, tier: str) -> None:
    if not passenger or not passenger.strip():
        raise ValueError("passenger must not be blank")
    if not flight or not flight.strip():
        raise ValueError("flight must not be blank")
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"unknown claim type {claim_type!r}; expected one of {CLAIM_TYPES}")
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")


def deadline_for(tier: str, now: datetime) -> datetime:
    """Return the response deadline for a claim filed at `now` in the given tier."""
    return now + timedelta(hours=DEADLINE_HOURS[tier])


def file_claim(
    conn: sqlite3.Connection,
    passenger: str,
    flight: str,
    claim_type: str,
    tier: str,
    note: str,
    now: datetime,
) -> int:
    """Validate, insert a new open claim and its first history row, and return the id."""
    _validate_claim(passenger, flight, claim_type, tier)
    filed_at = now.isoformat()
    deadline = deadline_for(tier, now).isoformat()

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO claims
                (passenger, flight, claim_type, tier, status, note, filed_at, deadline)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (passenger, flight, claim_type, tier, note, filed_at, deadline),
        )
        claim_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)
            VALUES (?, NULL, 'open', 'system', ?)
            """,
            (claim_id, filed_at),
        )
    return int(claim_id)


def list_claims(
    conn: sqlite3.Connection,
    status: str | None = None,
    tier: str | None = None,
) -> list[sqlite3.Row]:
    """Return claims, optionally filtered by status and/or tier (filters are ANDed)."""
    clauses: list[str] = []
    params: list[str] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if tier is not None:
        clauses.append("tier = ?")
        params.append(tier)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(f"SELECT * FROM claims{where} ORDER BY id", params).fetchall()


def get_history(conn: sqlite3.Connection, claim_id: int) -> list[sqlite3.Row]:
    """Return the history rows for a claim, oldest first."""
    return conn.execute(
        "SELECT * FROM history WHERE claim_id = ? ORDER BY id", (claim_id,)
    ).fetchall()
