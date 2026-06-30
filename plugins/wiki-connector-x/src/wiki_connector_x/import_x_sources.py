#!/usr/bin/env python3
"""Import X (Twitter) likes and bookmarks into raw/ source markdown files.

Karpathy raw sources are immutable inputs for later wiki ingest.

Supported inputs:
  1. X account data export (GDPR archive) — provides likes via data/like.js (or like-part*.js)
  2. xarchive Chrome extension JSON export — provides bookmarks with full text
  3. Obsidian Web Clipper-style markdown folder — copies/normalizes existing clips

Usage:
  uv run x-import --archive ~/Downloads/twitter-2026-06-24-abc123
  uv run x-import --bookmarks-json ~/Downloads/bookmarks.json
  uv run x-import --clips "~/path/to/AI Ideas /Tweets"
  uv run x-import --archive PATH --bookmarks-json PATH --months 12

Exit codes: 0 success, 1 failure, 2 bad args
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wiki_core import paths

RAW_X = paths.raw_root() / "x"
RAW_LIKES = RAW_X / "likes"
RAW_BOOKMARKS = RAW_X / "bookmarks"

JS_ASSIGNMENT = re.compile(r"^\s*window\.YTD\.\w+\.part\d*\s*=\s*", re.MULTILINE)


def parse_js_export(path: Path) -> list[dict[str, Any]]:
    """Parse X archive .js files (window.YTD.* = [...])."""
    text = path.read_text(encoding="utf-8", errors="replace")
    text = JS_ASSIGNMENT.sub("", text).strip()
    if text.endswith(";"):
        text = text[:-1]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {path}")
    return data


def find_archive_like_files(archive_dir: Path) -> list[Path]:
    """Locate like.js / like-partN.js under an X data export."""
    candidates: list[Path] = []
    for pattern in ("**/like.js", "**/like-part*.js", "**/like/part*.js"):
        candidates.extend(archive_dir.glob(pattern))
    return sorted({p.resolve() for p in candidates})


def parse_archive_likes(archive_dir: Path) -> list[dict[str, Any]]:
    """Extract like records from an X account data export."""
    records: list[dict[str, Any]] = []
    files = find_archive_like_files(archive_dir)
    if not files:
        return records
    for file_path in files:
        for item in parse_js_export(file_path):
            like = item.get("like") or item
            if isinstance(like, dict):
                records.append(like)
    return records


def parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def within_months(dt: datetime | None, months: int) -> bool:
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    cutoff = datetime.now(UTC) - timedelta(days=months * 30)
    return dt >= cutoff


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len] or "tweet").strip("-")


def tweet_filename(tweet_id: str, author: str, preview: str) -> str:
    author_slug = slugify(author or "unknown", 24)
    preview_slug = slugify(preview, 40)
    return f"{tweet_id}-{author_slug}-{preview_slug}.md"


def render_source_md(
    *,
    source_type: str,
    tweet_id: str,
    author: str,
    author_handle: str,
    tweet_url: str,
    text: str,
    liked_at: str | None,
    bookmarked_at: str | None,
    saved_at: str,
    folder: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> str:
    metrics = metrics or {}
    lines = [
        "---",
        f"source_type: {source_type}",
        f'tweet_id: "{tweet_id}"',
        f'author: "{author}"',
        f'author_handle: "{author_handle}"',
        f'tweet_url: "{tweet_url}"',
    ]
    if liked_at:
        lines.append(f"liked_at: {liked_at}")
    if bookmarked_at:
        lines.append(f"bookmarked_at: {bookmarked_at}")
    if folder:
        lines.append(f'bookmark_folder: "{folder}"')
    lines.extend(
        [
            f"imported_at: {saved_at}",
            f"metrics_likes: {metrics.get('likes', 0)}",
            f"metrics_retweets: {metrics.get('retweets', 0)}",
            "---",
            "",
            f"# Tweet by {author}",
            "",
            f"**Author:** [{author}](https://x.com/{author_handle})",
            f"**Tweet:** [View on X]({tweet_url})",
            f"**Source:** {source_type}",
            "",
            "---",
            "",
            text.strip()
            or "_Tweet text not included in export; ID preserved for later enrichment._",
            "",
        ]
    )
    return "\n".join(lines)


def write_if_missing(path: Path, content: str, dry_run: bool) -> bool:
    if path.exists():
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def import_archive_likes(archive_dir: Path, months: int, dry_run: bool) -> tuple[int, int]:
    created = skipped = 0
    now = datetime.now(UTC).isoformat()
    for like in parse_archive_likes(archive_dir):
        tweet_id = str(like.get("tweetId") or like.get("id") or "")
        if not tweet_id:
            continue
        liked_at_str = like.get("createdAt") or like.get("likedAt")
        liked_dt = parse_iso_date(liked_at_str)
        if not within_months(liked_dt, months):
            continue

        text = like.get("fullText") or like.get("text") or ""
        author = like.get("authorName") or like.get("name") or "unknown"
        handle = (like.get("authorScreenName") or like.get("screenName") or "i").lstrip("@")
        url = like.get("expandedUrl") or f"https://x.com/{handle}/status/{tweet_id}"
        preview = text[:80] if text else tweet_id
        out = RAW_LIKES / tweet_filename(tweet_id, author, preview)
        body = render_source_md(
            source_type="x-like-archive",
            tweet_id=tweet_id,
            author=author,
            author_handle=handle,
            tweet_url=url,
            text=text,
            liked_at=liked_at_str,
            bookmarked_at=None,
            saved_at=now,
        )
        if write_if_missing(out, body, dry_run):
            created += 1
        else:
            skipped += 1
    return created, skipped


def import_xarchive_bookmarks(json_path: Path, months: int, dry_run: bool) -> tuple[int, int]:
    """Import bookmarks from sytelus/xarchive JSON export."""
    created = skipped = 0
    now = datetime.now(UTC).isoformat()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    items = (
        payload
        if isinstance(payload, list)
        else payload.get("bookmarks") or payload.get("tweets") or []
    )
    for item in items:
        tweet_id = str(item.get("id") or item.get("tweetId") or item.get("rest_id") or "")
        if not tweet_id:
            continue
        created_at = item.get("created_at") or item.get("bookmarked_at") or item.get("saved_at")
        if not within_months(parse_iso_date(created_at), months):
            continue

        user = item.get("user") or item.get("author") or {}
        author = user.get("name") or item.get("authorName") or "unknown"
        handle = (user.get("screen_name") or item.get("authorScreenName") or "i").lstrip("@")
        text = item.get("full_text") or item.get("text") or item.get("fullText") or ""
        url = item.get("url") or f"https://x.com/{handle}/status/{tweet_id}"
        folder = item.get("folder") or item.get("bookmark_folder")
        metrics = {
            "likes": item.get("favorite_count") or item.get("likes") or 0,
            "retweets": item.get("retweet_count") or item.get("retweets") or 0,
        }
        preview = text[:80] if text else tweet_id
        out = RAW_BOOKMARKS / tweet_filename(tweet_id, author, preview)
        body = render_source_md(
            source_type="x-bookmark-xarchive",
            tweet_id=tweet_id,
            author=author,
            author_handle=handle,
            tweet_url=url,
            text=text,
            liked_at=None,
            bookmarked_at=created_at,
            saved_at=now,
            folder=folder,
            metrics=metrics,
        )
        if write_if_missing(out, body, dry_run):
            created += 1
        else:
            skipped += 1
    return created, skipped


def import_clip_folder(clips_dir: Path, dest: Path, dry_run: bool) -> tuple[int, int]:
    """Normalize Obsidian Web Clipper tweets into raw/x/clips-imported/."""
    created = skipped = 0
    if not clips_dir.exists():
        return 0, 0
    for src in sorted(clips_dir.glob("*.md")):
        dest_path = dest / src.name
        if dest_path.exists():
            skipped += 1
            continue
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_path)
        created += 1
    return created, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import X likes/bookmarks into raw/ sources.")
    parser.add_argument("--archive", type=Path, help="Path to extracted X account data export")
    parser.add_argument("--bookmarks-json", type=Path, help="Path to xarchive bookmarks JSON")
    parser.add_argument(
        "--clips",
        type=Path,
        help="Folder of existing Obsidian-clipped tweet markdown files",
    )
    parser.add_argument(
        "--months", type=int, default=12, help="Only import items from last N months"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report counts without writing files"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not any([args.archive, args.bookmarks_json, args.clips]):
        print(
            "Provide at least one input: --archive, --bookmarks-json, or --clips",
            file=sys.stderr,
        )
        return 2

    totals_created = totals_skipped = 0

    if args.archive:
        if not args.archive.exists():
            print(f"Archive not found: {args.archive}", file=sys.stderr)
            return 1
        c, s = import_archive_likes(args.archive, args.months, args.dry_run)
        print(f"Likes from archive: {c} created, {s} skipped (already present or filtered)")
        totals_created += c
        totals_skipped += s

    if args.bookmarks_json:
        if not args.bookmarks_json.exists():
            print(f"Bookmarks JSON not found: {args.bookmarks_json}", file=sys.stderr)
            return 1
        c, s = import_xarchive_bookmarks(args.bookmarks_json, args.months, args.dry_run)
        print(f"Bookmarks from JSON: {c} created, {s} skipped")
        totals_created += c
        totals_skipped += s

    if args.clips:
        dest = RAW_X / "clips-imported"
        c, s = import_clip_folder(args.clips, dest, args.dry_run)
        print(f"Clips copied: {c} created, {s} skipped")
        totals_created += c
        totals_skipped += s

    action = "Would write" if args.dry_run else "Wrote"
    print(f"\n{action} {totals_created} raw source file(s) under {RAW_X}")
    if totals_created:
        print("Next: ask your agent to ingest new sources from raw/x/ into wiki/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
