---
description: Fold a raw/ source into the wiki — the Ingest operation.
argument-hint: "[source]"
---

# Ingest a source

Run the **Ingest** operation per the wiki-ingest skill (`plugins/wiki-core/skills/wiki-ingest/SKILL.md`).

Source: $ARGUMENTS

- If a source is named above, ingest that one.
- With no argument, compute the worklist with `uv run wiki-plan` and ingest the next pending source.

The skill owns the write order, the `--mark-ingested` finalize step, and the `raw/` boundary.
