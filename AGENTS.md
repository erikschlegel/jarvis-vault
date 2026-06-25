# LLM Wiki Operating Schema

Personal knowledge base for Erik Schlegel, following [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Mission

Maintain a persistent, compounding wiki — not a RAG dump. Knowledge is compiled once, cross-linked, and kept current as new sources arrive.

- `raw/` is read-only source material.
- `wiki/` is the maintained knowledge layer.
- `wiki/index.md` is the content catalog.
- `wiki/log.md` is the append-only activity log.

The human curates sources, directs analysis, and asks questions. The agent writes and maintains the wiki.

## State and Obsidian

This repository **is** the Obsidian vault. All durable state is plain markdown on disk:

- `wiki/` — maintained knowledge (the agent's primary write surface)
- `raw/` — immutable sources (read-only for ingest)
- `wiki/index.md` and `wiki/log.md` — navigation and history

Obsidian is the human's read/browse UI over the same files. Git is the backup and version history. Do not store knowledge only in chat transcripts; persist it in `wiki/`.

When editing wiki pages, use markdown links compatible with Obsidian (`[label](path.md)`). Images belong in `raw/assets/`.

## Directory rules

### Raw sources

- `raw/sources/` stores immutable source documents.
- `raw/assets/` stores local images and attachments referenced by sources.
- Never modify files under `raw/` unless the user explicitly requests file hygiene.

### Wiki content

- `wiki/overview.md` — high-level map of active domains and themes.
- `wiki/synthesis.md` — evolving cross-domain synthesis (update when major themes shift).
- `wiki/sources/` — one summary page per ingested source.
- `wiki/entities/` — people, organizations, products, places, works.
- `wiki/concepts/` — topics, methods, theses, themes.
- `wiki/queries/` — durable answers and analyses worth keeping.
- `wiki/staging/` — drafts pending review before promotion into the active wiki.

## Writing rules

- Use markdown with relative links.
- Prefer concise, high-signal pages over long excerpts.
- Cross-link aggressively.
- Preserve uncertainty explicitly; flag contradictions between sources.
- Update existing pages instead of creating duplicates.
- Every new page must be linked from at least one other page and listed in `wiki/index.md`.
- Use lowercase kebab-case filenames.

Substantive pages should include:

- A short summary at the top.
- `## Key Points`
- `## Evidence / Notes` (with source citations as `[[source-name]]` or markdown links)
- `## Links`
- `## Open Questions` when unresolved

## Operations

### Ingest

When the user asks to ingest a source:

1. Read the source from `raw/sources/` and any assets it references.
2. Discuss key takeaways with the user if the source is ambiguous or high-stakes.
3. Create or update a summary in `wiki/sources/`.
4. Update relevant `wiki/entities/` and `wiki/concepts/` pages.
5. Update `wiki/overview.md` and `wiki/synthesis.md` when the source changes the big picture.
6. Update `wiki/index.md`.
7. Append an entry to `wiki/log.md`.

One source may touch many wiki pages. Prefer reconciling existing pages coherently over appending fragments.

### Query

When the user asks a question:

1. Read `wiki/index.md` first.
2. Open the most relevant wiki pages.
3. Synthesize an answer with inline citations to wiki page paths.
4. If the answer has durable value, save it under `wiki/queries/`.
5. Update `wiki/index.md` and append a `query` entry to `wiki/log.md` when a query artifact is created.

### Lint

When the user asks for a health check:

1. Find contradictions between pages.
2. Find stale claims superseded by newer sources.
3. Find orphan pages with no inbound links.
4. Find important terms mentioned repeatedly without dedicated pages.
5. Find missing cross-references.
6. Propose fixes or apply them with user approval.
7. Append a `lint` entry to `wiki/log.md`.

## Index format

Keep `wiki/index.md` compact. Organize by section: overview, sources, entities, concepts, queries.

Each entry: page link, one-line description, optional date or source count.

## Log format

Append-only entries:

```md
## [YYYY-MM-DD] operation | title

- Summary of what changed
- Pages touched: [page](relative/path.md)
```

Parseable prefix: `## [YYYY-MM-DD] ingest | Article Title`

## Quality bar

- Do not dump large source excerpts into the wiki.
- Do not restate the same idea across many pages without page-specific value.
- Leave the wiki more connected after every operation.
- Good explorations and comparisons belong in the wiki, not only in chat history.