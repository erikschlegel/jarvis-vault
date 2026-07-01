#!/usr/bin/env python3
"""Compute the incremental ingest worklist for the LLM Wiki.

Enumerates the immutable raw sources, classifies each into a routing domain,
hashes its body, and compares against the ingest manifest and the destination
vault to emit a delta worklist (new / changed / missing / parked / noise /
up-to-date). Only sources in enabled domains land in the worklist the agent
compiles into the wiki.

Source-type specifics (identity derivation, body cleaning, asset flags) live in
``SourceAdapter`` implementations discovered through the ``wiki_core.source_adapters``
entry-point group; this planner stays connector-agnostic and dispatches per file.

Read-only by default. Pass --update-manifest to persist proposed domain
classifications and content hashes for not-yet-finalized sources (status
"pending" for enabled domains, "parked" for disabled). It never changes an
"ingested" or "noise" entry unless the raw body hash changed.

Usage:
  python3 scripts/ingest_plan.py                       # human summary + worklist
  python3 scripts/ingest_plan.py --json                # machine-readable worklist
  python3 scripts/ingest_plan.py --out .worklist.json  # write worklist to file
  python3 scripts/ingest_plan.py --domain ai-swe       # restrict to one domain
  python3 scripts/ingest_plan.py --all-domains         # include disabled domains
  python3 scripts/ingest_plan.py --update-manifest      # persist classifications
  python3 scripts/ingest_plan.py --mark-ingested ID...  # finalize ingested sources
  python3 scripts/ingest_plan.py --mark-noise ID...     # permanently skip sources

Exit codes: 0 success, 1 failure, 2 configuration/argument error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, cast

from wiki_core import paths, source_adapter

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2

# These paths anchor on the vault (WIKI_VAULT), so they are resolved lazily at
# call time rather than import time: raw_root() intentionally raises SystemExit
# with setup guidance when WIKI_VAULT is unset, and evaluating that at module
# import would break simply importing the module (e.g. during test collection).

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a source markdown file into (frontmatter dict, body).

    Only scalar ``key: value`` pairs are parsed; nested blocks (e.g. ``videos:``)
    are ignored for routing purposes. Quotes around values are stripped.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_fm, body = match.group(1), match.group(2)
    fm: dict[str, str] = {}
    for line in raw_fm.splitlines():
        if not line or line[0] in " \t-":  # skip nested/list lines
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            fm[key] = value
    return fm, body


def slugify(text: str, max_len: int = 60) -> str:
    """Lowercase, hyphen-separated slug matching the importer's convention."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len] or "tweet").strip("-")


