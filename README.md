# jarvis-vault

Personal knowledge base using [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The LLM incrementally builds and maintains a persistent, interlinked wiki from immutable raw sources. You curate inputs and ask questions; the agent summarizes, cross-references, and keeps the wiki current.

The wiki itself lives in an external Obsidian vault (resolved via `WIKI_VAULT`). This repo holds the agentic skills, the deterministic engine, and the templates that populate that vault consistently.

## Three layers

| Layer | Where |
|-------|-------|
| Raw sources | `raw/` in the vault (sibling of the wiki) — immutable; agent reads only |
| The wiki | the external Obsidian vault at `WIKI_VAULT` — agent-maintained markdown |
| The schema | `AGENTS.md` — structure and workflows |

## Setup

You need [uv](https://docs.astral.sh/uv/) (the Python toolchain) and a folder to hold the wiki — ideally an [Obsidian](https://obsidian.md/) vault, though any directory works.

1. **Install dependencies.** From the repo root:

   ```bash
   uv sync
   ```

2. **Point the engine at your vault.** Copy the example env file and set `WIKI_VAULT` to the absolute path of your vault's wiki root (the folder that will hold `index.md`):

   ```bash
   cp .env.example .env
   # then edit .env and set WIKI_VAULT=/absolute/path/to/your-vault/wiki
   ```

   The `.env` is discovered automatically from the working directory upward, then this repo, then `~/.config/jarvis-vault/.env`. A real exported environment variable always wins over the file.

3. **Seed the vault and build the index.** One command seeds an empty vault from the shipped template, builds the search index, and prints an MCP server entry:

   ```bash
   uv run wiki-init
   ```

   Re-running is safe — it never overwrites existing pages (pass `--force` to re-copy the template, `--no-build` to skip the index build when offline).

4. **Verify.** `wiki-doctor` reports the same checks read-only, so you can confirm what is configured before ingesting:

   ```bash
   uv run wiki-doctor
   ```

5. **Wire up the MCP retrieval server.** This repo already ships [.vscode/mcp.json](.vscode/mcp.json), so VS Code picks up the `jarvis-vault` server (`uv run wiki-mcp`) automatically — it reads `WIKI_VAULT` from your `.env`, no prompt. For another client, paste the snippet `wiki-init` printed (the portable `uv run --directory <repo>` form) into that client's MCP config.

The engine is files-first and degrades gracefully: even without the MCP server, every wiki page is plain markdown you can read and edit directly, and the `wiki-search` CLI covers retrieval. See the access tiers in [AGENTS.md](AGENTS.md) for the full files → CLI → MCP progression.

For the X (Twitter) connector — API credentials, fetching likes and bookmarks, local video transcription — continue with the [wiki-connector-x setup](plugins/wiki-connector-x/README.md#setup).

## Install as a Copilot plugin

The skills also ship as installable GitHub Copilot plugins, declared in [.github/plugin/marketplace.json](.github/plugin/marketplace.json). Add this repo as a local marketplace, then install the plugins you want:

```text
/plugin marketplace add erikschlegel/jarvis-vault
/plugin install wiki-core@jarvis-vault
/plugin install wiki-connector-x@jarvis-vault
```

`wiki-core` is the engine and its ingest/query/lint skills; `wiki-connector-x` adds the X (Twitter) pre-ingest skills and depends on `wiki-core`. Installing the plugins gives you the skills; the deterministic engine still resolves your vault from `WIKI_VAULT`, so complete the [Setup](#setup) steps above regardless of how you install.

## Workflow

1. Drop a source into `raw/` (Obsidian Web Clipper works well).
2. Tell the agent to **ingest** it.
3. Browse the vault in Obsidian — graph view, links, `index.md`.
4. **Query** the wiki; file durable answers into the vault's `comparisons/`.
5. Periodically ask the agent to **lint** the wiki.

## Skills

The engine and its skills ship as two plugins under [plugins/](plugins/), a uv workspace. Each plugin directory is also its Python package, so the deterministic scripts travel with the plugin. The agent loads the matching skill automatically based on your request.

| Skill | Plugin | Operation | What it does |
|-------|--------|-----------|--------------|
| [x-import](plugins/wiki-connector-x/skills/x-import/SKILL.md) | wiki-connector-x | Pre-ingest | Clip X likes and bookmarks into `raw/` (API, account archive, bookmarks JSON, or Web Clipper folder) |
| [x-transcribe](plugins/wiki-connector-x/skills/x-transcribe/SKILL.md) | wiki-connector-x | Pre-ingest | Backfill local ASR transcripts for caption-less X videos so their spoken content is ingestible |
| [wiki-ingest](plugins/wiki-core/skills/wiki-ingest/SKILL.md) | wiki-core | Ingest | Fold one `raw/` source into the wiki — summary, entities, concepts, overview, index, log — then rebuild the index |
| [wiki-query](plugins/wiki-core/skills/wiki-query/SKILL.md) | wiki-core | Query | Answer questions against the wiki via the `jarvis-vault` MCP retrieval tools, with citations |
| [wiki-lint](plugins/wiki-core/skills/wiki-lint/SKILL.md) | wiki-core | Lint | Health-check the wiki — broken links, orphans, contradictions, stale claims, gaps — and fix with approval |

Typical chain: **x-import** → **x-transcribe** → **wiki-ingest** → **wiki-query**, with **wiki-lint** run periodically.

The engine exposes console entry points (`wiki-plan`, `wiki-pages`, `wiki-search`, `wiki-verify`, `wiki-mcp`; `x-fetch`, `x-import`, `x-refresh-streams`, `x-transcribe`) — run any with `uv run <entry-point>`. Vault and index locations resolve from `WIKI_VAULT` / `WIKI_INDEX_DIR` / `WIKI_STATE` / `WIKI_CONFIG`; see [AGENTS.md](AGENTS.md) for defaults.

## Obsidian vault

The wiki lives in your external Obsidian vault — markdown on disk, git for history. Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase. Point `WIKI_VAULT` at the vault's wiki root, and seed a fresh vault from the structure template in [plugins/wiki-core/templates/vault/](plugins/wiki-core/templates/vault/) (see the [wiki-core README](plugins/wiki-core/README.md) for the bootstrap command). The vault's `index.md` is the catalog and `log.md` the timeline.

Raw sources live in the vault alongside the wiki (`raw/`, a sibling of the wiki root, with attachments under `raw/assets/`).

See [docs/llm-wiki.md](docs/llm-wiki.md) for Karpathy's full pattern description.