#!/usr/bin/env bash
# Stop hook: run the test suite when Claude tries to finish.
# Exit 2 = block the stop and send the failure output back to Claude.
# Exit 0 = allow the stop.

input="$(cat)"

# Claude Code sets stop_hook_active=true when it is already continuing
# because of this hook. Allow the stop then, so we never loop forever.
if printf '%s' "$input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

if [ -x .venv/bin/pytest ]; then
  PYTEST=".venv/bin/pytest"
else
  PYTEST="python3 -m pytest"
fi

output="$($PYTEST -q 2>&1)"
status=$?

# 0 = all passed, 5 = no tests collected (fresh repo) -> both fine.
if [ "$status" -eq 0 ] || [ "$status" -eq 5 ]; then
  exit 0
fi

{
  echo "pytest failed (exit $status). You are not done yet."
  echo "Fix the implementation so the tests pass. Do NOT edit files under tests/."
  echo "--- last 40 lines of pytest output ---"
  printf '%s\n' "$output" | tail -n 40
} >&2
exit 2
