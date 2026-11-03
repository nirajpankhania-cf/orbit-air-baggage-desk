"""Branch 3: feature/deadlines-and-escalation.

Tests for claims.is_overdue and claims.escalate_overdue, plus the transaction
rollback guarantee on status changes.
"""

import sqlite3
from datetime import datetime

import claims
import db
import pytest

FILED = datetime(2026, 11, 1, 9, 0)
# A gold claim filed at 09:00 has a 4-hour window, so its deadline is 13:00.
DEADLINE = datetime(2026, 11, 1, 13, 0)
ONE_MINUTE_BEFORE = datetime(2026, 11, 1, 12, 59)
ONE_MINUTE_AFTER = datetime(2026, 11, 1, 13, 1)
AGENT = "maria"


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.init_db(connection)
    yield connection
    connection.close()


def file_claim(conn, tier: str = "gold", passenger: str = "Ada Lovelace") -> int:
    return claims.file_claim(
        conn,
        passenger=passenger,
        flight="OA123",
        claim_type="lost",
        tier=tier,
        note="",
        now=FILED,
    )


def status_of(conn, claim_id: int) -> str:
    return claims.get_claim(conn, claim_id)["status"]


# --- is_overdue -------------------------------------------------------------


def test_not_overdue_one_minute_before(conn):
    claim_id = file_claim(conn)
    row = claims.get_claim(conn, claim_id)
    assert claims.is_overdue(row, ONE_MINUTE_BEFORE) is False


def test_not_overdue_exactly_at_deadline(conn):
    claim_id = file_claim(conn)
    row = claims.get_claim(conn, claim_id)
    assert claims.is_overdue(row, DEADLINE) is False


def test_overdue_one_minute_after(conn):
    claim_id = file_claim(conn)
    row = claims.get_claim(conn, claim_id)
    assert claims.is_overdue(row, ONE_MINUTE_AFTER) is True


# --- escalate_overdue -------------------------------------------------------


def test_escalate_moves_overdue_open_and_assigned(conn):
    open_id = file_claim(conn, passenger="Open Passenger")
    assigned_id = file_claim(conn, passenger="Assigned Passenger")
    claims.assign_claim(conn, assigned_id, AGENT, FILED)

    claims.escalate_overdue(conn, ONE_MINUTE_AFTER)

    assert status_of(conn, open_id) == "escalated"
    assert status_of(conn, assigned_id) == "escalated"


def test_escalate_leaves_resolved_closed_and_on_time_alone(conn):
    # Resolved and closed gold claims are past their deadline but not escalatable.
    resolved_id = file_claim(conn, passenger="Resolved Passenger")
    claims.assign_claim(conn, resolved_id, AGENT, FILED)
    claims.resolve_claim(conn, resolved_id, AGENT, FILED)

    closed_id = file_claim(conn, passenger="Closed Passenger")
    claims.assign_claim(conn, closed_id, AGENT, FILED)
    claims.resolve_claim(conn, closed_id, AGENT, FILED)
    claims.close_claim(conn, closed_id, AGENT, FILED)

    # A standard-tier claim has a 72-hour window, so it is still on time at 13:01.
    on_time_id = file_claim(conn, tier="standard", passenger="On Time Passenger")

    escalated = claims.escalate_overdue(conn, ONE_MINUTE_AFTER)

    assert escalated == []
    assert status_of(conn, resolved_id) == "resolved"
    assert status_of(conn, closed_id) == "closed"
    assert status_of(conn, on_time_id) == "open"


def test_escalate_returns_escalated_ids(conn):
    first_id = file_claim(conn, passenger="First")
    second_id = file_claim(conn, passenger="Second")
    on_time_id = file_claim(conn, tier="standard", passenger="On Time")

    escalated = claims.escalate_overdue(conn, ONE_MINUTE_AFTER)

    assert escalated == sorted([first_id, second_id])
    assert on_time_id not in escalated

    # Already-escalated claims must not be picked up a second time.
    assert claims.escalate_overdue(conn, ONE_MINUTE_AFTER) == []


def test_escalate_writes_history_row(conn):
    open_id = file_claim(conn, passenger="Open Passenger")
    assigned_id = file_claim(conn, passenger="Assigned Passenger")
    claims.assign_claim(conn, assigned_id, AGENT, FILED)

    claims.escalate_overdue(conn, ONE_MINUTE_AFTER)

    open_latest = claims.get_history(conn, open_id)[-1]
    assert open_latest["old_status"] == "open"
    assert open_latest["new_status"] == "escalated"
    assert open_latest["changed_by"] == "system"
    assert open_latest["changed_at"] == ONE_MINUTE_AFTER.isoformat()

    assigned_latest = claims.get_history(conn, assigned_id)[-1]
    assert assigned_latest["old_status"] == "assigned"
    assert assigned_latest["new_status"] == "escalated"
    assert assigned_latest["changed_by"] == "system"
    assert assigned_latest["changed_at"] == ONE_MINUTE_AFTER.isoformat()


# --- transaction guarantee --------------------------------------------------


def test_rollback_when_history_write_fails(conn):
    # The claim UPDATE and the history INSERT must share one `with conn:` block.
    # Renaming the history table makes the INSERT fail after the UPDATE has run.
    # If the transaction wrapper is removed, the UPDATE is committed on its own,
    # the status becomes 'assigned', and this test fails. That is the point.
    claim_id = file_claim(conn)
    conn.execute("ALTER TABLE history RENAME TO history_gone")

    with pytest.raises(sqlite3.OperationalError):
        claims.assign_claim(conn, claim_id, AGENT, FILED)

    row = conn.execute("SELECT status, agent FROM claims WHERE id = ?", (claim_id,)).fetchone()
    assert row["status"] == "open"
    assert row["agent"] is None
