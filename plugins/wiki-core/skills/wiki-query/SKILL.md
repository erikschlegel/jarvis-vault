---
name: wiki-query
description: "Answer questions against the jarvis-vault LLM Wiki using the jarvis-vault MCP retrieval tools. USE WHEN: the user asks a question that the wiki may answer, asks to compare or synthesize across sources, or asks what the vault says about a topic, person, concept, or claim. Covers routing across get_index / search_wiki / expand_neighbors / read_page, citation discipline, and filing durable answers back into the vault."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-06-27"
---

# Wiki Query Skill

## Overview

This skill runs the **Query** operation defined in [AGENTS.md](../../../../AGENTS.md) against the LLM Wiki. The wiki is an interlinked markdown knowledge base living in an Obsidian vault outside the workspace (its location resolves from `WIKI_VAULT`). It is plain files: you can always read and write any page with native file tools at the vault path (Tier 0). The `jarvis-vault` MCP server (Tier 2) is a retrieval *accelerator* over those same files — prefer it for **search** (finding which pages answer a question), but reading a page you already know the path of, or writing a page back, works directly through file tools. See the AGENTS.md "Access tiers" section.

The retrieval engine is hybrid: BM25 keyword search and on-device dense embeddings, fused with reciprocal-rank fusion, over heading-level chunks of every page. Trust it over recall: the index reflects the vault's current state, your memory of prior sessions does not.

## Tools

The `jarvis-vault` MCP server exposes five tools:

- `get_pulse()` — returns `pulse.md`, the recent-context cache: a short rolling prose summary of recent activity and the current working context. Tier 0 routing: read this **first**, before `get_index()`, so the session resumes without a recap. Returns a placeholder when the vault has no pulse yet.
- `get_index()` — returns `index.md`, the curated content catalog. Read this second for broad or structural questions ("what does the vault cover?", "which sources discuss X?").
- `search_wiki(query, k)` — hybrid search returning the top-k page sections, each with `page` (vault-relative path), `heading`, `snippet`, and `score`. Tier 1/2 routing: the default for specific factual or conceptual questions.
- `expand_neighbors(path, depth)` — 1st-degree wikilink neighbors of a page. Use to pull in connected context after a hit lands on a relevant page.
- `read_page(path)` — full markdown of one page. Use to read a result in full before quoting or synthesizing.

If the `jarvis-vault` server is not configured in this client, fall back to Tier 0: read `pulse.md` and `index.md` directly with file tools at the `WIKI_VAULT` path, open pages by their catalog paths, and use `uv run wiki-search` (Tier 1) for keyword/dense search. The tools above degrade gracefully — an unset `WIKI_VAULT` or unbuilt index returns a guidance message (run `uv run wiki-init`) rather than failing the session.

## Routing

0. **Always start with `get_pulse()`** to load recent context and the current working thread, then route the actual question below.
1. **Structural / "what's in here" questions** → `get_index()` first, then `read_page` on the catalog entries that match.
2. **Specific factual or conceptual questions** → `search_wiki(query, k=8)`. Rephrase into a focused query; the engine handles both exact terms and paraphrase.
3. **Landed on a relevant page but need surrounding context** → `expand_neighbors(path)` to find linked entities, concepts, and sources, then `read_page` the promising ones.
4. **Before quoting or asserting** → `read_page` the source section in full. Snippets are previews, not ground truth.

Issue multiple `search_wiki` calls with different phrasings when the first pass is thin. Stop searching once you have enough pages to answer confidently — do not over-retrieve.

## Citation discipline

- Cite the wiki `page` paths you drew from, using their vault-relative paths (for example, `sources/...md`, `entities/anthropic.md`, `concepts/agentic-coding.md`).
- Distinguish what the wiki states from your own synthesis. Attribute claims to their source pages.
- Surface contradictions explicitly when sources disagree, naming both pages.
- Never invent a page path. If `search_wiki` returns nothing relevant, say the vault does not cover it rather than guessing.

## Filing durable answers

Per the AGENTS.md Query operation, valuable analysis must not die in chat. When you produce a durable artifact — a comparison, a cross-source synthesis, or a non-trivial answer worth keeping — file it back into the vault:

1. Write a new page under the appropriate category, usually `wiki/comparisons/` (lowercase kebab-case filename, relative markdown links, aggressive cross-linking). Give it OKF frontmatter — `type: comparison`, a crafted `title`, and an optional `tags` list.
2. Catalog the new page in `wiki/index.md` with `uv run wiki-pages index-add --section "<heading>" --entry "[Title](comparisons/<slug>.md) — one-line summary."` — it inserts the bullet under the named section and dedupes on the link target, so no anchor matching and re-runs are no-ops.
3. Append a `query` entry to `wiki/log.md` with `uv run wiki-pages log-append --op query --title "<title>" --bullet "..." --pages-touched "comparisons/<slug>.md"` — it renders the AGENTS.md log format for you.
4. After writing vault files, rebuild the index so future searches see the new page: `uv run wiki-search build --incremental`.
5. Refresh `wiki/pulse.md` — rewrite the `## Working context` blurb and prepend the new artifact to `## Recently updated`, trimming back to ~500 words. This is the project's "save" step: it keeps the next session's `get_pulse()` aware of what you just filed.

Writing vault files happens through the workspace tools against the vault path the same way the existing ingest workflow writes pages — confirm the destination with the user when the artifact is substantial. Skip filing for quick lookups that produce no lasting artifact.

## Index freshness

The index is derived and rebuildable. If results seem stale or a page you expect is missing, rebuild:

- `uv run wiki-search build --incremental` — re-embeds only changed pages (content-hash gated).
- `uv run wiki-search build` — full rebuild.

The index lives under `<vault>/.wiki_index/` (override with `WIKI_INDEX_DIR`) and is outside the repo. A first build (or an embedding-model change) re-embeds every page; subsequent incremental builds touch only what changed.
