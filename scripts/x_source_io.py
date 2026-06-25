"""Shared helpers for writing X tweets into raw/ markdown sources."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_X = REPO_ROOT / "raw" / "x"
RAW_LIKES = RAW_X / "likes"
RAW_BOOKMARKS = RAW_X / "bookmarks"


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
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
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
    metrics: dict | None = None,
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
            f"metrics_replies: {metrics.get('replies', 0)}",
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
    return "\n".join(lines)


def write_if_missing(path: Path, content: str, dry_run: bool) -> bool:
    if path.exists():
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True