"""Business rules for Orbit Air baggage claims.

No function here reads the system clock; `now` is always passed in.
"""

import sqlite3
from collections.abc import Iterable, Mapping
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
STATUSES = tuple(ALLOWED_TRANSITIONS)
ACTIVE_STATUSES = ("open", "assigned", "escalated")
ESCALATABLE_STATUSES = ("open", "assigned")

# Columns a seed row must carry; 'type' maps to the claim_type column.
SEED_COLUMNS = ("passenger", "flight", "type", "tier", "note")


def _require_text(value: str | None, field: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field} must not be blank")


def _validate_claim(passenger: str, flight: str, claim_type: str, tier: str) -> None:
    _require_text(passenger, "passenger")
    _require_text(flight, "flight")
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"unknown claim type {claim_type!r}; expected one of {CLAIM_TYPES}")
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")


def check_seed_columns(columns: Iterable[str] | None) -> None:
    """Raise ValueError naming the first required seed column that is missing."""
    present = set(columns or ())
    for column in SEED_COLUMNS:
        if column not in present:
            raise ValueError(f"seed file is missing column {column!r}")


def deadline_for(tier: str, now: datetime) -> datetime:
    """Return the response deadline for a claim filed at `now` in the given tier."""
    return now + timedelta(hours=DEADLINE_HOURS[tier])


def _insert_claim(
    conn: sqlite3.Connection,
    passenger: str,
    flight: str,
    claim_type: str,
    tier: str,
    note: str,
    now: datetime,
) -> int:
    """Insert an open claim and its filing history row. Caller owns the transaction."""
    filed_at = now.isoformat()
    deadline = deadline_for(tier, now).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO claims
            (passenger, flight, claim_type, tier, status, note, filed_at, deadline)
        VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (passenger, flight, claim_type, tier, note, filed_at, deadline),
    )
    claim_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)
        VALUES (?, NULL, 'open', 'system', ?)
        """,
        (claim_id, filed_at),
    )
    return claim_id


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
    with conn:
        return _insert_claim(conn, passenger, flight, claim_type, tier, note, now)


def seed_claims(conn: sqlite3.Connection, rows: Iterable[Mapping[str, str]], now: datetime) -> int:
    """File every row in one transaction; a bad row means nothing is loaded. Returns the count."""
    prepared: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        check_seed_columns(row.keys())
        passenger, flight = row["passenger"], row["flight"]
        claim_type, tier = row["type"], row["tier"]
        _validate_claim(passenger, flight, claim_type, tier)
        prepared.append((passenger, flight, claim_type, tier, row["note"] or ""))

    with conn:
        for passenger, flight, claim_type, tier, note in prepared:
            _insert_claim(conn, passenger, flight, claim_type, tier, note, now)
    return len(prepared)


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


def _check_transition(
    conn: sqlite3.Connection,
    claim_id: int,
    new_status: str,
    changed_by: str,
    agent: str | None,
) -> str:
    """Validate actors and the move against ALLOWED_TRANSITIONS; return the current status."""
    if agent is not None:
        _require_text(agent, "agent")
    _require_text(changed_by, "changed_by")
    old_status = get_claim(conn, claim_id)["status"]
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValueError(
            f"cannot move claim {claim_id} from {old_status!r} to {new_status!r}"
        )
    return old_status


def _write_transition(
    conn: sqlite3.Connection,
    claim_id: int,
    old_status: str,
    new_status: str,
    changed_by: str,
    now: datetime,
    agent: str | None,
) -> None:
    """Update the claim and insert its history row. Caller owns the transaction."""
    if agent is None:
        conn.execute("UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id))
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
        (claim_id, old_status, new_status, changed_by, now.isoformat()),
    )


def _apply_transition(
    conn: sqlite3.Connection,
    claim_id: int,
    new_status: str,
    changed_by: str,
    now: datetime,
    agent: str | None = None,
) -> None:
    """Check the move, then write claim + history in one transaction."""
    old_status = _check_transition(conn, claim_id, new_status, changed_by, agent)
    with conn:
        _write_transition(conn, claim_id, old_status, new_status, changed_by, now, agent)


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


def is_overdue(claim_row: sqlite3.Row, now: datetime) -> bool:
    """True only when `now` is strictly later than the claim's deadline."""
    deadline = datetime.fromisoformat(claim_row["deadline"])
    return now > deadline


def escalate_overdue(
    conn: sqlite3.Connection,
    now: datetime,
    changed_by: str = "system",
) -> list[int]:
    """Move every overdue open or assigned claim to 'escalated'; return the ids, sorted.

    The whole sweep is one transaction: each move is checked against ALLOWED_TRANSITIONS
    and written with its history row, and a failure anywhere rolls back every move.
    """
    placeholders = ", ".join("?" for _ in ESCALATABLE_STATUSES)
    candidates = conn.execute(
        f"SELECT * FROM claims WHERE status IN ({placeholders}) ORDER BY id",
        ESCALATABLE_STATUSES,
    ).fetchall()
    overdue = [row for row in candidates if is_overdue(row, now)]

    escalated: list[int] = []
    with conn:
        for row in overdue:
            claim_id = row["id"]
            old_status = _check_transition(conn, claim_id, "escalated", changed_by, None)
            _write_transition(conn, claim_id, old_status, "escalated", changed_by, now, None)
            escalated.append(claim_id)
    return sorted(escalated)


# STRETCH GOAL 2
def report_counts(conn: sqlite3.Connection, now: datetime) -> dict[str, dict[str, int]]:
    """Per tier: how many claims have status 'open', and how many active claims are overdue.

    An active claim is one whose status is in ACTIVE_STATUSES (not resolved or closed).
    """
    counts = {tier: {"open": 0, "overdue": 0} for tier in TIERS}
    for row in conn.execute("SELECT tier, status, deadline FROM claims").fetchall():
        bucket = counts[row["tier"]]
        if row["status"] == "open":
            bucket["open"] += 1
        if row["status"] in ACTIVE_STATUSES and is_overdue(row, now):
            bucket["overdue"] += 1
    return counts


def get_history(conn: sqlite3.Connection, claim_id: int) -> list[sqlite3.Row]:
    """Return the history rows for a claim, oldest first."""
    return conn.execute(
        "SELECT * FROM history WHERE claim_id = ? ORDER BY id", (claim_id,)
    ).fetchall()
