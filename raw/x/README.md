# X (Twitter) raw sources

Immutable liked and bookmarked tweets — one markdown file per post. The agent reads these during **ingest**; do not edit after import.

## Layout

```text
raw/x/
  likes/            ← from X API or account export
  bookmarks/        ← from X API or xarchive JSON
  clips-imported/   ← Obsidian Web Clipper tweets
```

## Recommended: X API (OAuth 2.0)

### 1. Developer portal checklist

In [developer.x.com](https://developer.x.com) → app **eriks-knowledge-base**:

| Setting | Value |
|---------|--------|
| App permissions | **Read** |
| OAuth 2.0 | Enabled |
| Type of App | Web App (or Native for local dev) |
| Callback URI | `http://127.0.0.1:8765/callback` |
| Scopes | `tweet.read` `users.read` `like.read` `bookmark.read` `offline.access` |

Copy **Client ID** and **Client Secret** (OAuth 2.0 section — not the legacy API Key alone).

### 2. Local config

```bash
cd /Users/erikschlegel/Source/erik/erik-knowledge-base
cp .env.example .env
# Edit .env — paste Client ID and Secret. Do not commit .env.
```

### 3. One-time login (browser)

```bash
python3 scripts/fetch_x_api.py login
```

Approves access as `@erikschlegel1`. Tokens save to `.secrets/x_tokens.json` (gitignored).

### 4. Fetch into raw/

```bash
python3 scripts/fetch_x_api.py fetch --likes --bookmarks --months 12
```

Writes one `.md` file per tweet under `likes/` and `bookmarks/`.

**Note:** The API returns tweet post dates, not the exact time you liked or bookmarked. `--months` filters by when the tweet was posted (best available proxy). Increase `--max-pages` if you need deeper history.

### 5. Wiki ingest

Tell the agent: **"Ingest new sources from raw/x/"**

## Fallbacks

- **Likes archive:** `python3 scripts/import_x_sources.py --archive ~/Downloads/twitter-...`
- **Bookmarks JSON (xarchive):** `python3 scripts/import_x_sources.py --bookmarks-json ~/Downloads/bookmarks.json`
- **Obsidian clips:** `python3 scripts/import_x_sources.py --clips "…/AI Ideas /Tweets"`