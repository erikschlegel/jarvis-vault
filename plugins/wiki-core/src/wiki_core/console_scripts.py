"""Single source of truth for the engine's required console scripts.

The skills invoke these deterministic entry points by name. Listing them once
here lets both ``wiki-doctor`` (Python) and ``bin/setup.sh`` (shell) validate the
same set without drifting -- the shell script reads this list via
``python -c "from wiki_core.console_scripts import REQUIRED_SCRIPTS; ..."``.
"""

from __future__ import annotations

from importlib import metadata

# Console scripts declared by wiki-core and wiki-connector-x (see each plugin's
# ``[project.scripts]``). Order is the report order shown by wiki-doctor/setup.
REQUIRED_SCRIPTS: tuple[str, ...] = (
    "wiki-search",
    "wiki-verify",
    "wiki-pages",
    "wiki-plan",
    "wiki-mcp",
    "wiki-init",
    "wiki-doctor",
    "x-fetch",
    "x-import",
    "x-transcribe",
    "x-refresh-streams",
)


def installed_scripts() -> set[str]:
    """Return the names of every registered ``console_scripts`` entry point."""
    return {ep.name for ep in metadata.entry_points(group="console_scripts")}


def missing_scripts() -> list[str]:
    """Return required scripts that are not registered, in declared order."""
    installed = installed_scripts()
    return [name for name in REQUIRED_SCRIPTS if name not in installed]
