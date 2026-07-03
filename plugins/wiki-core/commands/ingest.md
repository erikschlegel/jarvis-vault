---
description: Fold a source into the wiki — the Ingest operation.
argument-hint: "[source | path | url | text]"
---

# Ingest a source

Run the **Ingest** operation per the wiki-ingest skill (`plugins/wiki-core/skills/wiki-ingest/SKILL.md`).

Source: $ARGUMENTS

The argument can take any of these shapes — the skill lands new content into `raw/inbox/` (via `wiki-add`) before ingesting, so you never have to add it by hand:

- **An existing source** — a `source_id`, or a file already under `raw/`. Ingest that one.
- **A local file path or an `http(s)://` URL** — auto-landed with `uv run wiki-add <arg>`, then ingested.
- **An attached file or a pasted/typed text block** (no path) — auto-landed with `uv run wiki-add --stdin`, then ingested.
- **No argument** — compute the worklist with `uv run wiki-plan` and ingest the next pending source.

The skill owns the classification, the write order, the `--mark-ingested` finalize step, and the `raw/` boundary.
