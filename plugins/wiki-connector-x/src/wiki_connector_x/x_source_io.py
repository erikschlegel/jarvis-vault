"""Shared helpers for writing X tweets into raw/ markdown sources."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wiki_core import paths

REPO_ROOT = Path(__file__).resolve().parents[4]


def _raw_x() -> Path:
    return paths.raw_root() / "x"


# Convenience aliases — evaluated lazily so importing this module without
# WIKI_VAULT set (e.g. during pytest collection) does not raise SystemExit.
def raw_x() -> Path:
    return _raw_x()


def raw_likes() -> Path:
    return _raw_x() / "likes"


def raw_bookmarks() -> Path:
    return _raw_x() / "bookmarks"


# Legacy module-level names for code that already references them directly.
# These are resolved on first access via module __getattr__ so they are
# safe to have in a module that is imported during test collection.
RAW_X: Path  # assigned in __getattr__
RAW_LIKES: Path
RAW_BOOKMARKS: Path


def __getattr__(name: str) -> Path:
    if name == "RAW_X":
        return _raw_x()
    if name == "RAW_LIKES":
        return _raw_x() / "likes"
    if name == "RAW_BOOKMARKS":
        return _raw_x() / "bookmarks"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len] or "tweet").strip("-")


def tweet_filename(tweet_id: str, author: str, preview: str) -> str:
    author_slug = slugify(author or "unknown", 24)
    preview_slug = slugify(preview, 40)
    return f"{tweet_id}-{author_slug}-{preview_slug}.md"


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
    assets: dict[str, Any] | None = None,
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
    assets = assets or {}
    lines.extend(
        [
            f"imported_at: {saved_at}",
            f"metrics_likes: {metrics.get('likes', 0)}",
            f"metrics_retweets: {metrics.get('retweets', 0)}",
            f"metrics_replies: {metrics.get('replies', 0)}",
        ]
    )
    videos = assets.get("videos") or []
    if videos:
        lines.append("videos:")
        for video in videos:
            if video.get("page"):
                lines.append(f'  - page: "{video["page"]}"')
            elif video.get("stream"):
                lines.append("  -")
            if video.get("stream"):
                lines.append(f'    stream: "{video["stream"]}"')
            if video.get("transcript"):
                lines.append(f'    transcript: "{video["transcript"]}"')
    lines.extend(
        [
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
            text.strip() or "_No tweet text returned by API._",
            "",
        ]
    )
    media = assets.get("media") or []
    articles = assets.get("articles") or []
    if media or videos or articles:
        lines.extend(["## Attachments", ""])
        for path in media:
            lines.append(f"- Image: `{path}`")
        for video in videos:
            stream = video.get("stream") or ""
            page = video.get("page") or ""
            if stream:
                lines.append(f"- Video stream: {stream}")
            if page and page != stream:
                lines.append(f"- Video page: {page}")
            if video.get("transcript"):
                lines.append(f"- Video transcript: `{video['transcript']}`")
        for path in articles:
            lines.append(f"- Article: `{path}`")
        lines.append("")
    return "\n".join(lines)


def write_if_missing(path: Path, content: str, dry_run: bool) -> bool:
    if path.exists():
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True
