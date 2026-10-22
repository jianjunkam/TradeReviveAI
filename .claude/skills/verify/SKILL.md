---
name: verify
description: Run the tests, show the diff and check it against AGENTS.md before a commit. Use when the user asks to verify or review a change.
disable-model-invocation: true
---
Verify the current change. Do not edit files and do not commit.

1. Run `pytest -q` and report the real result: how many tests passed and failed, and the name of each failure.
2. Run `git status`: no .env or other secret file may be listed. Then `git diff` (and `git diff --staged`): summarise each changed file in one line.
3. Check every changed line against the Rules and Never sections of AGENTS.md, and against blueprint.json. List each line that breaks one, as file:line and the rule.
4. Check the milestone's “Done when” in docs/BUILD_PLAN.md, item by item.
5. Say what the tests do not cover yet.

End with one line: "Ready to commit" or "Not ready", and why. The human decides.
