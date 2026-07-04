---
name: wiki-ingest
description: "Process an immutable raw/ source into the jarvis-vault LLM Wiki — the Ingest operation. USE WHEN: the user drops a new source into raw/ and asks to ingest, process, fold in, or summarize it; asks to update the wiki from a source; or asks to compile pending sources into the vault. Covers the ingest worklist, the source→sources/→entities/→concepts/→overview/synthesis/index/log write order, and rebuilding the search index."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-07-01"
---

# Wiki Ingest Skill

## Overview

This skill runs the **Ingest** operation defined in [AGENTS.md](../../../../AGENTS.md) against the LLM Wiki. Ingest takes one immutable source from `raw/` and integrates it into the interlinked markdown wiki — it does not merely index the source for later retrieval. A single source typically touches 10–15 wiki pages.

The wiki lives in an Obsidian vault outside the workspace (its location resolves from `WIKI_VAULT`). Source files live in the workspace under `raw/`; wiki pages are written to the vault. Karpathy's rule holds: process **one source at a time, with the user involved**. Never modify `raw/` during ingest — sources are immutable inputs.

Ingest is source-type agnostic. Content reaches `raw/` two ways: connector plugins land their own content under a dedicated subtree (the X connector writes `raw/x/`), and connector-less content — a local file, a web URL, or a piped text block (a chat attachment or pasted note) — comes in through the generic on-ramp `uv run wiki-add` (`<path-or-url>`, or `--stdin`/`--text` for content with no readable path), which writes a `raw/inbox/` file with uniform `source_type`/`source_id` frontmatter. The engine dispatches each raw file to the matching source adapter (the generic `DefaultAdapter` handles `raw/inbox/` `doc`/`web` content; the X connector's adapter handles `raw/x/`), so the write protocol below is identical regardless of where a source came from.

When you are running as a GUI or desktop client (for example, the GitHub Copilot desktop app) and the `jarvis-vault` server is available, prefer its MCP read tools (`get_pulse`, `search_wiki`, `read_page`) for the orientation and lookup steps — checking the pulse and finding existing entity or concept pages to update — rather than shelling out; page writes, index/log helpers, and manifest updates still go through the Tier 1 CLI and file tools.

## When to ingest

- The user added a file under `raw/` — X clips under `raw/x/{bookmarks,likes,clips-imported}/*.md`, or a generic file or web clip under `raw/inbox/*.md` (typically landed with `uv run wiki-add`) — and wants it folded into the wiki.
- The user names a local path or a URL, or attaches a file or pastes a text block in chat, for you to land and fold in (see [Landing the source](#landing-the-source)).
- The user asks what is pending ingest, or to compile the backlog into the vault.
- A source already ingested changed upstream and needs a refresh.

## Landing the source

Before computing the worklist, make sure the source actually exists under `raw/`. Classify the ingest argument:

- **An existing source** — a `source_id`, or a file already under `raw/` (an X clip, or a prior `raw/inbox/` drop). Nothing to land; go straight to the worklist.
- **A local file path or an `http(s)://` URL** — land it with `uv run wiki-add <path-or-url>`. This writes one `raw/inbox/` file with the uniform `source_type`/`source_id` frontmatter.
- **An attached file or a pasted/typed text block** — this arrives as *content*, not a readable path (a chat attachment or paste has no stable path, and an out-of-workspace temp path may be unreadable). Pipe the in-context body to `uv run wiki-add --stdin --title "<crafted headline>"`. Supply a specific `--title`; ask the user for one only when the body yields no sensible headline.

`wiki-add` prints the landed `source_id`, and the next `uv run wiki-plan` lists it as `new`. Landing happens **before** the write protocol begins — never interleave it with vault writes, and never edit `raw/` afterward (it stays immutable during ingest).

## Worklist

Compute the delta before writing anything. The worklist engine classifies every raw source into a routing domain, hashes its body, and compares against the manifest and the vault:

```bash
uv run wiki-plan            # human summary + worklist
uv run wiki-plan --json      # machine-readable worklist
uv run wiki-plan --domain ai-swe   # restrict to one domain
```

It is read-only by default and buckets every source into `new` / `pending` / `changed` / `missing` / `parked` / `noise` / `up_to_date`. The worklist is `new + pending + changed + missing` — enabled-domain sources that still need work; `parked`, `noise`, and `up_to_date` are excluded. Pass `--update-manifest` to persist the proposed domain classifications and content hashes.

After a source's vault page is written, finalize it in the manifest with the engine — never hand-edit the ingest manifest (`${WIKI_VAULT}/.wiki_index/ingest_state.json`):

```bash
uv run wiki-plan --mark-ingested <source_id> [<source_id> ...]
```

`--mark-ingested` flips each given source to status `ingested`, re-hashes its raw body, and records its `wiki_page`. It verifies the destination vault page exists first and refuses (non-zero exit, leaving the entry untouched) any id whose page is missing, so the manifest never claims an un-written page; pass `--allow-missing-page` only to override deliberately. Accept several ids at once to finalize a whole batch in one call.

Ingest one source at a time by default; to clear a backlog of thin, related sources, use the bounded **Batch mode** below. Never batch silently.

## Scope

The `/ingest` command routes here by scope:

- **Named source** (`/ingest <id>`) — ingest that one source solo.
- **No argument** (`/ingest`) — read the worklist. If exactly one source is pending, ingest it. If several are pending, group them into batchable clusters (thin, related sources sharing entities/concepts) and present that plan before folding any in — do not silently drain the queue.
- **All** (`/ingest all`) — drain the pending worklist through repeated **Batch mode** passes: one bounded cluster (~8 thin, related sources) at a time, each with its own go-ahead, index rebuild, and multi-id finalize. Heavy or contradiction-bearing sources still come out of the batch and ingest solo. `all` is "work the whole backlog in bounded batches," not a single monster call.

Batching amortizes the fixed overhead of a pass — context reload, one index rebuild, one multi-id `--mark-ingested` finalize — across a cluster. It does **not** shortcut per-source summarization: every source still gets a real `sources/` page and real entity/concept updates.

## Write protocol

Per the AGENTS.md Ingest operation, write in this order so cross-links resolve and the big picture stays current:

1. **Read** the source and any `raw/assets/` it references (images, transcripts). Discuss key takeaways with the user when useful.
2. **Source summary** — `uv run wiki-pages scaffold <source_id>` writes `wiki/sources/<slug>.md` with OKF frontmatter, a blockquote of the cleaned body, the `**Source:**` line, and `## Summary` / `## Entities` / `## Concepts` stubs marked by a scaffold sentinel. Then replace the placeholder `title` and the `_TODO:_` stubs with real content — craft a specific headline, summarize the source, and link the entities and concepts it raises. Scaffold is idempotent: it refuses to overwrite a filled page (sentinel gone) unless you pass `--force`. (One-off: `uv run wiki-pages migrate-okf` brings pre-OKF pages up to the current frontmatter.)
3. **Entities** — create or update `wiki/entities/*` pages for each person, org, product, place, or work the source covers. Carry OKF frontmatter (`type: entity`, `title`, `name`, optional `entity_kind`, `domain`, and an optional `tags` list). Add the new source as a citation; note contradictions explicitly.
4. **Concepts** — create or update `wiki/concepts/*` pages for the topics, themes, and methods involved. Carry OKF frontmatter (`type: concept`, `title`, `name`, `domain`, and an optional `tags` list). Cross-link aggressively.
5. **Overview / synthesis** — update `wiki/overview.md` and `wiki/synthesis.md` only when the source shifts the high-level map or the evolving thesis.
6. **Index** — add the new source page (and any new entity/concept pages) to `wiki/index.md` with `uv run wiki-pages index-add --section "<heading>" --entry "[Title](sources/<slug>.md) — one-line summary."`. It inserts the bullet under the named section, dedupes on the link target (re-running is a no-op), and never hand-matches anchors. Repeat per new page.
7. **Log** — append an `ingest` entry to `wiki/log.md` with `uv run wiki-pages log-append --op ingest --title "<title>" --bullet "..." --pages-touched "<page>, <page>"`. It renders the AGENTS.md format and spacing for you.
8. **Pulse** — refresh `wiki/pulse.md`: rewrite the `## Working context` blurb to reflect what was just folded in, prepend the ingested source to `## Recently updated`, and trim the page back to ~500 words. The pulse is agent-maintained prose (like `overview.md`), not a deterministic CLI output; the MCP server serves it as `get_pulse()` so the next query reads it first.
9. **Finalize** — `uv run wiki-plan --mark-ingested <source_id>` after the page exists (see Worklist).

Integrate into the existing wiki — prefer updating an existing page over creating a near-duplicate. Leave the wiki more connected than you found it.

## Batch mode

Batch mode trades the per-source approval gate for speed while keeping full integration depth. It relaxes *when the user is consulted* — never *how thoroughly each source is folded in*. Every source in a batch still gets a real `sources/` page and real entity/concept updates; batching is not indexing.

Use it only when all of these hold:

- The candidates are **thin** — short tweets or clips whose claims fit in a few lines, not long articles or transcripts.
- They share a **theme or entities/concepts**, so their cross-links land on overlapping pages.
- The set is **bounded** — roughly one thematic cluster or up to ~8 thin sources per batch. Split larger backlogs into multiple batches.

Keep these out of batches and ingest them solo: substantial sources (long-form articles, video transcripts), and any source that contradicts or materially revises an existing page — contradiction handling needs focused attention.

Batch sequence:

1. **Plan once.** Group the chosen worklist sources into one cluster, list them to the user with their shared entity/concept targets, and get a single go-ahead — not one approval per source.
2. **Order by shared page.** Sort so sources touching the same entity/concept page are written consecutively, and edit those shared pages serially (read-modify-write) so concurrent updates never clobber each other.
3. **Integrate each source** through the full write protocol steps 1–4 (scaffold + fill source summary → entities → concepts). Cross-link across siblings in the same batch, not just into the existing vault.
4. **Roll up once at the end.** Apply overview/synthesis (step 5), `index-add` per new page (step 6), a single `log-append --op ingest` entry covering the whole batch (step 7), and a single `pulse.md` refresh (step 8) after every source is written — not per source.
5. **Finalize once.** Mark the whole batch ingested in a single call: `uv run wiki-plan --mark-ingested <id1> <id2> ...`.
6. **Rebuild the index once** after the batch, not per source.
7. **Review once.** Present a consolidated summary of every source page and every touched entity/concept so the user can sanity-check the whole batch in one pass.

If a source turns out thicker than expected mid-batch — it raises a contradiction or needs its own deep treatment — pull it out and ingest it solo.

## Index rebuild

The hybrid search index is derived and rebuildable. After writing vault pages, rebuild so the new content is searchable:

```bash
uv run wiki-search build --incremental   # re-embeds only changed pages
```

## Boundaries

- `raw/` is immutable. Read it; never edit it during ingest.
- Write vault pages through the workspace tools against the vault path, the same way the existing ingest workflow does. Confirm the destination with the user for substantial pages.
- One source at a time by default; **Batch mode** above is the only sanctioned way to process several at once, and only for bounded clusters of thin, related sources. Substantial or contradiction-bearing sources stay solo. Never silently bulk-ingest the whole worklist — always plan the batch with the user first.
- Hand-offs: video sources missing transcripts should go through the **x-transcribe** skill first so their spoken content is ingestible; raw X clipping is the **x-import** skill. Question answering against the finished wiki is **wiki-query**; health checks are **wiki-lint**.
