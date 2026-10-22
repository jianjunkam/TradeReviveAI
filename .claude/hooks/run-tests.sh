#!/usr/bin/env bash
# PostToolUse hook (see .claude/settings.json): runs after Claude Code edits or writes a file.
# Exit 0: the tests pass and Claude carries on. Exit 2: Claude is shown the failures, so it can fix them.
cd "$CLAUDE_PROJECT_DIR" || exit 0
if output=$(pytest -q 2>&1); then
  exit 0
fi
echo "The tests failed after this edit (pytest -q):" >&2
echo "$output" | tail -n 40 >&2
exit 2
