"""Branch 2: feature/assign-and-status.

Tests for claims.ALLOWED_TRANSITIONS, change_status, assign_claim, resolve_claim,
close_claim and get_claim.
"""

from datetime import datetime

import claims
import db
import pytest

NOW = datetime(2026, 11, 1, 9, 0)
AGENT = "maria"

# The transition table from PLAN.md, written out literally so the test is the spec.
SPEC_TRANSITIONS = {
    "open": {"assigned", "escalated"},
    "assigned": {"resolved", "escalated"},
    "escalated": {"assigned", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}

# Shortest legal route from 'open' to each status, used to set up a claim in a given state.
ROUTE_TO = {
    "open": [],
    "assigned": ["assigned"],
    "escalated": ["escalated"],
    "resolved": ["assigned", "resolved"],
    "closed": ["assigned", "resolved", "closed"],
}

ALL_PAIRS = [
    (from_status, to_status)
    for from_status, targets in SPEC_TRANSITIONS.items()
    for to_status in sorted(targets)
]


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.init_db(connection)
    yield connection
    connection.close()


def file_open_claim(conn) -> int:
    return claims.file_claim(
        conn,
        passenger="Ada Lovelace",
        flight="OA123",
        claim_type="lost",
        tier="silver",
        note="",
        now=NOW,
    )


def drive_to(conn, claim_id: int, target: str) -> None:
    for step in ROUTE_TO[target]:
        claims.change_status(conn, claim_id, step, "system", NOW)


def history_count(conn, claim_id: int) -> int:
    return len(claims.get_history(conn, claim_id))


def test_allowed_transitions_table_matches_spec():
    assert claims.ALLOWED_TRANSITIONS == SPEC_TRANSITIONS


def test_assign_open_claim_sets_agent_and_status(conn):
    claim_id = file_open_claim(conn)

    claims.assign_claim(conn, claim_id, AGENT, NOW)

    row = claims.get_claim(conn, claim_id)
    assert row["status"] == "assigned"
    assert row["agent"] == AGENT


def test_assign_escalated_claim_allowed(conn):
    claim_id = file_open_claim(conn)
    claims.change_status(conn, claim_id, "escalated", "system", NOW)

    claims.assign_claim(conn, claim_id, AGENT, NOW)

    row = claims.get_claim(conn, claim_id)
    assert row["status"] == "assigned"
    assert row["agent"] == AGENT


def test_resolve_assigned_claim(conn):
    claim_id = file_open_claim(conn)
    claims.assign_claim(conn, claim_id, AGENT, NOW)

    claims.resolve_claim(conn, claim_id, AGENT, NOW)

    assert claims.get_claim(conn, claim_id)["status"] == "resolved"


def test_close_resolved_claim(conn):
    claim_id = file_open_claim(conn)
    claims.assign_claim(conn, claim_id, AGENT, NOW)
    claims.resolve_claim(conn, claim_id, AGENT, NOW)

    claims.close_claim(conn, claim_id, AGENT, NOW)

    assert claims.get_claim(conn, claim_id)["status"] == "closed"


@pytest.mark.parametrize(("from_status", "to_status"), ALL_PAIRS)
def test_every_allowed_transition_succeeds(conn, from_status, to_status):
    claim_id = file_open_claim(conn)
    drive_to(conn, claim_id, from_status)
    assert claims.get_claim(conn, claim_id)["status"] == from_status

    claims.change_status(conn, claim_id, to_status, "system", NOW)

    assert claims.get_claim(conn, claim_id)["status"] == to_status


def test_close_open_claim_rejected(conn):
    claim_id = file_open_claim(conn)

    with pytest.raises(ValueError, match=r"open.*closed"):
        claims.close_claim(conn, claim_id, AGENT, NOW)

    assert claims.get_claim(conn, claim_id)["status"] == "open"


def test_resolve_open_claim_rejected(conn):
    claim_id = file_open_claim(conn)

    with pytest.raises(ValueError, match=r"open.*resolved"):
        claims.resolve_claim(conn, claim_id, AGENT, NOW)

    assert claims.get_claim(conn, claim_id)["status"] == "open"


def test_change_from_closed_rejected(conn):
    claim_id = file_open_claim(conn)
    drive_to(conn, claim_id, "closed")

    for target in ("open", "assigned", "escalated", "resolved"):
        with pytest.raises(ValueError, match=rf"closed.*{target}"):
            claims.change_status(conn, claim_id, target, "system", NOW)

    assert claims.get_claim(conn, claim_id)["status"] == "closed"


def test_assign_resolved_claim_rejected(conn):
    claim_id = file_open_claim(conn)
    drive_to(conn, claim_id, "resolved")

    with pytest.raises(ValueError, match=r"resolved.*assigned"):
        claims.assign_claim(conn, claim_id, AGENT, NOW)

    row = claims.get_claim(conn, claim_id)
    assert row["status"] == "resolved"
    assert row["agent"] is None


def test_rejected_change_writes_no_history_and_leaves_status(conn):
    claim_id = file_open_claim(conn)
    before = history_count(conn, claim_id)

    with pytest.raises(ValueError):
        claims.change_status(conn, claim_id, "closed", AGENT, NOW)

    assert history_count(conn, claim_id) == before
    assert claims.get_claim(conn, claim_id)["status"] == "open"


def test_history_row_has_old_new_who_when(conn):
    claim_id = file_open_claim(conn)

    claims.assign_claim(conn, claim_id, AGENT, NOW)

    history = claims.get_history(conn, claim_id)
    assert len(history) == 2
    latest = history[-1]
    assert latest["claim_id"] == claim_id
    assert latest["old_status"] == "open"
    assert latest["new_status"] == "assigned"
    assert latest["changed_by"] == AGENT
    assert latest["changed_at"] == NOW.isoformat()
