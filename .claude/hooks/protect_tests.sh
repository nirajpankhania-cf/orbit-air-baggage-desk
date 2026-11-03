#!/usr/bin/env bash
# STRETCH GOAL 1
# PreToolUse hook for Edit|Write|MultiEdit.
# Blocks changes to any test file that is already committed to git.
# New, untracked test files are allowed, so the agent can still draft
# tests on a fresh branch; once a test is committed it is the spec.
# Exit 2 = block the tool call and tell Claude why.

input="$(cat)"

path="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
print(data.get("tool_input", {}).get("file_path", ""))
')"

[ -z "$path" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

case "$path" in
  */tests/*|tests/*) ;;
  *) exit 0 ;;
esac

# Is this test file tracked by git?
if git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
  echo "Blocked: $path is a committed test file. The tests are the spec and must not be edited by the agent. If you believe the test is wrong, stop and explain why instead." >&2
  exit 2
fi

exit 0
