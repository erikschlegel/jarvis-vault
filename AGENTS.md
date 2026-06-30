# LLM Wiki — Operating Schema

This repository implements [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Read `docs/llm-wiki.md` for the full idea. Co-evolve this file with the user as the knowledge base grows.

## Core idea

Do not treat this as RAG. The LLM **incrementally builds and maintains a persistent wiki** — interlinked markdown between the user and immutable raw sources. Knowledge is compiled once and kept current. Cross-references, contradictions, and synthesis should already be in the wiki before the user asks.

The user curates sources, explores, and asks questions. **The LLM writes and maintains almost all of the wiki.** The user reads it in Obsidian.

**Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase.**

## Architecture

Three layers:

| Layer | Path | Rule |
|-------|------|------|
| Raw sources | `raw/` in the vault (sibling of `wiki/`) | Immutable. Read only. Never modify unless the user explicitly requests file hygiene. |
| The wiki | external Obsidian vault at `WIKI_VAULT` | LLM-owned. Summaries, entity pages, concept pages, comparisons, overview, synthesis. |
| The schema | `AGENTS.md` | This file. Structure, conventions, workflows. |

Attachment images: `raw/assets/`.

## Wiki layout

The wiki lives in the external Obsidian vault that `WIKI_VAULT` resolves to. Throughout this file, `wiki/` denotes that vault root (not a folder in this repo). The canonical structure below ships as a seed template in `plugins/wiki-core/templates/vault/`; copy it into a fresh vault to bootstrap it.

```
<WIKI_VAULT>/
  pulse.md       # recent-context cache — rewritten each session/ingest/query
  index.md       # content catalog — update on every ingest
  log.md         # append-only timeline
  overview.md    # high-level map
  synthesis.md   # evolving thesis / cross-cutting synthesis
  sources/       # one summary page per ingested source
  entities/      # people, orgs, products, places, works
  concepts/      # topics, themes, methods
  comparisons/   # comparisons, analyses, and durable query artifacts
```

New pages: lowercase kebab-case filenames, relative markdown links, cross-link aggressively, update `wiki/index.md`, note contradictions explicitly.

## Operations

### Ingest

The user drops a source into `raw/` and asks you to process it.

1. Read the source and any `raw/assets/` it references.
2. Discuss key takeaways with the user when useful — Karpathy prefers **one source at a time with the user involved**.
3. Write a summary page in `wiki/sources/`.
4. Update relevant entity and concept pages across the wiki (a single source may touch 10–15 pages).
5. Update `wiki/overview.md` and `wiki/synthesis.md` when the big picture shifts.
6. Update `wiki/index.md`.
7. Append to `wiki/log.md`.
8. Refresh `wiki/pulse.md` — rewrite the working context and prepend the new source to the recent list.

Integrate into the existing wiki — do not merely index for later retrieval.

### Query

The user asks questions against the wiki.

1. Read `wiki/pulse.md` first (recent context), then `wiki/index.md`.
2. Open relevant pages, then synthesize an answer **with citations** to wiki paths.
3. **File durable answers back into the wiki** — comparisons, analyses, connections. Do not let valuable work die in chat history. Save under `wiki/comparisons/` (or the appropriate category).
4. Update `wiki/index.md`, refresh `wiki/pulse.md`, and append a `query` entry to `wiki/log.md` when filing a new page.

Answers may be markdown pages, comparison tables, or other formats the user requests (Marp slides, charts, etc.).

### Lint

When the user asks for a health check:

Look for:

- Contradictions between pages
- Stale claims newer sources have superseded
- Orphan pages with no inbound links
- Important concepts mentioned but lacking their own page
- Missing cross-references
- Data gaps that could be filled with a web search

Suggest new questions and sources to investigate. Apply fixes with user approval. Append a `lint` entry to `wiki/log.md`.

## Indexing and logging

### `wiki/pulse.md` (recent-context cache)

A short (~500-word) rolling summary of recent activity and the current working context, kept for session continuity. Read it first on query so the next session resumes without a recap. Unlike `index.md` and `log.md`, it is **rewritten in prose** (like `overview.md`/`synthesis.md`), not appended or deduped: refresh it on each ingest and each durable query, trimming stale entries. The MCP server exposes it as `get_pulse()`.

### `wiki/index.md` (content-oriented)

Catalog of every wiki page: link, one-line summary, optional metadata (date, source count). Organized by category: overview, synthesis, sources, entities, concepts, comparisons.

Update on every ingest. On query, read the pulse then the index, then drill into pages. At moderate scale (~100 sources, hundreds of pages) the index is enough — no embedding RAG required.

### `wiki/log.md` (chronological)

Append-only record of ingests, queries, and lint passes. Use a consistent prefix:

```md
## [YYYY-MM-DD] ingest | Article Title

- Summary of what changed
- Pages touched: [page](relative/path.md)
```

Parseable with: `grep "^## \[" wiki/log.md | tail -5`

## Obsidian and git

The wiki and the raw sources are siblings inside an external Obsidian vault: the wiki root is resolved via `WIKI_VAULT` (`<vault>/wiki`) and the raw sources sit beside it at `<vault>/raw`. This repo holds the engine and the skills that populate them. The repo is tracked with git; the vault is markdown on disk, synced by Obsidian.

- **Obsidian Web Clipper** → save articles into `raw/`
- **Attachment folder:** `raw/assets/` (configured in the vault's `.obsidian/app.json`)
- **Download attachments for current file** hotkey after clipping (e.g. Ctrl+Shift+D)
- **Graph view** to see wiki shape, hubs, and orphans. The seed template ships a tuned `.obsidian/graph.json` that filters to `path:wiki/` (so `raw/` stays out of the graph) and color-codes `entities`, `concepts`, `sources`, and `comparisons`. Copy it into the live vault's `.obsidian/` to apply the same defaults.
- **Default layout** — the seed template also ships `.obsidian/workspace.json` so a fresh vault opens straight into the Graph view, with file-explorer/search/bookmarks in the left sidebar and backlinks/outgoing-links/tags/properties/outline collapsed on the right. This only seeds the first launch; the live vault's `workspace.json` is gitignored because Obsidian rewrites it on every layout change.
- Optional: **Dataview** if you add YAML frontmatter; **Marp** for slides from wiki content

For images in sources: read text first, then view referenced images separately if needed.

### X tweet sources with video (`raw/x/`)

Videos are **not stored locally**. Each source markdown may include a `videos:` block in frontmatter:

```yaml
videos:
  - page: "https://x.com/handle/status/123/video/1"
    stream: "https://video.twimg.com/amplify_video/.../file.mp4"
    transcript: "raw/assets/x/123/video-1-transcript.txt"
```

- **`stream`** — direct MP4 URL for coding agents to fetch, transcode, or analyze video without a browser.
- **`page`** — human-readable X player URL.
- **`transcript`** — local caption text when X provided auto-generated subtitles.

Do not download MP4s into the repo unless the user explicitly asks. Prefer `videos[].stream` over scraping the X page.

## Access tiers

The wiki is markdown first; the engine is an accelerator, not a gate. Three tiers, each a superset of the one below:

- **Tier 0 — files (always available).** Every wiki page, including `pulse.md` and `index.md`, is markdown on disk under `WIKI_VAULT`. Read and write it with native file tools at the vault path. Ingest, Query, and Lint all work at this tier with no package install: read `pulse.md` then `index.md` to orient, open pages directly, and write pages back. This is the Karpathy baseline.
- **Tier 1 — `wiki-search` CLI.** Installing `wiki-core` adds hybrid BM25 + dense retrieval (`uv run wiki-search`) plus the deterministic authoring helpers (`wiki-pages`, `wiki-plan`, `wiki-verify`) and onboarding (`wiki-init`, `wiki-doctor`). Use it when scanning `index.md` by hand is too slow to find the right pages, or to scaffold/roll-up pages mechanically.
- **Tier 2 — `erik-wiki` MCP server.** `wiki-mcp` wraps the Tier 1 engine as MCP tools (`get_pulse`, `get_index`, `search_wiki`, `expand_neighbors`, `read_page`) for GUI and headless clients that prefer tool calls over a terminal. It reads the same files Tier 0 does, so anything it returns is also reachable by reading the vault directly.

`get_pulse()` / `get_index()` are conveniences over `pulse.md` / `index.md`; when the server is unavailable, read those files directly. The MCP tools fail soft — an unset `WIKI_VAULT` or unbuilt index returns an actionable message rather than crashing — so a missing Tier 2 never blocks Tier 0 work.

## Optional tools

At larger scale, add local search (e.g. [qmd](https://github.com/tobi/qmd)) — not required initially.

## Engine and layout

The deterministic engine ships as two installable packages under `plugins/`, a uv workspace:

- `plugins/wiki-core/` — the wiki engine (`wiki_core` package) and its skills. Console entry points: `wiki-plan` (ingest worklist + manifest), `wiki-pages` (scaffold/index-add/log-append), `wiki-search` (build/search/duplicates), `wiki-verify` (lint), and `wiki-mcp` (the `erik-wiki` MCP server).
- `plugins/wiki-connector-x/` — the X (Twitter) connector (`wiki_connector_x` package, depends on `wiki-core`) and its skills. Entry points: `x-fetch`, `x-import`, `x-refresh-streams`, `x-transcribe`.

Run any of them with `uv run <entry-point>` from the repo root. Each plugin directory **is** its Python package, so the scripts ship with the plugin for consumers.

Locations resolve from environment variables, with a vault-relative default so an installed consumer never depends on the repo layout:

| Variable | Selects | Default |
|----------|---------|---------|
| `WIKI_VAULT` | Obsidian vault wiki root (holds `index.md`) — any synced or local folder | the author's personal vault fallback; set this to your own |
| `WIKI_RAW` | immutable raw sources root (the sibling of the wiki) | `<vault>/../raw` |
| `WIKI_INDEX_DIR` | retrieval index home | `<vault>/.wiki_index` |
| `WIKI_STATE` | ingest manifest | `<index>/ingest_state.json` |
| `WIKI_CONFIG` | ingest config | `<index>/ingest_config.json` |

The committed [plugins/wiki-core/templates/ingest_config.template.json](plugins/wiki-core/templates/ingest_config.template.json) is the starting point for a personal config; copy it to `<vault>/.wiki_index/ingest_config.json` (or wherever `WIKI_CONFIG` points) and tune the domain routing.

## Code quality

The Python packages under `plugins/*/src/` are gated by deterministic linting and type checking. Run the gate after any change to that Python code, and before committing it:

```bash
uv run ruff format --check   # formatting is consistent
uv run ruff check            # lint (fixed rule set, no auto-discovered plugins)
uv run mypy                  # strict static types
uv run pytest                # hermetic engine tests + MCP stdio contract
```

Use `uv run ruff format && uv run ruff check --fix` to apply fixes. Determinism comes from four places: `uv.lock` pins exact tool versions, the `ruff` rule set in `pyproject.toml` is explicit, `mypy` runs in `strict` mode, and `pytest` builds a throwaway index over a fixture vault in `tmp_path` rather than the live wiki. Each tool is configured to target only the enforced surface, so a bare invocation equals the gate.

Scope note: `ruff` and `mypy` cover `plugins/*/src`, and `ruff` and `pytest` also cover `plugins/*/tests`. New code and tests are enforced automatically — keep them green. The `integration`-marked MCP contract test self-skips when the real index is not built; deselect it offline with `uv run pytest -m "not integration"`.

This gate applies to code changes. The Ingest, Query, and Lint operations above write markdown to `wiki/`, not Python, so they do not trigger it.

## Boundaries

- Never modify `raw/` during ingest.
- Prefer updating existing wiki pages over creating duplicates.
- Leave the wiki more connected after every operation.
- Persist knowledge in `wiki/`, not only in conversation.