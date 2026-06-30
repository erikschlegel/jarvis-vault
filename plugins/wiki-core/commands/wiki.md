---
description: Show wiki status and the next thing to do — health, recent context, and the pending ingest worklist.
---

# Wiki status

Give me an orientation on the jarvis-vault LLM Wiki and recommend the next action. Report read-only — do not write to the vault or modify `raw/`.

1. Run `uv run wiki-doctor` and surface any FAIL or warn lines, including any printed plugin-install commands.
2. Read the recent-context cache: call the `jarvis-vault` MCP `get_pulse()` tool, or read `pulse.md` at the `WIKI_VAULT` path when the server is unavailable.
3. Summarize the ingest worklist with `uv run wiki-plan` — how many sources are new, pending, changed, or missing.
4. Recommend the single most useful next step — ingest a source, answer an open question, or run a lint pass — and wait for my go-ahead before acting.
