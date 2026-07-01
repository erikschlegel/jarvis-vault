#!/usr/bin/env python3
"""Lint the LLM Wiki vault: broken relative links, orphan pages, index/manifest drift.

Read-only. Walks the vault wiki tree, parses inline markdown links, and reports:
  - broken relative links (target file does not resolve on disk)
  - orphan pages (no inbound link from any other wiki page)
  - manifest drift (ingested sources whose wiki_page is missing on disk)

Usage:
    python3 scripts/verify_wiki.py [--vault PATH] [--manifest PATH]

Defaults point at the live iCloud Obsidian vault and the repo manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from wiki_core import paths

# Vault root and manifest resolve lazily from WIKI_VAULT / WIKI_STATE (see
# paths). default_vault() raises SystemExit with setup guidance when WIKI_VAULT
# is unset, so it is resolved inside main() rather than at import time to keep
# importing this module (e.g. during test collection) side-effect free.

# Inline markdown links: [text](target). Skip image links handled the same way.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Fenced code blocks (``` or ~~~) hold template examples, not real links.
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def strip_fenced_code(text: str) -> str:
    """Drop fenced code-block lines so template examples are not linkified."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def is_relative_md(target: str) -> bool:
    """True when the link points at a local markdown file we should resolve."""
    return not target.startswith(("http://", "https://", "mailto:", "#"))


# Markdown ATX headings: capture the heading text for anchor-slug derivation.
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
# Top-level frontmatter scalar keys: `key: value` (nested/list lines are skipped).
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")

# Required frontmatter per content directory: (expected `type`, required keys).
# Vault pages follow the Open Knowledge Format (OKF): every content page declares a
# reserved `type`; sources use the reserved `resource`/`timestamp`/`title` names.
# OKF hard-requires only `type` — `tags` is an optional reserved key (see below).
REQUIRED_FRONTMATTER: dict[str, tuple[str, tuple[str, ...]]] = {
    "sources": ("source", ("tweet_id", "resource", "raw", "timestamp", "domain")),
    "entities": ("entity", ("entity_kind", "name", "domain")),
    "concepts": ("concept", ("name", "domain")),
    "comparisons": ("comparison", ("title",)),
}


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the leading `---` frontmatter block into top-level scalar keys."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")):
            continue  # nested mapping / list item
        match = FRONTMATTER_KEY_RE.match(line)
        if match:
            fm[match.group(1)] = match.group(2).strip()
    return fm


