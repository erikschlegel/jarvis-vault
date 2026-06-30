# wiki-connector-x

The X (Twitter) connector for the LLM Wiki. This plugin folder is also a Python package (`wiki_connector_x`), so its import and transcription scripts ship with the plugin. It is a pre-ingest pipeline that feeds [wiki-core](../wiki-core/) — it lands immutable source markdown in `raw/`, which `wiki-core` then folds into the wiki.

## What it provides

### Skills

The agent loads the matching skill automatically based on your request.

| Skill | Operation | What it does |
|-------|-----------|--------------|
| [x-import](skills/x-import/SKILL.md) | Pre-ingest | Clip X likes and bookmarks into `raw/` (API, account archive, bookmarks JSON, or Web Clipper folder) |
| [x-transcribe](skills/x-transcribe/SKILL.md) | Pre-ingest | Backfill local ASR transcripts for caption-less X videos so their spoken content is ingestible |

### Console entry points

Run any from the repo root with `uv run <entry-point>`.

| Entry point | Purpose |
|-------------|---------|
| `x-fetch` | OAuth login and fetch likes/bookmarks from the X API into `raw/` |
| `x-import` | Import from a fallback source — account archive, bookmarks JSON, or Obsidian Web Clipper folder |
| `x-refresh-streams` | Refresh expired video `stream` URLs in existing source frontmatter |
| `x-transcribe` | Run `faster-whisper` locally over caption-less videos and write transcript sidecars |

See `raw/x/README.md` in the Obsidian vault for the end-to-end fetch, fallback, and ingest walkthrough.

## Setup

Complete the [wiki-core setup](../wiki-core/README.md#setup) first — `uv sync`, `WIKI_VAULT`, and a seeded vault. This connector then lands X sources in that vault's `raw/x/`.

1. **Add X API credentials.** Create an app at [developer.x.com](https://developer.x.com/) and put its OAuth 2.0 keys in the repo's `.env` (gitignored):

   ```bash
   # in .env
   X_CLIENT_ID=...
   X_CLIENT_SECRET=...
   ```

2. **Fetch from the X API.** `x-fetch` runs the OAuth login (caching tokens under `.secrets/`, also gitignored) and pulls your likes and bookmarks into `raw/x/`:

   ```bash
   uv run x-fetch
   ```

   No API access? Use `x-import` instead to load from a fallback source — your account archive, a bookmarks JSON export, or an Obsidian Web Clipper folder:

   ```bash
   uv run x-import
   ```

3. **Backfill video transcripts (optional).** For caption-less videos, `x-transcribe` runs `faster-whisper` locally and writes transcript sidecars so the spoken content becomes ingestible:

   ```bash
   uv run x-transcribe
   ```

   If a previously fetched video's `stream` URL has expired, refresh it with `uv run x-refresh-streams`.

Once sources land in `raw/x/`, fold them into the wiki with the wiki-core [wiki-ingest](../wiki-core/skills/wiki-ingest/SKILL.md) skill.

## Configuration

Inherits the same environment variables as `wiki-core` (`WIKI_VAULT`, `WIKI_INDEX_DIR`, `WIKI_STATE`, `WIKI_CONFIG`). X API credentials live in `.env` and OAuth tokens in `.secrets/` (both gitignored) — see the fetch walkthrough for setup.

## Dependencies

Depends on [wiki-core](../wiki-core/) plus `faster-whisper` for local transcription — see [pyproject.toml](pyproject.toml).

See the repository [AGENTS.md](../../AGENTS.md) for the full wiki operating schema and the quality gate.
