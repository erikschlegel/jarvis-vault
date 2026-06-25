# erik-knowledge-base

Personal knowledge base using [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The LLM incrementally builds and maintains a persistent, interlinked wiki from immutable raw sources. You curate inputs and ask questions; the agent summarizes, cross-references, and keeps the wiki current.

## Three layers

| Layer | Path |
|-------|------|
| Raw sources | `raw/` — immutable; agent reads only |
| The wiki | `wiki/` — agent-maintained markdown |
| The schema | `AGENTS.md` — structure and workflows |

## Workflow

1. Drop a source into `raw/` (Obsidian Web Clipper works well).
2. Tell the agent to **ingest** it.
3. Browse `wiki/` in Obsidian — graph view, links, `wiki/index.md`.
4. **Query** the wiki; file durable answers into `wiki/comparisons/`.
5. Periodically ask the agent to **lint** the wiki.

## Obsidian vault

Open this folder as your Obsidian vault. The vault **is** the state — markdown on disk, git for history. Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase.

- Attachments: `raw/assets/` (preconfigured)
- Catalog: [wiki/index.md](wiki/index.md)
- Log: [wiki/log.md](wiki/log.md)

See [docs/llm-wiki.md](docs/llm-wiki.md) for Karpathy's full pattern description.