def slugify(heading: str) -> str:
    """Derive a GitHub/Obsidian-style anchor slug from heading or fragment text."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def heading_slugs(text: str) -> set[str]:
    """The set of anchor slugs for every heading in a page (code blocks excluded)."""
    return {
        slugify(match.group(1))
        for line in strip_fenced_code(text).splitlines()
        if (match := HEADING_RE.match(line))
    }


def collect_md_files(wiki_root: Path) -> list[Path]:
    return sorted(p for p in wiki_root.rglob("*.md"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()

    wiki_root: Path = args.vault if args.vault is not None else paths.default_vault()
    manifest_path: Path = args.manifest if args.manifest is not None else paths.state_path()
    if not wiki_root.is_dir():
        print(f"ERROR: vault wiki root not found: {wiki_root}", file=sys.stderr)
        return 2

    md_files = collect_md_files(wiki_root)

    def rel(p: Path) -> str:
        return p.relative_to(wiki_root).as_posix()

    text_by_path: dict[Path, str] = {
        p: p.read_text(encoding="utf-8", errors="replace") for p in md_files
    }
    slugs_by_path: dict[Path, set[str]] = {
        p.resolve(): heading_slugs(text) for p, text in text_by_path.items()
    }

    broken: list[tuple[str, str]] = []
    anchor_broken: list[tuple[str, str]] = []
    inbound: dict[Path, int] = {p.resolve(): 0 for p in md_files}

    for src in md_files:
        for raw_target in LINK_RE.findall(strip_fenced_code(text_by_path[src])):
            target, _, fragment = raw_target.partition("#")
            target = target.strip()
            if not target or not is_relative_md(target):
                continue
            resolved = (src.parent / target).resolve()
            if resolved.suffix != ".md":
                # Non-markdown relative asset; check existence only.
                if not resolved.exists():
                    broken.append((rel(src), raw_target))
                continue
            if not resolved.exists():
                broken.append((rel(src), raw_target))
                continue
            if resolved in inbound:
                inbound[resolved] += 1
            if fragment.strip() and slugify(fragment) not in slugs_by_path.get(resolved, set()):
                anchor_broken.append((rel(src), raw_target))

    # Orphans: content pages (sources/entities/concepts/comparisons) with 0 inbound links.
    content_dirs = {"sources", "entities", "concepts", "comparisons"}
    orphans: list[str] = []
    for p in md_files:
        parts = p.relative_to(wiki_root).parts
        if parts and parts[0] in content_dirs and inbound.get(p.resolve(), 0) == 0:
            orphans.append(rel(p))

    # Frontmatter schema: required keys and matching `type` per content directory.
    frontmatter_violations: list[str] = []
    for p in md_files:
        parts = p.relative_to(wiki_root).parts
        if not parts or parts[0] not in REQUIRED_FRONTMATTER:
            continue
        expected_type, required_keys = REQUIRED_FRONTMATTER[parts[0]]
        fm = parse_frontmatter(text_by_path[p])
        if not fm:
            frontmatter_violations.append(f"{rel(p)}: missing frontmatter")
            continue
        actual_type = fm.get("type", "")
        if actual_type != expected_type:
            frontmatter_violations.append(
                f"{rel(p)}: type '{actual_type or '(none)'}' != '{expected_type}'"
            )
        missing = [k for k in required_keys if not fm.get(k)]
        if missing:
            frontmatter_violations.append(f"{rel(p)}: missing {', '.join(missing)}")
        # `tags` is an optional OKF reserved key. Absent or empty is conformant; when
        # present inline (`tags: [..]`) it must be a YAML list. Block-style lists are
        # skipped by the scalar parser and so are not checked here.
        tags_val = fm.get("tags")
        if tags_val and not tags_val.startswith("["):
            frontmatter_violations.append(f"{rel(p)}: tags must be a list")

    # Manifest drift (forward): ingested sources whose wiki_page is missing on disk.
    # Reverse drift: source pages on disk not finalized as ingested in the manifest.
    drift: list[str] = []
    unfinalized: list[str] = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources_meta = manifest.get("sources", {})
        for tid, meta in sources_meta.items():
            if meta.get("status") != "ingested":
                continue
            page = meta.get("wiki_page")
            if not page:
                drift.append(f"{tid}: ingested but no wiki_page")
                continue
            if not (wiki_root / page).exists():
                drift.append(f"{tid}: {page} (missing on disk)")

        status_by_id = {tid: meta.get("status") for tid, meta in sources_meta.items()}
        for p in md_files:
            parts = p.relative_to(wiki_root).parts
            if not parts or parts[0] != "sources":
                continue
            tweet_id = parse_frontmatter(text_by_path[p]).get("tweet_id", "").strip("\"'")
            if not tweet_id:
                continue  # already surfaced by the frontmatter schema check
            status = status_by_id.get(tweet_id)
            if status != "ingested":
                unfinalized.append(f"{rel(p)}: manifest status '{status or '(absent)'}'")

    print(f"vault: {wiki_root}")
    print(f"markdown pages scanned: {len(md_files)}")
    print()

    print(f"== broken relative links: {len(broken)} ==")
    for broken_src, broken_target in broken:
        print(f"  {broken_src} -> {broken_target}")
    print()

    print(f"== broken anchor links (missing heading): {len(anchor_broken)} ==")
    for anchor_src, anchor_target in anchor_broken:
        print(f"  {anchor_src} -> {anchor_target}")
    print()

    print(f"== frontmatter schema violations: {len(frontmatter_violations)} ==")
    for v in frontmatter_violations:
        print(f"  {v}")
    print()

    print(f"== orphan content pages (no inbound links): {len(orphans)} ==")
    for o in orphans:
        print(f"  {o}")
    print()

    print(f"== manifest drift (ingested page missing): {len(drift)} ==")
    for d in drift:
        print(f"  {d}")
    print()

    print(f"== source pages not finalized as ingested: {len(unfinalized)} ==")
    for u in unfinalized:
        print(f"  {u}")

    return 1 if (broken or anchor_broken or frontmatter_violations or drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
