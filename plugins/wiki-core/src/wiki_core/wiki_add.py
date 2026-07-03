"""Land connector-less content into ``raw/inbox/`` for ingest.

This is the generic on-ramp for content that has no dedicated connector. It
writes a single ``raw/inbox/<slug>-<date>.md`` file carrying the uniform identity
frontmatter (``source_type`` + ``source_id``) plus ``resource``/``title`` so the
engine's ``DefaultAdapter`` (which owns ``raw/inbox/``) can plan and scaffold it
exactly like any other source. It never touches the wiki vault directly.

Three input shapes are supported:
  * an ``http(s)://`` URL             -> ``source_type: web`` (page is fetched)
  * an existing local file path       -> ``source_type: doc`` (file is read)
  * literal content (``--stdin`` /     -> ``source_type: doc`` (body is the source;
    ``--text``) with no path/URL          identity is a content hash)

The content shapes exist because a chat attachment or a pasted/typed note arrives
as text, not as a readable path — the ingest skill pipes that body straight in.

The fetch is intentionally dependency-free (``urllib`` + a crude tag strip);
callers wanting rich extraction can pre-convert to text/markdown and pass the
file path or piped body instead.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import NamedTuple

from wiki_core import ingest_plan, paths

logger = logging.getLogger("wiki_add")

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_H1_RE = re.compile(r"^\s*#\s+(.*\S)\s*$", re.MULTILINE)
_MAX_DERIVED_TITLE = 120
_USER_AGENT = "jarvis-vault/wiki-add (+https://github.com/)"


class LandedSource(NamedTuple):
    """The result of landing a source into the inbox: its path and stable identity."""

    path: Path
    source_id: str


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


def derive_title(body: str) -> str:
    """A headline for a bare content body: first markdown H1, else first text line.

    Used when landing piped/pasted content (``--stdin``/``--text``) without an
    explicit ``--title``. Returns an empty string only when the body has no
    non-blank line; callers substitute a fallback in that case.
    """
    match = _H1_RE.search(body)
    if match:
        return match.group(1).strip()[:_MAX_DERIVED_TITLE]
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:_MAX_DERIVED_TITLE]
    return ""


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch ``url`` and return ``(title, body_text)``.

    Raises ``urllib.error.URLError`` on a network/HTTP failure so the caller can
    report a clean message and exit non-zero. Rejects any non-``http(s)`` scheme
    (e.g. ``file:``) before opening so a crafted argument cannot reach the local
    filesystem or an unexpected protocol handler.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Refusing to fetch non-http(s) URL scheme: {scheme or '(none)'}")
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
    """Render the ``raw/inbox`` markdown carrying uniform identity frontmatter.

    Free-text values (``source_id``, ``resource``, ``title``) are emitted as
    JSON-encoded scalars — a valid subset of YAML double-quoted scalars — so a
    URL containing ``#`` or a title containing a quote or backslash cannot break
    the frontmatter block.
    """
    fm = [
        "---",
        f"source_type: {source_type}",
        f"source_id: {json.dumps(source_id)}",
        f"resource: {json.dumps(resource)}",
        f"title: {json.dumps(title)}",
        f"imported_at: {imported_at}",
        "---",
    ]
    return "\n".join(fm) + "\n\n" + body.strip() + "\n"


def _land(
    *,
    source_type: str,
    resource: str,
    title: str,
    body: str,
    imported_at: str,
    inbox: Path,
    stem: str,
) -> LandedSource:
    """Compute identity, render, and write one inbox file; return path + source_id."""
    sid = source_id_for(source_type=source_type, resource=resource, body=body, stem=stem)
    slug = ingest_plan.slugify(title, 50) or "source"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / f"{slug}-{imported_at}-{sid[:6]}.md"
    dest.write_text(
        render_inbox_md(
            source_type=source_type,
            source_id=sid,
            resource=resource,
            title=title,
            imported_at=imported_at,
            body=body,
        ),
        encoding="utf-8",
    )
    return LandedSource(path=dest, source_id=sid)


def add_source(
    source: str,
    *,
    title: str | None,
    imported_at: str,
    inbox: Path,
) -> LandedSource:
    """Fetch/read a path or URL and write it into ``inbox``; return path + source_id."""
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

    return _land(
        source_type=source_type,
        resource=resource,
        title=effective_title,
        body=body,
        imported_at=imported_at,
        inbox=inbox,
        stem=Path(source).stem,
    )


def add_text(
    body: str,
    *,
    title: str | None,
    imported_at: str,
    inbox: Path,
) -> LandedSource:
    """Land a literal content body (chat attachment / pasted note) into ``inbox``.

    Unlike ``add_source`` there is no path or URL — the body *is* the source. The
    identity is a content hash, the ``source_type`` is ``doc``, and ``resource``
    is left empty (the scaffolder falls back to the raw file path for the vault
    page). The title is the given ``title``, else one derived from the body.
    """
    if not body.strip():
        raise ValueError("refusing to land empty content")
    effective_title = title or derive_title(body) or "untitled note"
    return _land(
        source_type="doc",
        resource="",
        title=effective_title,
        body=body,
        imported_at=imported_at,
        inbox=inbox,
        stem="",
    )


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="A local file path or an http(s):// URL. Omit when using --stdin/--text.",
    )
    parser.add_argument(
        "--text",
        help="Land this literal text as a source (for content with no path, e.g. a pasted note).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the source body from stdin (for piped content with no path).",
    )
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
    # Exactly one input shape: a positional path/URL, --text, or --stdin.
    shapes_given = sum([args.source is not None, args.text is not None, bool(args.stdin)])
    if shapes_given != 1:
        logger.error("wiki-add: provide exactly one of a path/URL, --text, or --stdin")
        return EXIT_FAILURE

    inbox = args.inbox or paths.inbox_root()
    imported_at = args.date or today_iso()
    try:
        if args.stdin:
            result = add_text(
                sys.stdin.read(), title=args.title, imported_at=imported_at, inbox=inbox
            )
        elif args.text is not None:
            result = add_text(args.text, title=args.title, imported_at=imported_at, inbox=inbox)
        else:
            result = add_source(args.source, title=args.title, imported_at=imported_at, inbox=inbox)
    except (FileNotFoundError, urllib.error.URLError, ValueError, OSError) as exc:
        logger.error("wiki-add: %s", exc)
        return EXIT_FAILURE
    logger.info("wiki-add: wrote %s (source_id %s)", result.path, result.source_id)
    return EXIT_SUCCESS


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