def source_hash(body: str) -> str:
    """Stable SHA-256 of the source body (whitespace-normalised tail)."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def wiki_source_slug(source_id: str, author: str, body: str) -> str:
    """Derive the wiki source page filename for a source.

    Readable-first scheme ``<author-slug>-<preview-slug>-<id6>.md``: the human
    author/topic leads so Obsidian's file explorer and graph nodes sort and read
    by content, with the last 6 characters of the source id appended as a
    deterministic, collision-proof disambiguator. The full source id stays in the
    page's frontmatter and the manifest, so nothing is lost.
    """
    preview = re.sub(r"\s+", " ", body.strip())[:80]
    id6 = source_id[-6:] if source_id else "source"
    return f"{slugify(author, 24)}-{slugify(preview, 40)}-{id6}.md"


# --------------------------------------------------------------------------- #
# Config / state IO
# --------------------------------------------------------------------------- #
def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, raising a clear error on failure."""
    try:
        return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise FileNotFoundError(f"Required file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON with stable, human-diffable formatting."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify_domain(
    fm: dict[str, str],
    body: str,
    config: dict[str, Any],
    adapter: source_adapter.SourceAdapter,
) -> str:
    """Pick the best-matching domain for a source via keyword/author scoring.

    Returns the configured ``unclassified`` bucket (default "review") when no
    domain shows any signal.
    """
    handle = adapter.author_handle(fm).lower()
    haystack = f"{fm.get('author', '')} {body}".lower()
    domains: dict[str, dict[str, Any]] = config.get("domains", {})

    best_domain: str = config.get("unclassified", "review")
    best_score = 0
    for name, spec in domains.items():
        score = 0
        for author in spec.get("authors", []):
            if author.lower() in handle:
                score += 5
        for keyword in spec.get("keywords", []):
            if re.search(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", haystack):
                score += 1
        if score > best_score:
            best_score = score
            best_domain = name
    return best_domain


def domain_enabled(domain: str, config: dict[str, Any]) -> bool:
    """True when ``domain`` is a configured, enabled routing domain."""
    spec = config.get("domains", {}).get(domain)
    return bool(spec and spec.get("enabled"))


def domain_vault(domain: str, config: dict[str, Any]) -> Path | None:
    """Resolve the vault wiki path for a domain.

    Falls back to the env-resolved default vault (WIKI_VAULT) when an enabled
    domain leaves ``vault`` empty, so a shipped config need not hardcode a path.
    """
    spec = config.get("domains", {}).get(domain) or {}
    vault = spec.get("vault")
    if vault:
        return Path(vault)
    if spec.get("enabled"):
        return paths.default_vault()
    return None


# --------------------------------------------------------------------------- #
# Plan computation
# --------------------------------------------------------------------------- #
def iter_source_files() -> list[Path]:
    """All raw source markdown files, sorted for deterministic output.

    Walks the whole ``raw/`` tree so every registered adapter's sources are
    considered, skipping ``README.md`` and the ``assets/`` attachment store
    (binaries and transcripts, never sources in their own right).
    """
    root = paths.raw_root()
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if path.name == "README.md":
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "assets":
            continue
        files.append(path)
    return sorted(files)


def _canonical_rank(path: Path, source_id: str) -> tuple[int, str]:
    """Lower ranks win: prefer the id-stamped export, then a stable path order."""
    return (0 if path.name.startswith(source_id) else 1, str(path))


def iter_canonical_source_files() -> list[Path]:
    """One raw file per ``source_id``.

    The same source can land in multiple folders (e.g. a hand-named copy
    alongside the id-stamped export). Without deduping, the planner processes
    both and the non-canonical copy shows up as a phantom ``changed`` entry.
    This collapses to a single canonical file per ``source_id``, preferring the
    id-stamped filename. Files without a derivable id are passed through so the
    caller can still log them.
    """
    chosen: dict[str, Path] = {}
    extras: list[Path] = []
    for path in iter_source_files():
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        adapter = source_adapter.adapter_for(path, fm)
        source_id = adapter.source_id(fm, path)
        if not source_id:
            extras.append(path)
            continue
        current = chosen.get(source_id)
        if current is None or _canonical_rank(path, source_id) < _canonical_rank(
            current, source_id
        ):
            chosen[source_id] = path
    return sorted(chosen.values()) + extras


def vault_page_exists(domain: str, slug: str, config: dict[str, Any]) -> bool:
    """Self-heal check: does the source's wiki page exist in its vault?

    Returns False on transient OS errors (a synced vault can briefly
    fail a stat) so a hiccup never crashes the whole plan; the page is simply
    treated as missing and re-queued.
    """
    vault = domain_vault(domain, config)
    if vault is None:
        return False
    try:
        return (vault / "sources" / slug).exists()
    except OSError as exc:
        logger.warning("Vault stat failed for %s/%s: %s", domain, slug, exc)
        return False


def compute_plan(
    config: dict[str, Any],
    state: dict[str, Any],
    *,
    domain_filter: str | None,
    all_domains: bool,
) -> dict[str, Any]:
    """Categorise every raw source into a worklist bucket."""
    sources = state.setdefault("sources", {})
    buckets: dict[str, list[dict[str, Any]]] = {
        "new": [],
        "pending": [],
        "changed": [],
        "missing": [],
        "parked": [],
        "noise": [],
        "up_to_date": [],
    }

    for path in iter_canonical_source_files():
        text = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        adapter = source_adapter.adapter_for(path, fm)
        source_id = adapter.source_id(fm, path)
        if not source_id:
            logger.warning("Skipping (no source_id): %s", path)
            continue

        clean = adapter.clean_body(fm, body)
        body_hash = source_hash(clean)
        entry = sources.get(source_id)
        domain = entry.get("domain") if entry else classify_domain(fm, clean, config, adapter)
        enabled = domain_enabled(domain, config)
        rel = str(path.relative_to(paths.raw_root().parent))
        slug = wiki_source_slug(source_id, fm.get("author", "unknown"), clean)
        flags = adapter.asset_flags(fm, text)

        record = {
            "source_id": source_id,
            "source_type": adapter.source_type_for(fm),
            "file": rel,
            "domain": domain,
            "hash": body_hash,
            "wiki_page": f"sources/{slug}",
            "author": fm.get("author", ""),
            "has_video": flags["has_video"],
        }

        if domain_filter and domain != domain_filter:
            continue

        if entry and entry.get("status") == "noise":
            buckets["noise"].append(record)
            continue

        if not enabled and not all_domains:
            buckets["parked"].append(record)
            continue

        if entry is None:
            buckets["new"].append(record)
        elif entry.get("hash") != body_hash:
            buckets["changed"].append(record)
        elif entry.get("status") != "ingested":
            buckets["pending"].append(record)
        elif not vault_page_exists(domain, Path(entry.get("wiki_page", "x")).name, config):
            buckets["missing"].append(record)
        else:
            buckets["up_to_date"].append(record)

    worklist = buckets["new"] + buckets["pending"] + buckets["changed"] + buckets["missing"]
    return {"buckets": buckets, "worklist": worklist}


def update_manifest(state: dict[str, Any], plan: dict[str, Any], config: dict[str, Any]) -> int:
    """Persist proposed classification + hash for not-yet-finalized sources.

    Sets status "pending" for enabled-domain sources and "parked" for disabled
    ones. Never touches an existing "ingested" or "noise" entry whose hash is
    unchanged. Returns the number of entries written.
    """
    sources = state.setdefault("sources", {})
    written = 0
    for bucket in ("new", "parked"):
        for record in plan["buckets"][bucket]:
            sid = record["source_id"]
            existing = sources.get(sid)
            if (
                existing
                and existing.get("status") in {"ingested", "noise"}
                and existing.get("hash") == record["hash"]
            ):
                continue
            sources[sid] = {
                "file": record["file"],
                "domain": record["domain"],
                "hash": record["hash"],
                "status": "pending" if bucket == "new" else "parked",
                "wiki_page": record["wiki_page"],
                "source_type": record["source_type"],
                "has_video": record["has_video"],
            }
            written += 1
    return written


def mark_ingested(
    state: dict[str, Any],
    plan: dict[str, Any],
    source_ids: list[str],
    config: dict[str, Any],
    *,
    require_page: bool = True,
) -> tuple[int, list[str]]:
    """Flip the given sources to status "ingested" in the manifest.

    Looks each source up in the freshly computed plan to capture its current body
    hash, destination wiki page, and domain, verifies the vault page actually
    exists (unless ``require_page`` is False), then records it as ingested so the
    next plan run reports it up-to-date. This is the finalize step the agent runs
    after writing source pages, replacing ad-hoc manifest edits.

    Returns ``(count_written, problems)`` where ``problems`` lists the source ids
    that could not be marked and why.
    """
    records: dict[str, dict[str, Any]] = {}
    for bucket in plan["buckets"].values():
        for record in bucket:
            records[record["source_id"]] = record

    sources = state.setdefault("sources", {})
    written = 0
    problems: list[str] = []
    for sid in source_ids:
        record = records.get(sid)
        if record is None:
            problems.append(f"{sid}: no raw source found")
            continue
        page_name = Path(record["wiki_page"]).name
        if require_page and not vault_page_exists(record["domain"], page_name, config):
            problems.append(f"{sid}: vault page missing ({record['wiki_page']})")
            continue
        sources[sid] = {
            "file": record["file"],
            "domain": record["domain"],
            "hash": record["hash"],
            "status": "ingested",
            "wiki_page": record["wiki_page"],
            "source_type": record["source_type"],
            "has_video": record["has_video"],
        }
        written += 1
    return written, problems


def mark_noise(
    state: dict[str, Any],
    plan: dict[str, Any],
    source_ids: list[str],
) -> tuple[int, list[str]]:
    """Flip the given sources to status "noise" so they never enter the worklist.

    Records each source's current classification and body hash under status
    "noise" in the manifest. Unlike ``mark_ingested`` this does not verify a
    vault page, because a noise source is deliberately never written to the
    wiki. ``compute_plan`` short-circuits any "noise" entry before the hash
    comparison, so the exclusion is permanent even if the raw body later
    changes. This is the sanctioned "not going to process" lever for backlog
    items the agent should skip going forward.

    Returns ``(count_written, problems)`` where ``problems`` lists the source ids
    that could not be marked and why.
    """
    records: dict[str, dict[str, Any]] = {}
    for bucket in plan["buckets"].values():
        for record in bucket:
            records[record["source_id"]] = record

    sources = state.setdefault("sources", {})
    written = 0
    problems: list[str] = []
    for sid in source_ids:
        record = records.get(sid)
        if record is None:
            problems.append(f"{sid}: no raw source found")
            continue
        sources[sid] = {
            "file": record["file"],
            "domain": record["domain"],
            "hash": record["hash"],
            "status": "noise",
            "wiki_page": record["wiki_page"],
            "source_type": record["source_type"],
            "has_video": record["has_video"],
        }
        written += 1
    return written, problems


def print_summary(plan: dict[str, Any], config: dict[str, Any]) -> None:
    """Human-readable plan summary on stderr."""
    buckets = plan["buckets"]
    domain_counts: dict[str, int] = {}
    for record in plan["worklist"]:
        domain_counts[record["domain"]] = domain_counts.get(record["domain"], 0) + 1

    lines = [
        "Ingest plan",
        "===========",
        f"  new        : {len(buckets['new'])}",
        f"  pending    : {len(buckets['pending'])}  (classified, awaiting ingest)",
        f"  changed    : {len(buckets['changed'])}",
        f"  missing    : {len(buckets['missing'])}  (self-heal: page gone from vault)",
        f"  up-to-date : {len(buckets['up_to_date'])}",
        f"  parked     : {len(buckets['parked'])}  (disabled domain)",
        f"  noise      : {len(buckets['noise'])}",
        f"  WORKLIST   : {len(plan['worklist'])}  (new + pending + changed + missing)",
    ]
    if domain_counts:
        lines.append("  worklist by domain:")
        for domain, count in sorted(domain_counts.items(), key=lambda kv: -kv[1]):
            mark = "on" if domain_enabled(domain, config) else "off"
            lines.append(f"    - {domain} [{mark}]: {count}")
    print("\n".join(lines), file=sys.stderr)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=paths.config_path())
    parser.add_argument("--state", type=Path, default=paths.state_path())
    parser.add_argument("--out", type=Path, help="Write the worklist JSON to this file.")
    parser.add_argument("--domain", help="Restrict the plan to a single domain.")
    parser.add_argument("--all-domains", action="store_true", help="Include disabled domains.")
    parser.add_argument(
        "--update-manifest", action="store_true", help="Persist proposed classifications."
    )
    parser.add_argument(
        "--mark-ingested",
        nargs="+",
        metavar="SOURCE_ID",
        help="Finalize the given sources as ingested (verifies the vault page exists first).",
    )
    parser.add_argument(
        "--allow-missing-page",
        action="store_true",
        help="With --mark-ingested, record the source even if its vault page is absent.",
    )
    parser.add_argument(
        "--mark-noise",
        nargs="+",
        metavar="SOURCE_ID",
        help='Permanently skip the given sources (status "noise"); never worklisted again.',
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit only the worklist JSON on stdout."
    )
    parser.add_argument("-v", "--verbose", action="store_true")
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
        config = load_json(args.config)
        state = load_json(args.state) if args.state.exists() else {"version": 1, "sources": {}}
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return EXIT_ERROR

    mark_problems: list[str] = []
    if args.mark_ingested:
        discovery = compute_plan(config, state, domain_filter=None, all_domains=True)
        written, problems = mark_ingested(
            state,
            discovery,
            args.mark_ingested,
            config,
            require_page=not args.allow_missing_page,
        )
        save_json(args.state, state)
        for problem in problems:
            logger.warning("mark-ingested skipped %s", problem)
        logger.info("Marked ingested: %d source(s) in %s", written, args.state)
        mark_problems.extend(problems)

    if args.mark_noise:
        discovery = compute_plan(config, state, domain_filter=None, all_domains=True)
        written, problems = mark_noise(state, discovery, args.mark_noise)
        save_json(args.state, state)
        for problem in problems:
            logger.warning("mark-noise skipped %s", problem)
        logger.info("Marked noise: %d source(s) in %s", written, args.state)
        mark_problems.extend(problems)

    plan = compute_plan(config, state, domain_filter=args.domain, all_domains=args.all_domains)

    if args.update_manifest:
        written = update_manifest(state, plan, config)
        save_json(args.state, state)
        logger.info("Updated manifest: %d entries written to %s", written, args.state)

    if args.out:
        save_json(args.out, {"worklist": plan["worklist"]})
        logger.info("Wrote worklist (%d items) to %s", len(plan["worklist"]), args.out)

    if args.json:
        print(json.dumps({"worklist": plan["worklist"]}, indent=2, ensure_ascii=False))
    else:
        print_summary(plan, config)

    return EXIT_FAILURE if mark_problems else EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
