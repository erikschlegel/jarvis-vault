# erik-knowledge-base

A git-backed personal knowledge base using [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The LLM maintains a compounding wiki from immutable sources. You curate inputs and ask questions; the agent does summarizing, cross-referencing, and upkeep.

## Three layers

| Layer | Path | Role |
|-------|------|------|
| Raw sources | `raw/` | Immutable inputs — articles, notes, transcripts. Read-only for the agent. |
| Wiki | `wiki/` | LLM-maintained markdown — entities, concepts, source summaries, synthesis. |
| Schema | `AGENTS.md` | Operating rules: structure, conventions, ingest/query/lint workflows. |

## Quick start

1. Drop a source into `raw/sources/`.
2. Ask the agent to **ingest** it (see `AGENTS.md`).
3. Browse the wiki in Obsidian or your editor; follow links in `wiki/index.md`.
4. Ask questions against the wiki; file durable answers under `wiki/queries/`.
5. Periodically ask the agent to **lint** the wiki for orphans, contradictions, and stale claims.

## Navigation

- [wiki/index.md](wiki/index.md) — catalog of all wiki pages
- [wiki/log.md](wiki/log.md) — chronological activity log
- [wiki/overview.md](wiki/overview.md) — high-level map of active domains
- [AGENTS.md](AGENTS.md) — agent operating schema

## Obsidian

Open this repo as an Obsidian vault. Set **Attachment folder path** to `raw/assets/` so clipped images stay local. Use graph view to see how pages connect.