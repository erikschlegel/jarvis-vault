#!/usr/bin/env python3
"""Lint repository markdown: structural rules plus SKILL.md frontmatter schema.

Two deterministic checks run over the repository's own markdown (never the
external vault, which `wiki-verify` owns):

  1. PyMarkdown structural lint over every tracked ``*.md`` file. The repository
     deliberately uses em-dashes and bold-prefix list items and keeps long prose
     lines, so the line-length rule (MD013) is disabled; the front-matter
     extension is enabled so SKILL.md frontmatter parses as data, not content.
  2. SKILL.md frontmatter schema: each ``skills/<name>/SKILL.md`` must declare a
     ``name`` matching its directory, a non-empty quoted ``description``,
     ``user-invocable``, and a ``metadata`` block with ``spec_version`` and
     ``last_updated``.

Top-level repository docs (README, AGENTS, CLAUDE, SETUP, docs/*) carry no
frontmatter and are exempt from the schema check; only their structure is linted.

Usage:
    lint-docs [--root PATH]

Exits non-zero on any structural failure or schema violation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pymarkdown.api import PyMarkdownApi, PyMarkdownScanFailure

# Directories that never hold repository documentation we lint here. The vault
# seed templates are vault pages (OKF format, governed by `wiki-verify`), not
# repository documentation prose, so they are out of scope for this check.
SKIP_DIRS = frozenset({".venv", ".git", ".wiki_index", "node_modules", "__pycache__", "templates"})

# Structural rules disabled because they conflict with the repository's
# deliberate house style (long prose lines).
DISABLED_RULES = ("md013",)

# A top-level frontmatter scalar key line: `key: value`.
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
# A key nested one level under a mapping (two-space indent): `  key: value`.
_NESTED_KEY_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(.*)$")


def repo_root() -> Path:
    """Repository root: four parents up from this module inside plugins/*/src/*."""
    return Path(__file__).resolve().parents[4]


def find_markdown(root: Path) -> list[Path]:
    """Every repository markdown file, skipping generated and vendored trees."""
    return sorted(
        path for path in root.rglob("*.md") if not (SKIP_DIRS & set(path.relative_to(root).parts))
    )


def _scanner() -> PyMarkdownApi:
    """A PyMarkdown API configured for the repository's markdown conventions."""
    api = PyMarkdownApi()
    api.enable_extension_by_identifier("front-matter")
    for rule in DISABLED_RULES:
        api.disable_rule_by_identifier(rule)
    return api


def lint_structure(files: list[Path], root: Path) -> list[str]:
    """Run PyMarkdown over each file; return human-readable violation strings."""
    api = _scanner()
    violations: list[str] = []
    for path in files:
        result = api.scan_path(str(path))
        for failure in result.scan_failures:
            violations.append(_format_failure(failure, path, root))
        for critical in result.critical_errors:
            violations.append(f"{path.relative_to(root).as_posix()}: critical: {critical}")
    return violations


def _format_failure(failure: PyMarkdownScanFailure, path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return (
        f"{rel}:{failure.line_number}:{failure.column_number} "
        f"{failure.rule_id} {failure.rule_name}: {failure.rule_description}"
    )


def frontmatter_block(text: str) -> list[str] | None:
    """The lines inside a leading `---` frontmatter block, or None if absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return block
        block.append(line)
    return None  # unterminated block


def validate_skill_frontmatter(path: Path, root: Path) -> list[str]:
    """Validate one SKILL.md frontmatter against the skill manifest schema."""
    rel = path.relative_to(root).as_posix()
    block = frontmatter_block(path.read_text(encoding="utf-8"))
    if block is None:
        return [f"{rel}: missing or unterminated frontmatter block"]

    top: dict[str, str] = {}
    metadata: dict[str, str] = {}
    in_metadata = False
    for line in block:
        if not line.strip():
            continue
        top_match = _KEY_RE.match(line)
        if top_match and not line.startswith((" ", "\t")):
            key, value = top_match.group(1), top_match.group(2).strip()
            top[key] = value
            in_metadata = key == "metadata"
            continue
        nested_match = _NESTED_KEY_RE.match(line)
        if nested_match and in_metadata:
            metadata[nested_match.group(1)] = nested_match.group(2).strip()

    errors: list[str] = []
    expected_name = path.parent.name
    name = top.get("name", "").strip("\"'")
    if name != expected_name:
        errors.append(f"{rel}: name '{name or '(none)'}' != directory '{expected_name}'")
    if not top.get("description", "").strip("\"'"):
        errors.append(f"{rel}: empty or missing description")
    if "user-invocable" not in top:
        errors.append(f"{rel}: missing user-invocable")
    if "metadata" not in top:
        errors.append(f"{rel}: missing metadata block")
    else:
        for required in ("spec_version", "last_updated"):
            if not metadata.get(required):
                errors.append(f"{rel}: metadata missing {required}")
    return errors


def skill_files(root: Path) -> list[Path]:
    """Every ``skills/<name>/SKILL.md`` under any plugin (sorted)."""
    return sorted(root.glob("plugins/*/skills/*/SKILL.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="Repository root to lint.")
    args = parser.parse_args(argv)

    root = (args.root or repo_root()).resolve()
    if not root.is_dir():
        print(f"ERROR: repository root not found: {root}", file=sys.stderr)
        return 2

    md_files = find_markdown(root)
    structural = lint_structure(md_files, root)

    schema: list[str] = []
    for skill in skill_files(root):
        schema.extend(validate_skill_frontmatter(skill, root))

    print(f"root: {root}")
    print(f"markdown files linted: {len(md_files)}")
    print()
    print(f"== structural violations: {len(structural)} ==")
    for line in structural:
        print(f"  {line}")
    print()
    print(f"== SKILL.md frontmatter violations: {len(schema)} ==")
    for line in schema:
        print(f"  {line}")

    return 1 if (structural or schema) else 0


if __name__ == "__main__":
    raise SystemExit(main())
