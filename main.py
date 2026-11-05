"""Orbit Air baggage desk CLI.

argparse only: parse arguments, open the database, call one function in claims.py, print.
This is the only module allowed to read the real clock (as the default for --now).
"""

import argparse
import csv
import sqlite3
import sys
from datetime import datetime

import claims
import db

USAGE_EPILOG = """\
commands:
  file      file a new claim            (--passenger --flight --type --tier [--note])
  list      list claims                 ([--status S] [--tier R])
  assign    assign a claim to an agent  (<id> --agent NAME)
  resolve   mark a claim resolved       (<id> --by NAME)
  close     close a resolved claim      (<id> --by NAME)
  escalate  escalate every overdue open or assigned claim
  history   show a claim's status history (<id>)
  seed      file claims from a CSV      (<path>; columns passenger,flight,type,tier,note)
  report    open and overdue counts by tier
"""


def parse_now(value: str) -> datetime:
    """Parse --now as a naive ISO 8601 timestamp; offset-aware values are refused."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"--now is not a valid ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise ValueError("--now must be a naive ISO timestamp without timezone offset")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Orbit Air baggage claims desk",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--now",
        default=None,
        help="current time as naive ISO 8601, e.g. 2026-11-01T13:01:00 (default: system clock)",
    )
    parser.add_argument("--db", default="claims.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_file = sub.add_parser("file", help="file a new claim")
    p_file.add_argument("--passenger", required=True)
    p_file.add_argument("--flight", required=True)
    p_file.add_argument("--type", dest="claim_type", required=True)
    p_file.add_argument("--tier", required=True)
    p_file.add_argument("--note", default="")

    p_list = sub.add_parser("list", help="list claims")
    p_list.add_argument("--status")
    p_list.add_argument("--tier")

    p_assign = sub.add_parser("assign", help="assign a claim to an agent")
    p_assign.add_argument("claim_id", type=int)
    p_assign.add_argument("--agent", required=True)

    p_resolve = sub.add_parser("resolve", help="mark a claim resolved")
    p_resolve.add_argument("claim_id", type=int)
    p_resolve.add_argument("--by", dest="changed_by", required=True)

    p_close = sub.add_parser("close", help="close a resolved claim")
    p_close.add_argument("claim_id", type=int)
    p_close.add_argument("--by", dest="changed_by", required=True)

    sub.add_parser("escalate", help="escalate every overdue open or assigned claim")

    p_history = sub.add_parser("history", help="show a claim's status history")
    p_history.add_argument("claim_id", type=int)

    p_seed = sub.add_parser("seed", help="file claims from a CSV file")
    p_seed.add_argument("csv_path")

    sub.add_parser("report", help="open and overdue counts by tier")
    return parser


def format_claim(row: sqlite3.Row) -> str:
    agent = row["agent"] or "-"
    return (
        f"#{row['id']}  {row['passenger']}  {row['flight']}  {row['claim_type']}  "
        f"{row['tier']}  {row['status']}  agent={agent}  deadline={row['deadline']}"
    )


def cmd_file(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    claim_id = claims.file_claim(
        conn, args.passenger, args.flight, args.claim_type, args.tier, args.note, now
    )
    print(f"Filed claim {claim_id}")


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    if args.status is not None and args.status not in claims.STATUSES:
        raise ValueError(f"unknown status {args.status!r}; expected one of {claims.STATUSES}")
    if args.tier is not None and args.tier not in claims.TIERS:
        raise ValueError(f"unknown tier {args.tier!r}; expected one of {claims.TIERS}")
    rows = claims.list_claims(conn, status=args.status, tier=args.tier)
    if not rows:
        print("No claims")
        return
    for row in rows:
        print(format_claim(row))


def cmd_assign(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    claims.assign_claim(conn, args.claim_id, args.agent, now)
    print(f"Assigned claim {args.claim_id} to {args.agent}")


def cmd_resolve(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    claims.resolve_claim(conn, args.claim_id, args.changed_by, now)
    print(f"Resolved claim {args.claim_id}")


def cmd_close(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    claims.close_claim(conn, args.claim_id, args.changed_by, now)
    print(f"Closed claim {args.claim_id}")


def cmd_escalate(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    ids = claims.escalate_overdue(conn, now)
    if ids:
        print("Escalated claims: " + ", ".join(str(i) for i in ids))
    else:
        print("No claims to escalate")


def cmd_history(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    claims.get_claim(conn, args.claim_id)  # raises ValueError if the id does not exist
    for row in claims.get_history(conn, args.claim_id):
        old = row["old_status"] or "-"
        print(f"{row['changed_at']}  {old} -> {row['new_status']}  by {row['changed_by']}")


def cmd_seed(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    with open(args.csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        claims.check_seed_columns(reader.fieldnames)
        # The note column is stored as data only; it is never interpreted.
        count = claims.seed_claims(conn, reader, now)
    print(f"Loaded {count} claims")


def cmd_report(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    counts = claims.report_counts(conn, now)
    for tier, bucket in counts.items():
        print(f"{tier}: open {bucket['open']}, overdue {bucket['overdue']}")


COMMANDS = {
    "file": cmd_file,
    "list": cmd_list,
    "assign": cmd_assign,
    "resolve": cmd_resolve,
    "close": cmd_close,
    "escalate": cmd_escalate,
    "history": cmd_history,
    "seed": cmd_seed,
    "report": cmd_report,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn: sqlite3.Connection | None = None
    try:
        now = parse_now(args.now) if args.now is not None else datetime.now()
        conn = db.connect(args.db)
        db.init_db(conn)
        COMMANDS[args.command](conn, args, now)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
