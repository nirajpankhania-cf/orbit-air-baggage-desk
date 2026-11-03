"""Branch 1: feature/schema-and-filing.

Tests for db.connect / db.init_db and claims.file_claim / list_claims / get_history.
"""

import sqlite3
from datetime import datetime, timedelta

import claims
import db
import pytest

NOW = datetime(2026, 11, 1, 9, 0)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.init_db(connection)
    yield connection
    connection.close()


def _count_claims(conn):
    return conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]


def test_init_db_creates_claims_and_history_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('claims', 'history')"
    ).fetchall()
    names = {row[0] for row in rows}
    assert names == {"claims", "history"}


def test_file_claim_returns_id_and_stores_fields(conn):
    claim_id = claims.file_claim(
        conn,
        passenger="Ada Lovelace",
        flight="OA123",
        claim_type="lost",
        tier="silver",
        note="Black suitcase",
        now=NOW,
    )

    assert isinstance(claim_id, int)
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    assert row is not None
    assert row["passenger"] == "Ada Lovelace"
    assert row["flight"] == "OA123"
    assert row["claim_type"] == "lost"
    assert row["tier"] == "silver"
    assert row["note"] == "Black suitcase"
    assert row["status"] == "open"
    assert row["agent"] is None
    assert row["filed_at"] == NOW.isoformat()


def test_file_claim_rejects_blank_passenger(conn):
    with pytest.raises(ValueError, match="passenger"):
        claims.file_claim(
            conn,
            passenger="  ",
            flight="OA123",
            claim_type="lost",
            tier="silver",
            note="",
            now=NOW,
        )
    assert _count_claims(conn) == 0


def test_file_claim_rejects_blank_flight(conn):
    with pytest.raises(ValueError, match="flight"):
        claims.file_claim(
            conn,
            passenger="Ada Lovelace",
            flight="  ",
            claim_type="lost",
            tier="silver",
            note="",
            now=NOW,
        )
    assert _count_claims(conn) == 0


def test_file_claim_rejects_unknown_type(conn):
    with pytest.raises(ValueError, match="type"):
        claims.file_claim(
            conn,
            passenger="Ada Lovelace",
            flight="OA123",
            claim_type="stolen",
            tier="silver",
            note="",
            now=NOW,
        )
    assert _count_claims(conn) == 0


def test_file_claim_rejects_unknown_tier(conn):
    with pytest.raises(ValueError, match="tier"):
        claims.file_claim(
            conn,
            passenger="Ada Lovelace",
            flight="OA123",
            claim_type="lost",
            tier="platinum",
            note="",
            now=NOW,
        )
    assert _count_claims(conn) == 0


@pytest.mark.parametrize(
    ("tier", "hours"),
    [("gold", 4), ("silver", 24), ("standard", 72)],
)
def test_deadline_by_tier(conn, tier, hours):
    claim_id = claims.file_claim(
        conn,
        passenger="Ada Lovelace",
        flight="OA123",
        claim_type="delayed",
        tier=tier,
        note="",
        now=NOW,
    )
    row = conn.execute("SELECT deadline FROM claims WHERE id = ?", (claim_id,)).fetchone()
    assert row["deadline"] == (NOW + timedelta(hours=hours)).isoformat()


def test_list_claims_filters_by_status_and_tier(conn):
    gold_id = claims.file_claim(conn, "Ada", "OA1", "lost", "gold", "", NOW)
    silver_id = claims.file_claim(conn, "Grace", "OA2", "delayed", "silver", "", NOW)
    standard_id = claims.file_claim(conn, "Linus", "OA3", "damaged", "standard", "", NOW)

    # Move one claim out of 'open' so the status filter has something to exclude.
    with conn:
        conn.execute("UPDATE claims SET status = 'resolved' WHERE id = ?", (silver_id,))

    all_ids = {row["id"] for row in claims.list_claims(conn)}
    assert all_ids == {gold_id, silver_id, standard_id}

    by_tier = {row["id"] for row in claims.list_claims(conn, tier="gold")}
    assert by_tier == {gold_id}

    by_status = {row["id"] for row in claims.list_claims(conn, status="open")}
    assert by_status == {gold_id, standard_id}

    # Both filters together must AND, not OR: silver is resolved, so nothing matches.
    both = {row["id"] for row in claims.list_claims(conn, status="open", tier="silver")}
    assert both == set()

    both_match = {row["id"] for row in claims.list_claims(conn, status="open", tier="standard")}
    assert both_match == {standard_id}


def test_filing_writes_initial_history_row(conn):
    claim_id = claims.file_claim(
        conn,
        passenger="Ada Lovelace",
        flight="OA123",
        claim_type="lost",
        tier="gold",
        note="",
        now=NOW,
    )

    history = claims.get_history(conn, claim_id)
    assert len(history) == 1
    entry = history[0]
    assert entry["claim_id"] == claim_id
    assert entry["old_status"] is None
    assert entry["new_status"] == "open"
    assert entry["changed_by"] == "system"
    assert entry["changed_at"] == NOW.isoformat()


def test_check_constraints_reject_bad_values(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO claims (passenger, flight, claim_type, tier, filed_at, deadline)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Ada", "OA123", "lost", "platinum", NOW.isoformat(), NOW.isoformat()),
        )
