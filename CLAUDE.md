# Orbit Air Baggage Desk

Python 3.12 CLI + SQLite. Activate the venv first: `source .venv/bin/activate`

## Commands
- All tests: `pytest -q`
- One file: `pytest -q tests/test_claims.py`
- Lint: `ruff check .`
- Run: `python main.py --now 2026-11-02T14:00:00 <command>`

## Rules you cannot infer from the code
- Deadline hours by tier: gold = 4, silver = 24, standard = 72.
- Overdue means now is strictly later than the deadline (equal is not overdue).
- Never read the clock in claims.py or db.py; `now` is always a parameter. Only main.py may call datetime.now().
- A claim update and its history row go in one `with conn:` transaction.

## Working agreement
- Files under tests/ are the spec. Do not edit them; if a test looks wrong, say so and stop.
- Finish only when `pytest -q` and `ruff check .` are both clean.
- Never read or print .env or any secret.
