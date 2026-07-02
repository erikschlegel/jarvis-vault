"""The X (Twitter) source adapter for the LLM Wiki engine.

Registers under the ``wiki_core.source_adapters`` entry-point group so the core
planner and scaffolder dispatch X-specific identity, body cleaning, resource
resolution, and video-transcription notices without importing this connector.
All the Twitter-shaped parsing that used to live in ``wiki_core.ingest_plan``
now lives here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wiki_core import paths
from wiki_core.source_adapter import SourceAdapter

STATUS_ID_RE = re.compile(r"/status/(\d+)")
HANDLE_RE = re.compile(r"x\.com/([^/]+)")
BOILERPLATE_PREFIXES = (
    "# ",
    "**Author:",
    "**Tweet:",
    "**Source:",
    "**Original",
    "**Saved:",
    "**Posted:",
    "**Likes:",
    "**Retweets:",
    "**Replies:",
)


class XAdapter(SourceAdapter):
    """Adapter for X/Twitter raw sources under ``raw/x/``."""

    source_type = "x"
    owned_subdirs = ("x",)

    def owns(self, path: Path, fm: dict[str, str]) -> bool:
        """Claim files in ``raw/x/`` and any tweet identifiable by frontmatter.

        Beyond the ``raw/x/`` subtree, a file is X-owned when it carries a
        ``tweet_id`` field or exposes a ``/status/<id>`` URL, so hand-placed
        exports are still routed here rather than to the default adapter.
        """
        try:
            rel = path.relative_to(paths.raw_root())
        except ValueError:
            rel = None
        if rel is not None and rel.parts and rel.parts[0] in self.owned_subdirs:
            return True
        if fm.get("tweet_id"):
            return True
        return any(STATUS_ID_RE.search(fm.get(key, "")) for key in ("tweet_url", "post_url", "url"))

    def source_id(self, fm: dict[str, str], path: Path) -> str:
        """Resolve a stable status ID across the like/bookmark and clips schemas.

        Prefers the explicit ``tweet_id`` field, then a ``/status/<id>`` segment
        in any URL field (clips use ``post_url``), then leading digits in the
        filename, then the stem.
        """
        if fm.get("tweet_id"):
            return fm["tweet_id"]
        for key in ("tweet_url", "post_url", "url"):
            match = STATUS_ID_RE.search(fm.get(key, ""))
            if match:
                return match.group(1)
        leading = re.match(r"(\d{6,})", path.name)
        return leading.group(1) if leading else path.stem

    def author_handle(self, fm: dict[str, str]) -> str:
        """Resolve the author handle across schemas (``author_handle`` or URL)."""
        if fm.get("author_handle"):
            return fm["author_handle"]
        for key in ("author_url", "tweet_url", "post_url"):
            match = HANDLE_RE.search(fm.get(key, ""))
            if match:
                return match.group(1)
        return ""

    def clean_body(self, fm: dict[str, str], body: str) -> str:
        """Strip render boilerplate to recover the substantive tweet/post text.

        Drops the rendered ``# Tweet by`` heading, ``**Author:**``/``**Tweet:**``
        metadata lines, ``---`` rules, the ``## Attachments`` trailer, and inline
        URLs so the result is the human-authored content used for slugs and
        hashes.
        """
        lines: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "---":
                continue
            if stripped.startswith("## Attachments"):
                break
            if stripped.startswith(BOILERPLATE_PREFIXES):
                continue
            lines.append(stripped)
        text = " ".join(lines)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"pic\.twitter\.com/\S+", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def resource_url(self, fm: dict[str, str], source_id: str) -> str:
        """Canonical tweet URL, falling back to a synthesized status link."""
        handle = self.author_handle(fm)
        return (
            fm.get("source_url")
            or fm.get("tweet_url")
            or fm.get("post_url")
            or fm.get("url")
            or f"https://x.com/{handle or 'i'}/status/{source_id}"
        )

    def source_label(self, fm: dict[str, str]) -> str:
        """Human-readable attribution, e.g. ``@handle on X``."""
        handle = self.author_handle(fm)
        if handle:
            return f"@{handle} on X"
        author = fm.get("author") or "source"
        return f"{author} on X"

    def asset_flags(self, fm: dict[str, str], raw_text: str) -> dict[str, bool]:
        """Detect attached video and whether a transcript is already present."""
        return {
            "has_video": "videos:" in raw_text,
            "video_transcribed": bool(re.search(r"transcript:\s*\S", raw_text)),
        }

    def scaffold_frontmatter(
        self, record: dict[str, Any], fm: dict[str, str], raw_text: str
    ) -> list[str]:
        """Add X-specific author and media frontmatter to the source page."""
        flags = self.asset_flags(fm, raw_text)
        handle = self.author_handle(fm)
        author = fm.get("author", "") or str(record.get("author", ""))
        lines: list[str] = []
        if author:
            lines.append(f"author: {author}")
        if handle:
            lines.append(f"author_handle: {handle}")
        lines.append(f"has_video: {str(flags['has_video']).lower()}")
        lines.append(f"video_transcribed: {str(flags['video_transcribed']).lower()}")
        return lines

    def scaffold_notices(
        self, record: dict[str, Any], fm: dict[str, str], raw_text: str
    ) -> list[str]:
        """Warn when a video is attached but not yet transcribed."""
        flags = self.asset_flags(fm, raw_text)
        if flags["has_video"] and not flags["video_transcribed"]:
            return [
                "> [!warning] Video not yet transcribed — spoken content is not ingestible. "
                "Run the x-transcribe skill, then re-scaffold.",
            ]
        return []
