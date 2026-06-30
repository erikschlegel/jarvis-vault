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
import sys
from dataclasses import dataclass
from pathlib import Path

from wiki_core import console_scripts, paths, wiki_search

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

# Minimum interpreter the engine supports (matches every plugin's requires-python).
MIN_PYTHON: tuple[int, int] = (3, 12)

# Server name registered in every MCP client config.
MCP_SERVER_NAME = "jarvis-vault"


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


def ensure_raw_root() -> list[str]:
    """Create the immutable ``raw/`` source tree beside the wiki; return new dirs.

    Idempotent: only directories that did not already exist are created and
    reported. ``raw/`` is the sibling the agent reads from, with ``assets`` for
    attachments and ``x`` for X (Twitter) sources.
    """
    root = paths.raw_root()
    created: list[str] = []
    for rel in ("", "assets", "x"):
        target = root / rel if rel else root
        if not target.exists():
            created.append((Path("raw") / rel).as_posix() if rel else "raw")
        target.mkdir(parents=True, exist_ok=True)
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
            MCP_SERVER_NAME: {
                "type": "stdio",
                "command": "uv",
                "args": ["run", "--directory", str(_repo_root()), "wiki-mcp"],
                "env": {"WIKI_VAULT": str(vault)},
            }
        }
    }
    return json.dumps(entry, indent=2)


def copilot_mcp_snippet(vault: Path) -> str:
    """Render the GitHub Copilot CLI registration for the retrieval server.

    Returns the one-shot ``copilot mcp add`` command followed by the equivalent
    ``~/.copilot/mcp-config.json`` block, so a client that auto-starts MCP
    servers from that file picks up ``jarvis-vault`` the same way VS Code does.
    Both forms pin uv to this workspace with ``--directory``; the command relies
    on the layered ``.env`` for ``WIKI_VAULT`` while the JSON block embeds it so
    the entry resolves from any working directory.
    """
    repo = str(_repo_root())
    command = f"copilot mcp add {MCP_SERVER_NAME} -- uv run --directory {repo} wiki-mcp"
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "type": "local",
                "command": "uv",
                "args": ["run", "--directory", repo, "wiki-mcp"],
                "env": {"WIKI_VAULT": str(vault)},
                "tools": ["*"],
            }
        }
    }
    return f"{command}\n\n~/.copilot/mcp-config.json:\n{json.dumps(config, indent=2)}"


def _file_mentions_server(path: Path, name: str) -> bool:
    """Best-effort, fail-soft check that ``path`` registers MCP server ``name``.

    Matches the quoted server key as plain text so JSONC client configs (which
    ``json`` cannot parse) are still detected, and a missing or unreadable file
    is simply absent rather than an error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return f'"{name}"' in text


def mcp_registrations() -> list[str]:
    """Return the MCP clients where ``jarvis-vault`` is registered (best-effort)."""
    found: list[str] = []
    if _file_mentions_server(_repo_root() / ".vscode" / "mcp.json", MCP_SERVER_NAME):
        found.append("VS Code (.vscode/mcp.json)")
    if _file_mentions_server(Path.home() / ".copilot" / "mcp-config.json", MCP_SERVER_NAME):
        found.append("Copilot CLI (~/.copilot/mcp-config.json)")
    return found


def _python_check() -> Diagnostic:
    """Verify the running interpreter meets the minimum supported version."""
    current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info[:2] >= MIN_PYTHON
    minimum = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    detail = current if ok else f"{current} (need >= {minimum}; run `uv python install {minimum}`)"
    return Diagnostic("python", ok, detail)


def _scripts_check() -> Diagnostic:
    """Verify every required console script is registered."""
    missing = console_scripts.missing_scripts()
    if missing:
        return Diagnostic(
            "console scripts",
            False,
            "missing: " + ", ".join(missing) + " (run `uv sync`)",
        )
    return Diagnostic(
        "console scripts",
        True,
        f"{len(console_scripts.REQUIRED_SCRIPTS)} registered",
    )


def _mcp_check() -> Diagnostic:
    """Report which MCP clients have the retrieval server registered."""
    clients = mcp_registrations()
    if clients:
        return Diagnostic("mcp registration", True, "; ".join(clients))
    return Diagnostic(
        "mcp registration",
        False,
        "not registered (run `bash bin/setup.sh` or see SETUP.md)",
    )


def diagnose() -> list[Diagnostic]:
    """Run the read-only onboarding checks and return them in report order."""
    checks: list[Diagnostic] = [_python_check()]
    vault = paths.find_vault()
    if vault is None:
        checks.append(
            Diagnostic(
                "WIKI_VAULT",
                False,
                "not set -- export it or add it to .env (copy .env.example)",
            )
        )
    else:
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
    checks.append(_scripts_check())
    checks.append(_mcp_check())
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

    raw_created = ensure_raw_root()
    if raw_created:
        print(f"\nCreated raw source folders under {paths.raw_root()}:")
        for rel in raw_created:
            print(f"  + {rel}")

    if build:
        print("\nBuilding search index...")
        report = wiki_search.build_index(vault, incremental=True)
        print(json.dumps(report, indent=2))
    else:
        print("\nSkipped index build (--no-build). Run `uv run wiki-search build` later.")

    print("\nVS Code -- .vscode/mcp.json server entry:")
    print(mcp_snippet(vault))
    print("\nGitHub Copilot CLI -- register the retrieval server:")
    print(copilot_mcp_snippet(vault))
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
