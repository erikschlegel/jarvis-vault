"""Land a connector-less local file or web URL into ``raw/inbox/`` for ingest.

This is the generic on-ramp for content that has no dedicated connector: a
local markdown/text file, or a web page fetched over HTTP. It writes a single
``raw/inbox/<slug>-<date>.md`` file carrying the uniform identity frontmatter
(``source_type`` + ``source_id``) plus ``resource``/``title`` so the engine's
``DefaultAdapter`` (which owns ``raw/inbox/``) can plan and scaffold it exactly
like any other source. It never touches the wiki vault directly.

Two source kinds are auto-detected from the argument:
  * an ``http(s)://`` URL           -> ``source_type: web`` (page is fetched)
  * anything else (an existing path) -> ``source_type: doc``

The fetch is intentionally dependency-free (``urllib`` + a crude tag strip);
callers wanting rich extraction can pre-convert to text/markdown and pass the
file path instead.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from wiki_core import ingest_plan, paths

logger = logging.getLogger("wiki_add")

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_USER_AGENT = "jarvis-vault/wiki-add (+https://github.com/)"


def today_iso() -> str:
    """Today's date as ``YYYY-MM-DD`` (kept tiny for test monkeypatching)."""
    return date.today().isoformat()


def is_url(source: str) -> bool:
    """True when ``source`` looks like an HTTP(S) URL rather than a local path."""
    return source.startswith(("http://", "https://"))


def _strip_html(raw: str) -> str:
    """Reduce an HTML document to readable text (best-effort, no dependencies)."""
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", without_blocks)
    text = html.unescape(text)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def _extract_title(raw: str) -> str:
    """The ``<title>`` text of an HTML document, or an empty string."""
    match = _TITLE_RE.search(raw)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch ``url`` and return ``(title, body_text)``.

    Raises ``urllib.error.URLError`` on a network/HTTP failure so the caller can
    report a clean message and exit non-zero.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read().decode(charset, errors="replace")
    return _extract_title(raw), _strip_html(raw)


def source_id_for(*, source_type: str, resource: str, body: str, stem: str) -> str:
    """Deterministic identity value for an inbox source.

    Web sources hash their canonical URL (stable across re-fetches); document
    sources hash their content when available, else fall back to the file stem.
    The 16-char hex prefix keeps filenames and frontmatter compact while staying
    collision-safe for a personal-scale corpus.
    """
    if source_type == "web" and resource:
        digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()
        return digest[:16]
    if body.strip():
        return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:16]
    return stem or hashlib.sha256(resource.encode("utf-8")).hexdigest()[:16]


def render_inbox_md(
    *,
    source_type: str,
    source_id: str,
    resource: str,
    title: str,
    imported_at: str,
    body: str,
) -> str:
    """Render the ``raw/inbox`` markdown carrying uniform identity frontmatter."""
    fm = [
        "---",
        f"source_type: {source_type}",
        f'source_id: "{source_id}"',
        f"resource: {resource}",
        f'title: "{title}"',
        f"imported_at: {imported_at}",
        "---",
    ]
    return "\n".join(fm) + "\n\n" + body.strip() + "\n"


def add_source(
    source: str,
    *,
    title: str | None,
    imported_at: str,
    inbox: Path,
) -> Path:
    """Fetch/read ``source`` and write it into ``inbox``; return the new path."""
    if is_url(source):
        source_type = "web"
        resource = source
        fetched_title, body = fetch_url(source)
        effective_title = title or fetched_title or source
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"no such file: {path}")
        source_type = "doc"
        resource = path.resolve().as_uri()
        body = path.read_text(encoding="utf-8")
        effective_title = title or path.stem

    sid = source_id_for(
        source_type=source_type,
        resource=resource,
        body=body,
        stem=Path(source).stem,
    )
    slug = ingest_plan.slugify(effective_title, 50) or "source"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / f"{slug}-{imported_at}-{sid[:6]}.md"
    dest.write_text(
        render_inbox_md(
            source_type=source_type,
            source_id=sid,
            resource=resource,
            title=effective_title,
            imported_at=imported_at,
            body=body,
        ),
        encoding="utf-8",
    )
    return dest


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", help="A local file path or an http(s):// URL.")
    parser.add_argument("--title", help="Override the derived title.")
    parser.add_argument("--date", help="imported_at date (default: today).")
    parser.add_argument(
        "--inbox",
        type=Path,
        default=None,
        help="Override the destination inbox directory (default: raw/inbox).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the ``wiki-add`` console script."""
    args = create_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    inbox = args.inbox or paths.inbox_root()
    imported_at = args.date or today_iso()
    try:
        dest = add_source(
            args.source,
            title=args.title,
            imported_at=imported_at,
            inbox=inbox,
        )
    except (FileNotFoundError, urllib.error.URLError, OSError) as exc:
        logger.error("wiki-add: %s", exc)
        return EXIT_FAILURE
    logger.info("wiki-add: wrote %s", dest)
    return EXIT_SUCCESS


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
