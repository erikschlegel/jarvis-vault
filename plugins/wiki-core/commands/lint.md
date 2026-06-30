---
description: Health-check the wiki for broken links, orphans, contradictions, and gaps — the Lint operation.
argument-hint: "[domain]"
---

# Lint the wiki

Run the **Lint** operation per the wiki-lint skill (`plugins/wiki-core/skills/wiki-lint/SKILL.md`).

Scope: $ARGUMENTS

Run the deterministic `uv run wiki-verify` first, then the skill's semantic review. Limit the pass to the scope above when one is given.
