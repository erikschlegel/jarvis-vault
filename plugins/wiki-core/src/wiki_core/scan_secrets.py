#!/usr/bin/env python3
"""Credential scan for the repository: a deterministic detect-secrets gate.

Runs the detect-secrets pre-commit hook over the repository's git-tracked files,
comparing findings against the committed ``.secrets.baseline`` allowlist. Exits
non-zero when a secret is found that is not already recorded in the baseline.

Usage:
    scan-secrets [--baseline PATH] [FILE ...]

With no FILE arguments the scan covers every git-tracked file. The baseline's
``should_exclude_file`` patterns (``.venv/``, ``.wiki_index/``, ``uv.lock``,
``.secrets.baseline``) drop generated and vendored paths even when passed
explicitly, so the result is stable regardless of the working tree.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from detect_secrets.pre_commit_hook import main as hook_main


def repo_root() -> Path:
    """Repository root: four parents up from this module inside plugins/*/src/*."""
    return Path(__file__).resolve().parents[4]


def tracked_files(root: Path) -> list[str]:
    """Return repository-relative paths of every git-tracked file (sorted)."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(name for name in result.stdout.split("\0") if name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to the detect-secrets baseline (default: <repo>/.secrets.baseline).",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files to scan (default: all git-tracked files).",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    baseline = args.baseline or (root / ".secrets.baseline")
    if not baseline.exists():
        print(f"ERROR: secrets baseline not found: {baseline}", file=sys.stderr)
        return 2

    files = args.files or tracked_files(root)
    if not files:
        print("no files to scan")
        return 0

    # The baseline's exclude patterns are anchored to repository-relative paths,
    # so the hook must run from the repository root with relative file names.
    previous_cwd = Path.cwd()
    os.chdir(root)
    try:
        return hook_main([*files, "--baseline", str(baseline)])
    finally:
        os.chdir(previous_cwd)


if __name__ == "__main__":
    raise SystemExit(main())
