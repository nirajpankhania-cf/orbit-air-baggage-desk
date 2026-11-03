"""Business rules for Orbit Air baggage claims.

No function here reads the system clock; `now` is always passed in.
"""

import sqlite3
from datetime import datetime, timedelta

CLAIM_TYPES = ("delayed", "lost", "damaged")
TIERS = ("standard", "silver", "gold")
DEADLINE_HOURS = {"gold": 4, "silver": 24, "standard": 72}

# Legal status moves, from PLAN.md. 'closed' is terminal.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"assigned", "escalated"},
    "assigned": {"resolved", "escalated"},
    "escalated": {"assigned", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}


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


def get_claim(conn: sqlite3.Connection, claim_id: int) -> sqlite3.Row:
    """Return the claim row, or raise ValueError if no such claim exists."""
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise ValueError(f"no claim with id {claim_id}")
    return row


def _apply_transition(
    conn: sqlite3.Connection,
    claim_id: int,
    new_status: str,
    changed_by: str,
    now: datetime,
    agent: str | None = None,
) -> None:
    """Check the move against ALLOWED_TRANSITIONS, then write claim + history atomically."""
    old_status = get_claim(conn, claim_id)["status"]
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValueError(
            f"cannot move claim {claim_id} from {old_status!r} to {new_status!r}"
        )

    changed_at = now.isoformat()
    with conn:
        if agent is None:
            conn.execute(
                "UPDATE claims SET status = ? WHERE id = ?",
                (new_status, claim_id),
            )
        else:
            conn.execute(
                "UPDATE claims SET status = ?, agent = ? WHERE id = ?",
                (new_status, agent, claim_id),
            )
        conn.execute(
            """
            INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (claim_id, old_status, new_status, changed_by, changed_at),
        )


def change_status(
    conn: sqlite3.Connection,
    claim_id: int,
    new_status: str,
    changed_by: str,
    now: datetime,
) -> None:
    """Move a claim to `new_status` if the table allows it; otherwise raise ValueError."""
    _apply_transition(conn, claim_id, new_status, changed_by, now)


def assign_claim(conn: sqlite3.Connection, claim_id: int, agent: str, now: datetime) -> None:
    """Assign a claim to an agent. Allowed from 'open' or 'escalated' per the table."""
    _apply_transition(conn, claim_id, "assigned", agent, now, agent=agent)


def resolve_claim(conn: sqlite3.Connection, claim_id: int, changed_by: str, now: datetime) -> None:
    """Mark a claim resolved. Allowed from 'assigned' or 'escalated' per the table."""
    _apply_transition(conn, claim_id, "resolved", changed_by, now)


def close_claim(conn: sqlite3.Connection, claim_id: int, changed_by: str, now: datetime) -> None:
    """Close a resolved claim. Allowed only from 'resolved' per the table."""
    _apply_transition(conn, claim_id, "closed", changed_by, now)


def get_history(conn: sqlite3.Connection, claim_id: int) -> list[sqlite3.Row]:
    """Return the history rows for a claim, oldest first."""
    return conn.execute(
        "SELECT * FROM history WHERE claim_id = ? ORDER BY id", (claim_id,)
    ).fetchall()
