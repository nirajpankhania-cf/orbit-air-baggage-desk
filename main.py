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


def parse_now(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="Orbit Air baggage claims desk")
    parser.add_argument(
        "--now",
        type=parse_now,
        default=None,
        help="current time as ISO 8601 (defaults to the system clock)",
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
    rows = claims.get_history(conn, args.claim_id)
    if not rows:
        print(f"No history for claim {args.claim_id}")
        return
    for row in rows:
        old = row["old_status"] or "-"
        print(f"{row['changed_at']}  {old} -> {row['new_status']}  by {row['changed_by']}")


def cmd_seed(conn: sqlite3.Connection, args: argparse.Namespace, now: datetime) -> None:
    count = 0
    with open(args.csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            # The note column is stored as data only; it is never interpreted.
            claims.file_claim(
                conn,
                row["passenger"],
                row["flight"],
                row["type"],
                row["tier"],
                row.get("note") or "",
                now,
            )
            count += 1
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
    now = args.now if args.now is not None else datetime.now()
    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        COMMANDS[args.command](conn, args, now)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
