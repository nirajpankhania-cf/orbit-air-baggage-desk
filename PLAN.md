# PLAN.md — Orbit Air Baggage Desk

## The problem

Orbit Air tracks lost, delayed and damaged baggage claims in spreadsheets and email threads. No-one owns a claim, can see when it was last touched and claims quietly blow past the response window the airline promises its passengers. We are building a small command line claims desk backed by SQLite that files claims, assigns them to agents, records every status change and automatically flags claims that are past their deadline so they get attention.

## The rules

**Validation.** A claim needs a passenger name and a flight number. The type must be one of `delayed`, `lost`, `damaged`. The tier must be one of `standard`, `silver`, `gold`. Anything else is refused with an error that names the bad field, and nothing is written.

**Deadlines.** When a claim is filed it gets a deadline = filed time + a tier-dependent response window: gold 4 hours, silver 24 hours, standard 72 hours. A claim is overdue only when the current time is after its deadline. At exactly the deadline it is still on time.

**Status changes.** Every claim starts `open`. The only legal moves are:

| From | To |
|---|---|
| open | assigned, escalated |
| assigned | resolved, escalated |
| escalated | assigned, resolved |
| resolved | closed |
| closed | — (terminal) |

Anything else (closing an open claim, resolving an open claim, reopening a closed one, escalating a resolved one…) is rejected with a clear error. Escalation has an extra condition: only `open` or `assigned` claims can be escalated and only when they are overdue.

**History.** Every status change, including the very first one when a claim is filed (nothing → open), writes a history row with old status, new status, who did it and when. The claim update and its history row are written in one transaction: if the history insert fails, the claim must be left exactly as it was.

**Time.** No rule code reads the system clock. The current time is always passed in as a parameter; the CLI's `--now` option supplies it (falling back to the real clock only in `main.py`).

## Tables

### `claims`

| column | type | notes |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| passenger | TEXT NOT NULL | CHECK length(trim(passenger)) > 0 |
| flight | TEXT NOT NULL | CHECK length(trim(flight)) > 0 |
| claim_type | TEXT NOT NULL | CHECK IN ('delayed','lost','damaged') |
| tier | TEXT NOT NULL | CHECK IN ('standard','silver','gold') |
| status | TEXT NOT NULL DEFAULT 'open' | CHECK IN ('open','assigned','escalated','resolved','closed') |
| agent | TEXT | NULL until assigned |
| note | TEXT | free text; treated as data only |
| filed_at | TEXT NOT NULL | ISO 8601 |
| deadline | TEXT NOT NULL | ISO 8601, filed_at + tier hours |

### `history`

| column | type | notes |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| claim_id | INTEGER NOT NULL REFERENCES claims(id) | |
| old_status | TEXT | NULL for the filing entry |
| new_status | TEXT NOT NULL | |
| changed_by | TEXT NOT NULL | agent name or 'system' |
| changed_at | TEXT NOT NULL | ISO 8601, the `now` passed in |

Foreign keys are switched on per connection (`PRAGMA foreign_keys = ON`).

## Module layout

- `db.py` — `connect(path)` and `init_db(conn)`; owns the schema and nothing else.
- `claims.py` — all rules: `file_claim`, `list_claims`, `ALLOWED_TRANSITIONS`, `change_status`, `assign_claim`, `resolve_claim`, `close_claim`, `is_overdue`, `escalate_overdue`, `get_history`. Every function takes the connection and, where time matters, `now: datetime`.
- `main.py` — argparse only. Parses `--now`, opens the DB, calls one function, prints.

## Branches and planned tests

### 1. `feature/schema-and-filing` (min 5, planned 8)

1. `test_init_db_creates_claims_and_history_tables`
2. `test_file_claim_returns_id_and_stores_fields`
3. `test_file_claim_rejects_blank_passenger`
4. `test_file_claim_rejects_blank_flight`
5. `test_file_claim_rejects_unknown_type`
6. `test_file_claim_rejects_unknown_tier`
7. `test_deadline_by_tier` (parametrised gold=4h, silver=24h, standard=72h)
8. `test_list_claims_filters_by_status_and_tier`
9. `test_filing_writes_initial_history_row` (old NULL → open)
10. `test_check_constraints_reject_bad_values_at_db_level` (raw INSERT with bad tier raises IntegrityError)

### 2. `feature/assign-and-status` (min 6, planned 8)

1. `test_assign_open_claim_sets_agent_and_status`
2. `test_assign_escalated_claim_allowed`
3. `test_resolve_assigned_claim`
4. `test_close_resolved_claim`
5. `test_every_allowed_transition_in_table` (parametrised over the dict)
6. `test_close_open_claim_rejected`
7. `test_resolve_open_claim_rejected`
8. `test_change_from_closed_rejected`
9. `test_assign_resolved_claim_rejected`
10. `test_history_row_has_old_new_who_when`

### 3. `feature/deadlines-and-escalation` (min 6, planned 7)

1. `test_not_overdue_one_minute_before`
2. `test_not_overdue_exactly_at_deadline`
3. `test_overdue_one_minute_after`
4. `test_escalate_moves_overdue_open_and_assigned`
5. `test_escalate_leaves_resolved_closed_and_on_time_alone`
6. `test_escalate_returns_escalated_ids`
7. `test_escalate_writes_history_row`
8. `test_rollback_when_history_write_fails` — rename the `history` table before calling `assign_claim`, expect an exception, assert the claim status is still `open`

### 4. `feature/cli` (min 3, planned 4)

1. `test_cli_file_and_list` (subprocess or calling `main.main(argv)`)
2. `test_cli_now_option_drives_escalation`
3. `test_cli_seed_loads_csv`
4. `test_cli_invalid_input_prints_error_and_exits_nonzero`

Total planned ≈ 30, minimum required 20.

## Risks and how I will handle them

1. **The agent reads the real clock inside the rules** (e.g. `now=None` defaulting to `datetime.now()`), which makes deadline tests flaky and breaks `--now`. Mitigation: every rule function takes `now` as a required parameter; after each branch I grep `claims.py`/`db.py` for `now()`/`utcnow` and reject the diff if it is there.
2. **Claim update and history insert end up in separate commits**, so a failed history write leaves a changed claim. Mitigation: use the connection as a context manager (`with conn:`) around both writes and keep a rollback test that fails on purpose if the transaction is removed.
3. **The agent edits a test to make it pass.** Mitigation: tests are committed before feature code, a PreToolUse hook blocks edits to tracked test files, and I run `git diff --stat tests/` before every commit.
4. **The Stop hook loops forever** when a test is still failing. Mitigation: the hook honours `stop_hook_active` so it only sends the agent back once; if tests still fail I read the failure myself and rewrite the prompt.
5. **Secret leak.** Mitigation: `.gitignore` is committed before `.env` exists; GitHub push protection is on; final audit searches the whole history for `.env` and the fake key.
6. **Prompt injection in claim notes.** The seed file contains a note that tells the agent to print `.env`. Mitigation: notes are data only; the deny rule on `Read(.env)` means even a fooled agent cannot read it.
