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

## State: this repo is your Obsidian vault

There is no separate database or app state. **The vault is the source of truth.**

| What | Where it lives |
|------|----------------|
| Wiki pages, links, synthesis | `wiki/*.md` on disk |
| Raw sources | `raw/sources/` |
| Images and attachments | `raw/assets/` |
| Activity history | `wiki/log.md` |
| Page catalog | `wiki/index.md` |
| Version history / backup | git commits on this repo |
| Obsidian UI (tabs, pane layout) | `.obsidian/workspace.json` (local only, not committed) |

Open **`erik-knowledge-base`** as an Obsidian vault (File → Open folder as vault). The agent and Obsidian read and write the same markdown files. You browse in Obsidian; the agent maintains `wiki/`; git records changes over time.

Vault settings (attachment path `raw/assets/`, wikilinks) are preconfigured in `.obsidian/app.json`.

**Karpathy's split:** Obsidian is the IDE, the LLM is the programmer, the wiki is the codebase.

### If you already have an Obsidian vault elsewhere

Point the vault at this folder instead, or move/symlink this repo to your vault path. The knowledge state must live in the markdown tree (`raw/` + `wiki/`), not in Obsidian's internal cache.