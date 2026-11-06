#!/usr/bin/env bash
# STRETCH GOAL 1
# PreToolUse hook for Edit|Write|MultiEdit|Bash.
# Blocks changes to any test file that is already committed to git.
# New, untracked test files are allowed, so the agent can still draft
# tests on a fresh branch; once a test is committed it is the spec.
# Bash is covered too, because an agent can route around an Edit-only
# guard with shell redirection, sed -i, mv, cp or tee.
# Exit 2 = block the tool call and tell Claude why.

input="$(cat)"

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

tool="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_name", ""))
except Exception:
    print("")
')"

block() {
  echo "Blocked: $1 is a committed test file. The tests are the spec and must not be edited by the agent (not with Edit, Write, or shell commands). If you believe the test is wrong, stop and explain why instead." >&2
  exit 2
}

if [ "$tool" = "Bash" ]; then
  cmd="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    print("")
')"
  # Only care about commands that both mention a tests path and look like a write.
  if printf '%s' "$cmd" | grep -Eq '(^|[^A-Za-z0-9_])tests/' \
     && printf '%s' "$cmd" | grep -Eq '(>|\bmv\b|\bcp\b|\bsed\b.*-i|\btee\b|\brm\b|\btruncate\b|\bpatch\b)'; then
    # Block if any tracked test file is named in the command.
    for f in $(git ls-files -- tests); do
      case "$cmd" in *"$f"*) block "$f" ;; esac
    done
    # Also block writes to tests/ by directory even if no exact filename matched.
    if printf '%s' "$cmd" | grep -Eq '(>|\bmv\b|\bcp\b|\btee\b)[^|;&]*tests/'; then
      block "a file under tests/"
    fi
  fi
  exit 0
fi

# Edit / Write / MultiEdit
path="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")
')"

[ -z "$path" ] && exit 0

case "$path" in
  */tests/*|tests/*) ;;
  *) exit 0 ;;
esac

if git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
  block "$path"
fi

exit 0
