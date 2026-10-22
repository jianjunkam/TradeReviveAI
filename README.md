# TradeRevive AI: build pack

Made with GigaLab Module 8 (SaaS Builder Lab) on 2026-10-22. Stack: confirmed.

`blueprint.json` is the source of truth: every requirement, choice and target as data. The documents in `docs/` explain it, and the tests in the acceptance folder fail until each feature is built.

1. Put these files in an empty folder and start a Git repository there (`git init`).
2. Copy `.env.example` to `.env` and fill it in. Never commit `.env`.
3. Open the folder in your coding agent:
   - Claude Code: run `claude` in the folder. It reads CLAUDE.md (which imports AGENTS.md) and `.claude/settings.json`.
   - Codex and Cursor read AGENTS.md.
   - GitHub Copilot reads AGENTS.md and `.github/copilot-instructions.md`.
   - Gemini CLI reads GEMINI.md, which imports AGENTS.md.
   - Any other agent: start with “Read AGENTS.md first.” (your choice)
4. Start with milestone M0 in `docs/BUILD_PLAN.md`: paste its prompt, approve the plan, check the tests.
5. One milestone per session. Record each one in GigaLab’s Build guide tab.
6. To change a requirement or the stack: change it in GigaLab, download the pack again, and copy the new `blueprint.json` and `docs/` over the old ones.
