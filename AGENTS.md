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
| Raw sources | `raw/` | Immutable. Read only. Never modify unless the user explicitly requests file hygiene. |
| The wiki | `wiki/` | LLM-owned. Summaries, entity pages, concept pages, comparisons, overview, synthesis. |
| The schema | `AGENTS.md` | This file. Structure, conventions, workflows. |

Attachment images: `raw/assets/`.

## Wiki layout

```
wiki/
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

Integrate into the existing wiki — do not merely index for later retrieval.

### Query

The user asks questions against the wiki.

1. Read `wiki/index.md` first.
2. Open relevant pages, then synthesize an answer **with citations** to wiki paths.
3. **File durable answers back into the wiki** — comparisons, analyses, connections. Do not let valuable work die in chat history. Save under `wiki/comparisons/` (or the appropriate category).
4. Update `wiki/index.md` and append a `query` entry to `wiki/log.md` when filing a new page.

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

### `wiki/index.md` (content-oriented)

Catalog of every wiki page: link, one-line summary, optional metadata (date, source count). Organized by category: overview, synthesis, sources, entities, concepts, comparisons.

Update on every ingest. On query, read the index first, then drill into pages. At moderate scale (~100 sources, hundreds of pages) the index is enough — no embedding RAG required.

### `wiki/log.md` (chronological)

Append-only record of ingests, queries, and lint passes. Use a consistent prefix:

```md
## [YYYY-MM-DD] ingest | Article Title

- Summary of what changed
- Pages touched: [page](relative/path.md)
```

Parseable with: `grep "^## \[" wiki/log.md | tail -5`

## Obsidian and git

This repo **is** the Obsidian vault. State is markdown on disk; git is version history.

- **Obsidian Web Clipper** → save articles into `raw/`
- **Attachment folder:** `raw/assets/` (configured in `.obsidian/app.json`)
- **Download attachments for current file** hotkey after clipping (e.g. Ctrl+Shift+D)
- **Graph view** to see wiki shape, hubs, and orphans
- Optional: **Dataview** if you add YAML frontmatter; **Marp** for slides from wiki content

For images in sources: read text first, then view referenced images separately if needed.

## Optional tools

At larger scale, add local search (e.g. [qmd](https://github.com/tobi/qmd)) — not required initially.

## Boundaries

- Never modify `raw/` during ingest.
- Prefer updating existing wiki pages over creating duplicates.
- Leave the wiki more connected after every operation.
- Persist knowledge in `wiki/`, not only in conversation.