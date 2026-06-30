---
name: x-import
description: "Import X (Twitter) likes and bookmarks into raw/ as immutable source markdown for the erik-knowledge-base LLM Wiki — the pre-ingest pipeline. USE WHEN: the user wants to clip, import, fetch, or sync X likes or bookmarks into the vault; points at an X data archive, a bookmarks JSON export, or a folder of Web Clipper markdown; or asks to pull tweets in for ingest. Covers the four import paths, the videos[] frontmatter contract, and hand-off to wiki-ingest."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-06-28"
---

# X Import Skill

## Overview

This skill populates `raw/x/` with immutable source markdown clipped from X (Twitter). These files are the raw inputs the **wiki-ingest** skill later folds into the wiki — this skill only writes to `raw/`, never to the vault. Per [AGENTS.md](../../../../AGENTS.md), raw sources are immutable once written.

Output lands under `raw/x/likes/` and `raw/x/bookmarks/` (and `raw/x/clips-imported/` for normalized Web Clipper clips). Tweet assets — images, videos, linked articles, transcripts — go under `raw/assets/`.

## Import paths

There are four ways in. Pick the one matching what the user has.

### 1. X API (live fetch)

Authenticated pull straight from the X API. Requires one-time OAuth setup (`.env` with `X_CLIENT_ID` / `X_CLIENT_SECRET`, callback URL, read scopes — see the script docstring). Never commit `.env` or `.secrets/`.

```bash
uv run x-fetch login                       # one-time OAuth
uv run x-fetch fetch --likes --bookmarks --months 12
```

`fetch` downloads images, videos, linked articles, and video transcripts alongside the source markdown.

### 2. X account data export (GDPR archive)

Provides likes via `data/like.js` (or `like-part*.js`) from the official account export:

```bash
uv run x-import --archive ~/Downloads/twitter-2026-06-24-abc123
```

### 3. Bookmarks JSON export

From the `xarchive` Chrome extension, which carries full bookmark text:

```bash
uv run x-import --bookmarks-json ~/Downloads/bookmarks.json
```

### 4. Web Clipper markdown folder

Normalizes and copies existing Obsidian Web Clipper-style clips:

```bash
uv run x-import --clips "~/path/to/AI Ideas /Tweets"
```

Paths can be combined, and `--months N` restricts to recent items:

```bash
uv run x-import --archive PATH --bookmarks-json PATH --months 12
```

## Video frontmatter contract

Per AGENTS.md, X videos are **not stored locally**. A source's frontmatter may carry a `videos:` block instead:

```yaml
videos:
  - page: "https://x.com/handle/status/123/video/1"
    stream: "https://video.twimg.com/amplify_video/.../file.mp4"
    transcript: "raw/assets/x/123/video-1-transcript.txt"
```

- `stream` — direct MP4 URL for downstream agents to fetch or analyze without a browser.
- `page` — human-readable X player URL.
- `transcript` — local caption text when X supplied auto-generated subtitles.

To backfill `videos[]` frontmatter (`page` + `stream`) onto existing sources that lack it:

```bash
uv run x-refresh-streams
```

Do not download MP4s into the repo unless the user explicitly asks. Prefer `videos[].stream` over scraping the X page.

## Boundaries

- This skill writes only to `raw/` and `raw/assets/`. It never writes to the wiki.
- Once a source markdown file exists in `raw/`, treat it as immutable.
- Secrets stay out of git: never commit `.env` or `.secrets/`.
- Hand-offs: caption-less videos get local transcripts via the **x-transcribe** skill; folding imported sources into the wiki is the **wiki-ingest** skill.
