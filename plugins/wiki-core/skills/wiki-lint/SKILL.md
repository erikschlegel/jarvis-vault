---
name: wiki-lint
description: "Run a health check over the erik-knowledge-base LLM Wiki — the Lint operation. USE WHEN: the user asks for a wiki health check, lint, audit, or cleanup; asks to find broken links, orphan pages, contradictions, stale claims, or missing pages; or asks what is wrong with or missing from the vault. Covers the deterministic verify_wiki.py checks plus the semantic checks, fix-with-approval, and logging."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-06-28"
---

# Wiki Lint Skill

## Overview

This skill runs the **Lint** operation defined in [AGENTS.md](../../../../AGENTS.md) against the LLM Wiki. Lint is a health check: it surfaces structural defects and knowledge defects, suggests new questions and sources to investigate, and applies fixes only with user approval. The goal is to leave the wiki more correct and more connected than you found it.

The wiki lives in an Obsidian vault outside the workspace (its location resolves from `WIKI_VAULT`). The deterministic checker runs against that vault path; the semantic checks are yours to perform by reading pages.

## Two layers of checks

### Deterministic (run the linter)

Start with the read-only structural linter. It walks the vault, parses inline markdown links and frontmatter, and reports the defects below:

```bash
uv run wiki-verify
```

It reports:

- **Broken relative links** — a `[text](target)` whose target does not resolve on disk.
- **Broken anchor links** — a `[text](page.md#heading)` whose `#heading` fragment has no matching heading in the target page.
- **Frontmatter schema violations** — a `sources/`, `entities/`, or `concepts/` page whose `type` is wrong or that is missing a required key (e.g. an entity missing `entity_kind`).
- **Orphan pages** — a wiki page with no inbound link from any other wiki page.
- **Manifest drift** — an ingested source whose `wiki_page` is missing from the vault.
- **Unfinalized source pages** — a `sources/` page on disk whose manifest status is not `ingested` (e.g. written but never finalized with `--mark-ingested`).

Links inside fenced code blocks are template examples and are intentionally skipped. The linter exits non-zero when it finds broken links, broken anchors, frontmatter violations, or manifest drift; orphans and unfinalized pages are advisory.

### Semantic (read and reason)

The linter handles structure; it cannot judge meaning. Per the AGENTS.md Lint operation, also look for:

- **Contradictions** between pages — name both pages and the conflicting claims.
- **Stale claims** a newer source has superseded — flag the page and the superseding source.
- **Missing concept pages** — a topic mentioned across sources but lacking its own page.
- **Missing cross-references** — pages that should link to each other but do not (the linter flags broken links, not absent ones).
- **Stale pulse** — `pulse.md` whose `## Recently updated` no longer matches the last few `wiki/log.md` entries, or that has grown well past ~500 words. The pulse is a recent-context cache, not an archive; flag it for a refresh.
- **Data gaps** that a web search could fill — surface them as suggested follow-ups.

To find redundant or overlapping pages worth consolidating, run the near-duplicate detector. It reuses the search index embeddings and reports page pairs above a cosine-similarity threshold — a heuristic shortlist for the contradiction and consolidation review, not a verdict:

```bash
uv run wiki-search duplicates --threshold 0.93
```

High-scoring pairs are often two sources covering the same talk, or an entity page that has drifted into restating its source. Lower the threshold to widen the net; treat every pair as a candidate to read, not an automatic merge.

Use the `erik-wiki` MCP retrieval tools (see the **wiki-query** skill) to sample the vault efficiently when hunting for contradictions and gaps, rather than reading every page blind.

## Applying fixes

1. Present findings grouped by type, ordered structural-first (broken links and drift are unambiguous) then semantic.
2. Apply fixes only with user approval. Structural fixes (repair a link, add an inbound link to an orphan, reconcile manifest drift) are usually safe; semantic fixes (resolving a contradiction, rewriting a stale claim) need a judgment call from the user.
3. Write changes to vault pages through the workspace tools against the vault path. Never touch `raw/` — sources are immutable.
4. After editing pages, rebuild the search index so it reflects the fixes:

   ```bash
   uv run wiki-search build --incremental
   ```

5. If the pulse is stale, refresh `wiki/pulse.md` — rewrite `## Working context` and reconcile `## Recently updated` against the latest `log.md` entries, trimming to ~500 words.
6. Append a `lint` entry to `wiki/log.md` using the AGENTS.md log format, listing what was checked and what was fixed.

## Boundaries

- `raw/` is immutable. Lint operates on `wiki/` only.
- Do not auto-apply semantic rewrites; confirm with the user.
- Hand-offs: filling a discovered gap with a new source is the **wiki-ingest** skill; answering a question the lint surfaced is **wiki-query**.
