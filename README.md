# Orbit Air Baggage Desk

A command line claims desk for lost, delayed and damaged baggage, backed by SQLite.
Built with Claude Code as the coding agent; this README is the evidence trail.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fake key, never committed
```

## Run

```bash
python main.py file --passenger "Ada Lovelace" --flight OA101 --type lost --tier gold --note "Black suitcase"
python main.py list [--status open] [--tier gold]
python main.py assign <id> --agent sam
python main.py resolve <id> --by sam
python main.py close <id> --by sam
python main.py --now 2026-11-02T14:00:00 escalate
python main.py history <id>
python main.py seed seed_claims.csv
```

## Test and lint

```bash
pytest -q
ruff check .
```

## Walkthrough

<!-- short end-to-end: file -> assign -> (time passes) -> escalate -> resolve -> close -> history -->

## Linear Issues

<!-- four links, project "Orbit Air Baggage Desk" -->

## Setup Check

<!-- what you asked Claude Code to do to test the deny rule, and what happened -->

## Agent Log

### feature/schema-and-filing
<!-- Prompt / What the agent did / What I checked or changed -->

### feature/assign-and-status

### feature/deadlines-and-escalation

### feature/cli

## Hidden Instruction Check

<!-- what Claude Code did with the note in seed_claims.csv, and why .env is still protected -->

## Overdue Demonstration

<!-- commands with --now, the escalation, the list of escalated claims, real output -->

## Code Review

<!-- what /code-review found on the last PR and what you did about each finding -->

## Stretch goals

### STRETCH GOAL 1 — hook blocking test edits
<!-- paste the blocked-edit message -->

### STRETCH GOAL 2 — report command
### STRETCH GOAL 3 — GitHub Actions
### STRETCH GOAL 4 — Dockerfile
