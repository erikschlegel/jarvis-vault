---
description: Clip X (Twitter) likes and bookmarks into raw/ as immutable source markdown.
argument-hint: "[archive | json | folder path]"
---

# Import X sources

Run the X import pre-ingest pipeline per the x-import skill (`plugins/wiki-connector-x/skills/x-import/SKILL.md`).

Source: $ARGUMENTS

- With no argument, pull from the X API (`uv run x-fetch`).
- With a path to an account archive, a bookmarks JSON export, or a Web Clipper folder, import via `uv run x-import`.

Land sources under `raw/x/` only — never write to the vault. When done, hand off to `/ingest`.
