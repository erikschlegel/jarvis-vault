#!/usr/bin/env python3
"""Deterministic authoring + roll-up helpers for the LLM Wiki Ingest/Query flow.

The agent no longer hand-writes source-page boilerplate, re-derives slugs, or
guesses anchor strings when rolling up ``index.md`` / ``log.md``. This script
owns the mechanical parts so the LLM spends its tokens on the substance — the
summary prose and the entity/concept link lists — not on plumbing.

Subcommands:
  scaffold     Write a source-page skeleton into the vault for one or more
               tweet ids (frontmatter, blockquote, Source line, section stubs).
               Idempotent: refuses to overwrite a page the agent already filled.
  log-append   Append a structured ``log.md`` entry (ingest/query/lint) in the
               AGENTS.md format — no anchor matching.
  index-add    Insert a deduped one-line catalog bullet under a named section in
               ``index.md`` — reused by both ingest roll-up and query filing.

Vault resolution: the destination vault is the routing domain's configured vault
(``WIKI_CONFIG``, default ``<index>/ingest_config.json``); override with
``--domain`` or ``--vault``.

Exit codes: 0 success, 1 failure, 2 configuration/argument error.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from wiki_core import ingest_plan, paths

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2

# Sentinel marking a page as a not-yet-filled scaffold. Its presence makes
# re-scaffolding safe; its absence means the agent has written real content and
# the page must not be clobbered.
SCAFFOLD_SENTINEL = (
    "<!-- SCAFFOLD: fill the Summary/Entities/Concepts sections, then delete this line -->"
)

# Placeholder headline shared by the frontmatter `title:` and the H1 so the agent
# replaces both in one edit. OKF lists `title` as a reserved queryable field.
TITLE_PLACEHOLDER = "TITLE — replace with a crafted, specific headline"

LINK_TARGET_RE = re.compile(r"\]\(([^)]+)\)")

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def today_iso() -> str:
    """Today's date as an ISO ``YYYY-MM-DD`` string."""
    return date.today().isoformat()


def first_enabled_domain(config: dict[str, Any]) -> str:
    """The first enabled routing domain, else the configured default."""
    for name, spec in config.get("domains", {}).items():
        if spec.get("enabled"):
            return str(name)
    return str(config.get("default_domain", "ai-swe"))


def resolve_vault(config: dict[str, Any], domain: str, vault_arg: Path | None) -> Path:
    """Resolve the destination vault: explicit ``--vault`` wins, else the domain's."""
    if vault_arg is not None:
        return vault_arg
    vault = ingest_plan.domain_vault(domain, config)
    if vault is None:
        raise ValueError(f"No vault configured for domain '{domain}'; pass --vault.")
    return vault


