#!/usr/bin/env python3
"""Onboarding and diagnostics for the LLM Wiki engine.

``wiki-init`` makes a fresh checkout usable in one command: it validates
``WIKI_VAULT``, seeds an empty vault from the shipped template, builds the
search index, and prints an mcp.json server entry. ``wiki-doctor`` reports the
same checks read-only, so you can see exactly what is missing before changing
anything.

Both are idempotent and safe to re-run: seeding never overwrites an existing
file (pass ``--force`` to re-copy the template), and a build over an unchanged
vault is a no-op.

CLI:
    uv run wiki-init [--force] [--no-build]
    uv run wiki-doctor
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from wiki_core import paths, wiki_search

EXIT_SUCCESS = 0
EXIT_FAILURE = 1


@dataclass
class Diagnostic:
    """One onboarding check: a name, pass/fail, and a human-readable detail."""

    name: str
    ok: bool
    detail: str


def _templates_vault() -> Path:
    """Locate the shipped seed vault (``templates/vault`` beside the package)."""
    return Path(__file__).resolve().parents[2] / "templates" / "vault"


def _repo_root() -> Path:
    """Locate the workspace root (the uv workspace that owns the console scripts)."""
    return Path(__file__).resolve().parents[4]


def seed_vault(vault: Path, template: Path, *, force: bool = False) -> list[str]:
    """Copy missing template files into ``vault``; return the created relative paths.

    Idempotent: an existing destination file is left untouched unless ``force``
    is set. Returns vault-relative paths (POSIX) of every file written.
    """
    if not template.is_dir():
        raise SystemExit(f"Template vault not found: {template}")
    created: list[str] = []
    for src in sorted(p for p in template.rglob("*") if p.is_file()):
        rel = src.relative_to(template)
        dest = vault / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(rel.as_posix())
    return created


def mcp_snippet(vault: Path) -> str:
    """Render an mcp.json server entry wired to ``vault`` via an env var.

    Uses the repo-local ``uv run --directory <repo>`` form so the entry works
    from any MCP client's working directory: ``--directory`` pins uv to this
    workspace (which owns the ``wiki-mcp`` console script), and ``WIKI_VAULT``
    points the engine at the seeded vault.
    """
    entry = {
        "servers": {
            "erik-wiki": {
                "type": "stdio",
                "command": "uv",
                "args": ["run", "--directory", str(_repo_root()), "wiki-mcp"],
                "env": {"WIKI_VAULT": str(vault)},
            }
        }
    }
    return json.dumps(entry, indent=2)


def diagnose() -> list[Diagnostic]:
    """Run the read-only onboarding checks and return them in report order."""
    checks: list[Diagnostic] = []
    vault = paths.find_vault()
    if vault is None:
        checks.append(
            Diagnostic(
                "WIKI_VAULT",
                False,
                "not set -- export it or add it to .env (copy .env.example)",
            )
        )
        return checks
    checks.append(Diagnostic("WIKI_VAULT", True, str(vault)))
    checks.append(
        Diagnostic(
            "vault directory",
            vault.is_dir(),
            "present" if vault.is_dir() else f"missing: {vault} (run `uv run wiki-init`)",
        )
    )
    index_md = vault / "index.md"
    checks.append(
        Diagnostic(
            "index.md",
            index_md.is_file(),
            "present"
            if index_md.is_file()
            else "missing: run `uv run wiki-init` to seed the vault",
        )
    )
    meta = paths.index_dir() / "meta.json"
    checks.append(
        Diagnostic(
            "search index",
            meta.is_file(),
            str(meta.parent)
            if meta.is_file()
            else "not built: run `uv run wiki-init` or `uv run wiki-search build`",
        )
    )
    return checks


def run_init(*, force: bool, build: bool) -> int:
    """Seed the configured vault, optionally build the index, and print an mcp.json entry."""
    vault = paths.default_vault()
    template = _templates_vault()
    vault.mkdir(parents=True, exist_ok=True)

    created = seed_vault(vault, template, force=force)
    if created:
        print(f"Seeded {len(created)} file(s) into {vault}:")
        for rel in created:
            print(f"  + {rel}")
    else:
        print(f"Vault already populated at {vault} (nothing to seed).")

    if build:
        print("\nBuilding search index...")
        report = wiki_search.build_index(vault, incremental=True)
        print(json.dumps(report, indent=2))
    else:
        print("\nSkipped index build (--no-build). Run `uv run wiki-search build` later.")

    print("\nmcp.json server entry:")
    print(mcp_snippet(vault))
    return EXIT_SUCCESS


def _print_diagnostics(checks: list[Diagnostic]) -> bool:
    """Print each check with a status marker; return True when all passed."""
    all_ok = True
    for check in checks:
        marker = "ok  " if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
        all_ok = all_ok and check.ok
    return all_ok


def main() -> int:
    """Console entry point for ``wiki-init``."""
    parser = argparse.ArgumentParser(
        description="Seed the wiki vault, build the index, and print an mcp.json entry.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-copy template files over existing ones."
    )
    parser.add_argument(
        "--no-build",
        dest="build",
        action="store_false",
        help="Skip the search-index build (e.g. offline, before the embed model is cached).",
    )
    args = parser.parse_args()
    return run_init(force=args.force, build=args.build)


def doctor_main() -> int:
    """Console entry point for ``wiki-doctor`` (read-only diagnostics)."""
    parser = argparse.ArgumentParser(
        description="Report the wiki engine's configuration and index health (read-only).",
    )
    parser.parse_args()
    ok = _print_diagnostics(diagnose())
    if not ok:
        print("\nSome checks failed. Run `uv run wiki-init` to set up the vault and index.")
    return EXIT_SUCCESS if ok else EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
