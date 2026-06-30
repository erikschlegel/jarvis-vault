#!/usr/bin/env python3
"""Add videos[] frontmatter (page + stream URLs) to existing raw/x/ sources."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from wiki_connector_x.fetch_x_api import (
    API_BASE,
    EXPANSIONS,
    MEDIA_FIELDS,
    TWEET_FIELDS,
    load_tokens,
    refresh_access_token,
    require_env,
    tweet_to_record,
    users_index,
)
from wiki_connector_x.x_source_io import RAW_BOOKMARKS, RAW_LIKES, render_source_md
from wiki_connector_x.x_tweet_assets import media_index, process_tweet_assets, tweet_text

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta


def api_get_batch(
    access_token: str, ids: list[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    params = {
        "ids": ",".join(ids),
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "media.fields": MEDIA_FIELDS,
    }
    url = f"{API_BASE}/tweets?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    users = users_index(payload)
    media = media_index(payload)
    tweets: dict[str, dict[str, Any]] = {}
    for tweet in payload.get("data") or []:
        record = tweet_to_record(tweet, users)
        tweets[tweet["id"]] = {"raw": tweet, "record": record}
    return tweets, media


def source_type_from_path(path: Path) -> str:
    if path.parent == RAW_LIKES:
        return "x-like-api"
    return "x-bookmark-api"


def main() -> int:
    env = require_env()
    tokens = load_tokens()
    access_token = tokens["access_token"]

    candidates: list[Path] = []
    for folder in (RAW_LIKES, RAW_BOOKMARKS):
        for md in folder.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            if "Video" in text or "videos:" in text:
                candidates.append(md)

    if not candidates:
        print("No tweet sources with video references found.")
        return 0

    tweet_ids = []
    for md in candidates:
        meta = parse_frontmatter(md.read_text(encoding="utf-8"))
        tid = meta.get("tweet_id")
        if tid:
            tweet_ids.append(tid)

    print(f"Refreshing video metadata for {len(tweet_ids)} tweet(s)...")
    updated = 0
    for i in range(0, len(tweet_ids), 100):
        batch = tweet_ids[i : i + 100]
        try:
            tweets, media = api_get_batch(access_token, batch)
        except Exception:
            tokens = refresh_access_token(env, load_tokens())
            access_token = tokens["access_token"]
            tweets, media = api_get_batch(access_token, batch)

        for md in candidates:
            meta = parse_frontmatter(md.read_text(encoding="utf-8"))
            tid = meta.get("tweet_id")
            if tid not in batch or tid not in tweets:
                continue
            raw = tweets[tid]["raw"]
            record = tweets[tid]["record"]
            assets = process_tweet_assets(raw, media, dry_run=False)
            if not assets.get("videos"):
                continue
            body = render_source_md(
                source_type=source_type_from_path(md),
                tweet_id=tid,
                author=meta.get("author", record["author_name"]),
                author_handle=meta.get("author_handle", record["author_handle"]),
                tweet_url=meta.get("tweet_url", record["url"]),
                text=tweet_text(raw),
                liked_at=meta.get("liked_at") or None,
                bookmarked_at=meta.get("bookmarked_at") or None,
                saved_at=meta.get("imported_at", record.get("created_at", "")),
                metrics={
                    "likes": int(meta.get("metrics_likes") or 0),
                    "retweets": int(meta.get("metrics_retweets") or 0),
                    "replies": int(meta.get("metrics_replies") or 0),
                },
                assets=assets,
            )
            md.write_text(body, encoding="utf-8")
            updated += 1
            print(f"  updated {md.name}")

    print(f"Done. {updated} file(s) now have videos[].stream in frontmatter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
