# X (Twitter) raw sources

Immutable liked and bookmarked tweets, one markdown file per post. The agent reads these during **ingest**; do not edit after import.

## Layout

```text
raw/x/
  likes/       ← from X account data export (like.js)
  bookmarks/   ← from xarchive JSON export
  clips-imported/  ← normalized Obsidian Web Clipper tweets
```

## How to populate

### Likes (last 12 months)

1. X → **Settings → Your account → Download an archive of your data**
2. Request archive; wait for email (often 24–48 hours)
3. Download and unzip
4. Run:

```bash
python3 scripts/import_x_sources.py \
  --archive ~/Downloads/twitter-YYYY-MM-DD-xxxxx \
  --months 12
```

Note: `like.js` often contains tweet IDs only. Full text may require a paid X API lookup or manual clip for sparse entries.

### Bookmarks

X's official archive **does not include bookmarks**. Use the [xarchive](https://github.com/sytelus/xarchive) Chrome extension:

1. Load extension, browse x.com while logged in
2. Export bookmarks to JSON
3. Run:

```bash
python3 scripts/import_x_sources.py \
  --bookmarks-json ~/Downloads/bookmarks.json \
  --months 12
```

### Existing Obsidian clips

```bash
python3 scripts/import_x_sources.py \
  --clips "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/AI Ideas /Tweets"
```

## After import

Tell the agent: **"Ingest new sources from raw/x/"** — it will compile wiki pages per `AGENTS.md`.