"""Branch 4: feature/cli.

End-to-end tests that drive main.py as a subprocess against a temporary database.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FILED_AT = "2026-11-01T09:00:00"
AT_DEADLINE = "2026-11-01T13:00:00"  # gold deadline: filed + 4h
AFTER_DEADLINE = "2026-11-01T13:01:00"


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "claims.sqlite"


def run_cli(tmp_db, *args: str, now: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "main.py", "--db", str(tmp_db)]
    if now is not None:
        cmd += ["--now", now]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def file_claim(tmp_db, passenger: str, tier: str, now: str = FILED_AT) -> int:
    result = run_cli(
        tmp_db,
        "file",
        "--passenger", passenger,
        "--flight", "OA123",
        "--type", "lost",
        "--tier", tier,
        now=now,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(r"Filed claim (\d+)", result.stdout)
    assert match is not None, result.stdout
    return int(match.group(1))


def test_cli_file_and_list(tmp_db):
    claim_id = file_claim(tmp_db, "Ada Lovelace", "silver")

    result = run_cli(tmp_db, "list")

    assert result.returncode == 0, result.stderr
    assert "Ada Lovelace" in result.stdout
    assert "open" in result.stdout
    assert str(claim_id) in result.stdout


def test_cli_now_option_drives_escalation(tmp_db):
    claim_id = file_claim(tmp_db, "Ada Lovelace", "gold", now=FILED_AT)

    at_deadline = run_cli(tmp_db, "escalate", now=AT_DEADLINE)
    assert at_deadline.returncode == 0, at_deadline.stderr
    assert "No claims to escalate" in at_deadline.stdout

    after_deadline = run_cli(tmp_db, "escalate", now=AFTER_DEADLINE)
    assert after_deadline.returncode == 0, after_deadline.stderr
    assert f"Escalated claims: {claim_id}" in after_deadline.stdout

    listed = run_cli(tmp_db, "list", "--status", "escalated")
    assert listed.returncode == 0, listed.stderr
    assert "Ada Lovelace" in listed.stdout
    assert "escalated" in listed.stdout


def test_cli_seed_loads_csv(tmp_db, tmp_path):
    csv_path = tmp_path / "seed.csv"
    csv_path.write_text(
        "passenger,flight,type,tier,note\n"
        "Ada Lovelace,OA101,lost,gold,Black suitcase\n"
        "Grace Hopper,OA202,delayed,silver,\n"
        'Linus Torvalds,OA303,damaged,standard,"Handle snapped, wheel missing"\n'
    )

    seeded = run_cli(tmp_db, "seed", str(csv_path), now=FILED_AT)
    assert seeded.returncode == 0, seeded.stderr
    assert "Loaded 3" in seeded.stdout

    listed = run_cli(tmp_db, "list")
    assert listed.returncode == 0, listed.stderr
    for passenger in ("Ada Lovelace", "Grace Hopper", "Linus Torvalds"):
        assert passenger in listed.stdout


def test_cli_invalid_input_exits_nonzero(tmp_db):
    result = run_cli(
        tmp_db,
        "file",
        "--passenger", "Ada Lovelace",
        "--flight", "OA123",
        "--type", "lost",
        "--tier", "platinum",
        now=FILED_AT,
    )

    assert result.returncode == 1
    assert "Error:" in result.stderr
    assert "tier" in result.stderr

    listed = run_cli(tmp_db, "list")
    assert listed.returncode == 0, listed.stderr
    assert "Ada Lovelace" not in listed.stdout


def test_cli_report_counts_by_tier(tmp_db):
    # One claim per tier, all filed at 09:00. At 13:01 only the gold one is overdue.
    file_claim(tmp_db, "Gold Passenger", "gold")
    file_claim(tmp_db, "Silver Passenger", "silver")
    file_claim(tmp_db, "Standard Passenger", "standard")

    escalated = run_cli(tmp_db, "escalate", now=AFTER_DEADLINE)
    assert escalated.returncode == 0, escalated.stderr

    result = run_cli(tmp_db, "report", now=AFTER_DEADLINE)
    assert result.returncode == 0, result.stderr

    # Each tier gets its own line with the open count followed by the overdue count.
    expected = {"gold": (0, 1), "silver": (1, 0), "standard": (1, 0)}
    for tier, (open_count, overdue_count) in expected.items():
        line = next((ln for ln in result.stdout.splitlines() if tier in ln), None)
        assert line is not None, f"no report line for {tier!r} in:\n{result.stdout}"
        numbers = [int(n) for n in re.findall(r"\d+", line)]
        assert numbers == [open_count, overdue_count], line
