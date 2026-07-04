# wiki-core

The core LLM Wiki engine and skills. This plugin folder is also a Python package (`wiki_core`), so the deterministic engine ships with the plugin — consumers install it and get both the agent skills and the scripts they call.

## What it provides

### Skills

The agent loads the matching skill automatically based on your request.

| Skill | Operation | What it does |
|-------|-----------|--------------|
| [wiki-ingest](skills/wiki-ingest/SKILL.md) | Ingest | Fold one `raw/` source into the wiki — summary, entities, concepts, overview, index, log — then rebuild the index |
| [wiki-query](skills/wiki-query/SKILL.md) | Query | Answer questions against the wiki via the `jarvis-vault` MCP retrieval tools, with citations |
| [wiki-lint](skills/wiki-lint/SKILL.md) | Lint | Health-check the wiki — broken links, orphans, contradictions, stale claims, gaps — and fix with approval |

### Commands

Slash-commands you invoke explicitly. They are thin wrappers that route to the matching skill, so the names differ from the skills (skills override commands of the same name).

| Command | What it does |
|---------|--------------|
| `/wiki` | Orientation dashboard — health, recent context (pulse), and the pending ingest worklist |
| `/ingest [source \| all]` | Run the Ingest operation; no argument ingests the next pending source, `all` drains the worklist in bounded batches |
| `/query <question>` | Run the Query operation and answer with citations |
| `/lint [domain]` | Run the Lint operation — deterministic checks plus semantic review |
| `/save [title]` | File the current answer or analysis into the vault as a durable page |
| `/pending [domain]` | Show the ingest worklist read-only |
| `/setup` | Onboard or repair the engine — seed the vault, build the index, print the MCP entry |

### Console entry points

Run any from the repo root with `uv run <entry-point>`.

| Entry point | Purpose |
|-------------|---------|
| `wiki-plan` | Build the ingest worklist and update the source manifest |
| `wiki-add` | Generic on-ramp — land a local file or web URL into `raw/inbox/` with uniform `source_type`/`source_id` frontmatter |
| `wiki-pages` | Scaffold wiki pages, add index entries, append log entries |
| `wiki-search` | Build the retrieval index, run hybrid search, find near-duplicates |
| `wiki-verify` | Lint the wiki for structural and manifest defects |
| `wiki-mcp` | Launch the `jarvis-vault` MCP server (stdio) exposing the retrieval tools |

In addition, two onboarding commands make a fresh checkout usable in one step:

| Entry point | Purpose |
|-------------|---------|
| `wiki-init` | Validate `WIKI_VAULT`, seed an empty vault from the shipped template, build the search index, and print an mcp.json server entry |
| `wiki-doctor` | Report the same configuration and index-health checks read-only, so you can see what is missing before changing anything |

## Setup

From the repo root, with [uv](https://docs.astral.sh/uv/) installed:

1. Install dependencies and point the engine at your vault:

   ```bash
   uv sync
   cp ../../.env.example ../../.env   # then set WIKI_VAULT to your vault's wiki root
   ```

2. Seed the vault, build the index, and print an MCP entry — all idempotent:

   ```bash
   uv run wiki-init
   ```

3. Confirm the configuration is healthy:

   ```bash
   uv run wiki-doctor
   ```

`wiki-init` accepts `--force` (re-copy template files over existing ones) and `--no-build` (skip the index build, for offline setup before the embed model is cached). If you prefer to seed the vault by hand, see [Bootstrapping a vault](#bootstrapping-a-vault) below.

The retrieval server is wired through [.vscode/mcp.json](../../.vscode/mcp.json) at the repo root (`uv run wiki-mcp`, reading `WIKI_VAULT` from `.env`). To register the server in another MCP client, paste the snippet `wiki-init` prints. The engine is files-first: the MCP server is an accelerator over the same markdown, and the `wiki-search` CLI covers retrieval when the server is unavailable. See the access tiers in [AGENTS.md](../../AGENTS.md).

## Configuration

Locations resolve from environment variables, with a vault-relative default so an installed consumer never depends on the repo layout:

| Variable | Selects | Default |
|----------|---------|---------|
| `WIKI_VAULT` | Obsidian vault wiki root (holds `index.md`) — any synced or local folder | the author's personal vault fallback; set this to your own |
| `WIKI_INDEX_DIR` | retrieval index home | `<vault>/.wiki_index` |
| `WIKI_STATE` | ingest manifest | `<index>/ingest_state.json` |
| `WIKI_CONFIG` | ingest config | `<index>/ingest_config.json` |

Copy [templates/ingest_config.template.json](templates/ingest_config.template.json) to `<vault>/.wiki_index/ingest_config.json` (or wherever `WIKI_CONFIG` points) and tune the domain routing.

### Bootstrapping a vault

The wiki lives in your external Obsidian vault, not in this repo. `uv run wiki-init` (see [Setup](#setup)) seeds it for you; to seed a fresh vault by hand instead, copy the structure template into the directory `WIKI_VAULT` points at:

```bash
cp -R plugins/wiki-core/templates/vault/. "$WIKI_VAULT"/
```

The template in [templates/vault/](templates/vault/) carries the canonical layout the skills write into: `index.md` (with the `Overview`/`Sources`/`Entities`/`Concepts`/`Comparisons` sections that `wiki-pages index-add` appends under), `log.md` (the `wiki-pages log-append` target), `overview.md`, `synthesis.md`, and the `sources/`, `entities/`, `concepts/`, and `comparisons/` directories.

## Dependencies

`bm25s`, `fastembed`, `mcp[cli]`, and `tqdm` — see [pyproject.toml](pyproject.toml). The wider [wiki-connector-x](../wiki-connector-x/) plugin depends on this package.

## Source adapters

The engine is content-type agnostic — nothing here hardwires any single source. The `SourceAdapter` contract in `wiki_core.source_adapter` defines how a raw file becomes planner/scaffolder input: identity (`source_id`/`source_type`), body cleaning, canonical URL, author handle, media flags, and the extra frontmatter or notices a page emits. The shipped `DefaultAdapter` handles generic `doc`/`web` content and owns the `raw/inbox/` drop that `wiki-add` writes.

Connectors extend the engine by registering their own adapter under the `wiki_core.source_adapters` entry-point group. The core discovers them at runtime with `importlib.metadata.entry_points` and never imports connector code, so a new source type is a plugin that ships an adapter — no change to `wiki-core`. See [wiki-connector-x](../wiki-connector-x/) for a worked example.

See the repository [AGENTS.md](../../AGENTS.md) for the full wiki operating schema and the quality gate.