def plan_records(config: dict[str, Any], state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map tweet_id -> plan record across every bucket (all domains)."""
    plan = ingest_plan.compute_plan(config, state, domain_filter=None, all_domains=True)
    records: dict[str, dict[str, Any]] = {}
    for bucket in plan["buckets"].values():
        for record in bucket:
            records[record["tweet_id"]] = record
    return records


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #
def build_scaffold(record: dict[str, Any], raw_text: str, *, ingested_date: str) -> str:
    """Render a source-page skeleton for one raw source."""
    fm, body = ingest_plan.parse_frontmatter(raw_text)
    handle = ingest_plan.derive_handle(fm)
    tweet_id = record["tweet_id"]
    author = fm.get("author", "") or record.get("author", "")
    url = (
        fm.get("source_url")
        or fm.get("tweet_url")
        or fm.get("post_url")
        or fm.get("url")
        or f"https://x.com/{handle or 'i'}/status/{tweet_id}"
    )
    clean = ingest_plan.extract_tweet_text(body)
    has_video = bool(record.get("has_video"))
    has_transcript = bool(re.search(r"transcript:\s*\S", raw_text))

    fm_lines = [
        "---",
        "type: source",
        f'title: "{TITLE_PLACEHOLDER}"',
        f'tweet_id: "{tweet_id}"',
    ]
    if author:
        fm_lines.append(f"author: {author}")
    if handle:
        fm_lines.append(f"author_handle: {handle}")
    fm_lines += [
        f"domain: {record['domain']}",
        f"resource: {url}",
        f"raw: {record['file']}",
        f"timestamp: {ingested_date}",
        "tags: []",
        f"has_video: {str(has_video).lower()}",
        f"video_transcribed: {str(has_transcript).lower()}",
        "---",
    ]

    quote = clean if clean else "_(no text body — see video transcript)_"
    source_label = f"@{handle} on X" if handle else f"{author or 'source'} on X"

    parts = [
        "\n".join(fm_lines),
        "",
        f"# {TITLE_PLACEHOLDER}",
        "",
        f"> {quote}",
        "",
        f"**Source:** [{source_label}]({url})",
    ]
    if has_video and not has_transcript:
        parts += [
            "",
            "> [!warning] Video not yet transcribed — spoken content is not ingestible. "
            "Run the x-transcribe skill, then re-scaffold.",
        ]
    parts += [
        "",
        SCAFFOLD_SENTINEL,
        "",
        "## Summary",
        "",
        "_TODO: summarize the source; cross-link the entities and concepts it raises._",
        "",
        "## Entities",
        "",
        "_TODO: link each person, org, product, place, or work._",
        "",
        "## Concepts",
        "",
        "_TODO: link each topic, theme, or method._",
        "",
    ]
    return "\n".join(parts)


def scaffold_one(
    record: dict[str, Any],
    *,
    ingested_date: str,
    vault: Path,
    dry_run: bool,
    force: bool,
) -> tuple[str, Path]:
    """Write (or refuse to overwrite) the skeleton for one source.

    Returns ``(status, page_path)`` where status is one of ``written``,
    ``rewritten`` (over a prior scaffold), ``would-write`` (dry run), or
    ``skip-filled`` (page exists with real content and ``force`` is off).
    """
    page = vault / record["wiki_page"]
    raw_path = paths.raw_root().parent / record["file"]
    raw_text = raw_path.read_text(encoding="utf-8")
    content = build_scaffold(record, raw_text, ingested_date=ingested_date)

    is_rewrite = False
    if page.exists():
        existing = page.read_text(encoding="utf-8")
        if SCAFFOLD_SENTINEL not in existing and not force:
            return "skip-filled", page
        is_rewrite = True

    if dry_run:
        return "would-write", page

    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(content, encoding="utf-8")
    return ("rewritten" if is_rewrite else "written"), page


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Scaffold source-page skeletons for the given tweet ids."""
    config = ingest_plan.load_json(args.config)
    state = (
        ingest_plan.load_json(args.state) if args.state.exists() else {"version": 1, "sources": {}}
    )
    records = plan_records(config, state)
    ingested_date = args.date or today_iso()

    exit_code = EXIT_SUCCESS
    for tweet_id in args.tweet_ids:
        record = records.get(tweet_id)
        if record is None:
            logger.error("scaffold: no raw source found for %s", tweet_id)
            exit_code = EXIT_FAILURE
            continue
        try:
            vault = resolve_vault(config, record["domain"], args.vault)
        except ValueError as exc:
            logger.error("scaffold: %s", exc)
            exit_code = EXIT_FAILURE
            continue
        status, page = scaffold_one(
            record,
            ingested_date=ingested_date,
            vault=vault,
            dry_run=args.dry_run,
            force=args.force,
        )
        if status == "skip-filled":
            logger.warning(
                "scaffold: %s already filled (use --force to overwrite): %s", tweet_id, page
            )
            exit_code = EXIT_FAILURE
        else:
            logger.info("scaffold: %s -> %s (%s)", tweet_id, page, status)
    return exit_code


# --------------------------------------------------------------------------- #
# migrate-okf
# --------------------------------------------------------------------------- #
H1_RE = re.compile(r"^#\s+(.+?)\s*$")
# Frontmatter scalar key at the start of a line (block/list lines are left alone).
FM_KEY_RE = re.compile(r"^([A-Za-z0-9_]+):")


def _first_h1(text: str) -> str | None:
    """The text of the first ``# H1`` heading, if any."""
    for line in text.splitlines():
        match = H1_RE.match(line)
        if match:
            return match.group(1).strip()
    return None


def _split_frontmatter(text: str) -> tuple[list[str], list[str]] | None:
    """Split ``text`` into (frontmatter lines, body lines) including the fences.

    Returns ``None`` when the text has no leading ``---`` frontmatter block.
    The frontmatter list spans the opening fence through the closing fence; the
    body list is everything after.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[: i + 1], lines[i + 1 :]
    return None  # unterminated frontmatter — treat as none


def _fm_keys(fm_lines: list[str]) -> set[str]:
    """The set of top-level scalar keys present in a frontmatter line list."""
    keys: set[str] = set()
    for line in fm_lines[1:-1]:
        if line.startswith((" ", "\t")):
            continue
        match = FM_KEY_RE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def migrate_source_text(text: str) -> tuple[str, bool]:
    """Bring one source page's frontmatter to OKF reserved names. Idempotent.

    Renames ``source_url``→``resource`` and ``ingested``→``timestamp``, and
    inserts ``title`` (from the H1) and ``tags: []`` when absent. Returns
    ``(new_text, changed)``; ``changed`` is ``False`` for an already-migrated page.
    """
    split = _split_frontmatter(text)
    if split is None:
        return text, False
    fm_lines, body = split
    changed = False

    renamed: list[str] = []
    for line in fm_lines:
        if line.startswith("source_url:"):
            line = "resource:" + line[len("source_url:") :]
            changed = True
        elif line.startswith("ingested:"):
            line = "timestamp:" + line[len("ingested:") :]
            changed = True
        renamed.append(line)

    keys = _fm_keys(renamed)
    # Insert `title` directly after the `type:` line (or the opening fence).
    if "title" not in keys:
        title = _first_h1(text) or TITLE_PLACEHOLDER
        insert_at = 1
        for idx, line in enumerate(renamed):
            if line.startswith("type:"):
                insert_at = idx + 1
                break
        renamed.insert(insert_at, f'title: "{title}"')
        changed = True
    # Append `tags: []` just before the closing fence.
    if "tags" not in keys:
        renamed.insert(len(renamed) - 1, "tags: []")
        changed = True

    if not changed:
        return text, False
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(renamed + body) + trailing, True


def migrate_comparison_text(text: str) -> tuple[str, bool]:
    """Ensure a comparison page carries the OKF ``type``/``title``/``tags``. Idempotent.

    Pages lacking frontmatter get a fresh block (title derived from the H1);
    pages with frontmatter gain any missing ``type``/``title``/``tags`` keys.
    """
    title = _first_h1(text) or TITLE_PLACEHOLDER
    split = _split_frontmatter(text)
    if split is None:
        block = ["---", "type: comparison", f'title: "{title}"', "tags: []", "---", ""]
        trailing = "\n" if text.endswith("\n") else ""
        return "\n".join(block) + text.rstrip("\n") + trailing, True

    fm_lines, body = split
    keys = _fm_keys(fm_lines)
    inner = fm_lines[1:-1]
    changed = False
    if "type" not in keys:
        inner.insert(0, "type: comparison")
        changed = True
    if "title" not in keys:
        inner.insert(1 if "type" not in keys else 0, f'title: "{title}"')
        changed = True
    if "tags" not in keys:
        inner.append("tags: []")
        changed = True
    if not changed:
        return text, False
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(["---", *inner, "---", *body]) + trailing, True


def _migrate_dir(
    vault: Path, subdir: str, migrate: Callable[[str], tuple[str, bool]], *, dry_run: bool
) -> tuple[int, int]:
    """Apply ``migrate`` to every ``*.md`` under ``vault/subdir``.

    Returns ``(changed, total)``. Writes in place unless ``dry_run``.
    """
    directory = vault / subdir
    if not directory.is_dir():
        return 0, 0
    changed = 0
    pages = sorted(directory.glob("*.md"))
    for page in pages:
        original = page.read_text(encoding="utf-8")
        migrated, did_change = migrate(original)
        if did_change:
            changed += 1
            verb = "would migrate" if dry_run else "migrated"
            logger.info("migrate-okf: %s %s", verb, page)
            if not dry_run:
                page.write_text(migrated, encoding="utf-8")
    return changed, len(pages)


def cmd_migrate_okf(args: argparse.Namespace) -> int:
    """Migrate existing vault pages to the Open Knowledge Format frontmatter."""
    config = ingest_plan.load_json(args.config)
    domain = args.domain or first_enabled_domain(config)
    try:
        vault = resolve_vault(config, domain, args.vault)
    except ValueError as exc:
        logger.error("migrate-okf: %s", exc)
        return EXIT_FAILURE

    if not vault.is_dir():
        logger.error("migrate-okf: vault not found: %s", vault)
        return EXIT_FAILURE

    src_changed, src_total = _migrate_dir(
        vault, "sources", migrate_source_text, dry_run=args.dry_run
    )
    cmp_changed, cmp_total = _migrate_dir(
        vault, "comparisons", migrate_comparison_text, dry_run=args.dry_run
    )
    verb = "would update" if args.dry_run else "updated"
    logger.info(
        "migrate-okf: %s %d/%d source pages, %d/%d comparison pages in %s",
        verb,
        src_changed,
        src_total,
        cmp_changed,
        cmp_total,
        vault,
    )
    return EXIT_SUCCESS


# --------------------------------------------------------------------------- #
# log-append
# --------------------------------------------------------------------------- #
def build_log_entry(
    op: str, title: str, date_str: str, bullets: list[str], pages_touched: str | None
) -> str:
    """Render an AGENTS.md-format log block."""
    lines = [f"## [{date_str}] {op} | {title}", ""]
    lines += [f"- {b}" for b in bullets]
    if pages_touched:
        lines.append(f"- Pages touched: {pages_touched}")
    return "\n".join(lines) + "\n"


def append_log(vault: Path, entry: str, *, dry_run: bool) -> Path:
    """Append a log block to ``log.md``, normalising spacing."""
    log = vault / "log.md"
    text = log.read_text(encoding="utf-8") if log.exists() else "# Log\n"
    new_text = text.rstrip("\n") + "\n\n" + entry
    if not dry_run:
        log.write_text(new_text, encoding="utf-8")
    return log


def cmd_log_append(args: argparse.Namespace) -> int:
    """Append a structured ingest/query/lint entry to ``log.md``."""
    config = ingest_plan.load_json(args.config)
    domain = args.domain or first_enabled_domain(config)
    try:
        vault = resolve_vault(config, domain, args.vault)
    except ValueError as exc:
        logger.error("log-append: %s", exc)
        return EXIT_FAILURE

    entry = build_log_entry(
        args.op, args.title, args.date or today_iso(), args.bullet or [], args.pages_touched
    )
    log = append_log(vault, entry, dry_run=args.dry_run)
    verb = "would append" if args.dry_run else "appended"
    logger.info("log-append: %s entry to %s", verb, log)
    if args.dry_run:
        print(entry, end="")
    return EXIT_SUCCESS


# --------------------------------------------------------------------------- #
# index-add
# --------------------------------------------------------------------------- #
def link_target(entry: str) -> str | None:
    """The ``(path)`` target of the first markdown link in ``entry``, if any."""
    match = LINK_TARGET_RE.search(entry)
    return match.group(1) if match else None


def insert_index_entry(text: str, section: str, entry: str) -> tuple[str, str]:
    """Insert ``- {entry}`` under ``section``; dedupe on the link target.

    Returns ``(new_text, status)`` where status is ``inserted`` or ``duplicate``.
    Raises ``ValueError`` when the section heading is not found.
    """
    lines = text.splitlines()
    head_idx: int | None = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and line.lstrip("#").strip() == section:
            head_idx = i
            break
    if head_idx is None:
        raise ValueError(f"section heading not found: '{section}'")

    end = len(lines)
    for j in range(head_idx + 1, len(lines)):
        if lines[j].startswith("#"):
            end = j
            break

    bullet = f"- {entry}"
    target = link_target(entry)
    last_bullet: int | None = None
    for k in range(head_idx + 1, end):
        stripped = lines[k].lstrip()
        if stripped == bullet.lstrip():
            return text, "duplicate"
        if target and f"({target})" in lines[k]:
            return text, "duplicate"
        if stripped.startswith("- "):
            last_bullet = k

    if last_bullet is not None:
        insert_at = last_bullet + 1
    else:
        insert_at = head_idx + 1
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1

    lines.insert(insert_at, bullet)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + trailing, "inserted"


def cmd_index_add(args: argparse.Namespace) -> int:
    """Insert a deduped catalog bullet under a named ``index.md`` section."""
    config = ingest_plan.load_json(args.config)
    domain = args.domain or first_enabled_domain(config)
    try:
        vault = resolve_vault(config, domain, args.vault)
    except ValueError as exc:
        logger.error("index-add: %s", exc)
        return EXIT_FAILURE

    index = vault / "index.md"
    if not index.exists():
        logger.error("index-add: %s not found", index)
        return EXIT_FAILURE

    text = index.read_text(encoding="utf-8")
    try:
        new_text, status = insert_index_entry(text, args.section, args.entry)
    except ValueError as exc:
        logger.error("index-add: %s", exc)
        return EXIT_FAILURE

    if status == "duplicate":
        logger.info("index-add: entry already present under '%s' (no change)", args.section)
        return EXIT_SUCCESS

    if args.dry_run:
        logger.info("index-add: would insert under '%s' in %s", args.section, index)
        print(f"- {args.entry}")
        return EXIT_SUCCESS

    index.write_text(new_text, encoding="utf-8")
    logger.info("index-add: inserted under '%s' in %s", args.section, index)
    return EXIT_SUCCESS


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=paths.config_path())
    parser.add_argument("--state", type=Path, default=paths.state_path())
    parser.add_argument("--vault", type=Path, help="Override the destination vault path.")
    parser.add_argument("--domain", help="Routing domain whose vault to target (log/index).")
    parser.add_argument("--dry-run", action="store_true", help="Show the change without writing.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scaffold = sub.add_parser("scaffold", help="Write source-page skeletons.")
    p_scaffold.add_argument("tweet_ids", nargs="+", metavar="TWEET_ID")
    p_scaffold.add_argument("--date", help="ingested date (default: today).")
    p_scaffold.add_argument(
        "--force", action="store_true", help="Overwrite a page even if already filled."
    )
    p_scaffold.set_defaults(func=cmd_scaffold)

    p_migrate = sub.add_parser(
        "migrate-okf",
        help="Rewrite existing source/comparison pages to OKF frontmatter (idempotent).",
    )
    p_migrate.set_defaults(func=cmd_migrate_okf)

    p_log = sub.add_parser("log-append", help="Append a structured log.md entry.")
    p_log.add_argument("--op", required=True, choices=["ingest", "query", "lint"])
    p_log.add_argument("--title", required=True)
    p_log.add_argument("--date", help="Entry date (default: today).")
    p_log.add_argument("--bullet", action="append", help="A body bullet (repeatable).")
    p_log.add_argument("--pages-touched", help="Final 'Pages touched:' bullet text.")
    p_log.set_defaults(func=cmd_log_append)

    p_index = sub.add_parser("index-add", help="Insert a deduped index.md bullet.")
    p_index.add_argument("--section", required=True, help="Heading text to insert under.")
    p_index.add_argument("--entry", required=True, help="Bullet content (without leading '- ').")
    p_index.set_defaults(func=cmd_index_add)

    return parser


def configure_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def main() -> int:
    """Main entry point."""
    args = create_parser().parse_args()
    configure_logging(args.verbose)
    try:
        result = args.func(args)
        return int(result)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
