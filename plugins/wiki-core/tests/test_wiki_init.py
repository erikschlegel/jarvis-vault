"""Hermetic tests for the ``wiki-init`` / ``wiki-doctor`` onboarding helpers.

Seeding is tested against a throwaway template built in ``tmp_path`` so the
suite never depends on the shipped template's contents, and diagnostics are
tested with a monkeypatched empty ``.env`` so an unset ``WIKI_VAULT`` is
genuinely unconfigured regardless of the developer's environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core import paths, wiki_init


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to an empty discovered ``.env`` mapping."""
    monkeypatch.setattr(paths, "_dotenv", lambda: {})


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A minimal seed template with a nested file and a dot-directory entry."""
    root = tmp_path / "template"
    (root / "sources").mkdir(parents=True)
    (root / ".obsidian").mkdir()
    (root / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "pulse.md").write_text("# Pulse\n", encoding="utf-8")
    (root / "sources" / ".gitkeep").write_text("", encoding="utf-8")
    (root / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    return root


def test_seed_vault_copies_all_files(template: Path, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    created = wiki_init.seed_vault(vault, template)
    assert set(created) == {
        ".obsidian/app.json",
        "index.md",
        "pulse.md",
        "sources/.gitkeep",
    }
    assert (vault / "index.md").read_text(encoding="utf-8") == "# Index\n"
    assert (vault / ".obsidian" / "app.json").is_file()


def test_seed_vault_is_idempotent(template: Path, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki_init.seed_vault(vault, template)
    assert wiki_init.seed_vault(vault, template) == []


def test_seed_vault_does_not_overwrite_user_edits(template: Path, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki_init.seed_vault(vault, template)
    (vault / "index.md").write_text("# My edits\n", encoding="utf-8")
    wiki_init.seed_vault(vault, template)
    assert (vault / "index.md").read_text(encoding="utf-8") == "# My edits\n"


def test_seed_vault_force_recopies(template: Path, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki_init.seed_vault(vault, template)
    (vault / "index.md").write_text("# My edits\n", encoding="utf-8")
    created = wiki_init.seed_vault(vault, template, force=True)
    assert "index.md" in created
    assert (vault / "index.md").read_text(encoding="utf-8") == "# Index\n"


def test_seed_vault_missing_template_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        wiki_init.seed_vault(tmp_path / "vault", tmp_path / "missing")


def test_diagnose_reports_unset_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VAULT", raising=False)
    checks = wiki_init.diagnose()
    assert len(checks) == 1
    assert checks[0].name == "WIKI_VAULT"
    assert checks[0].ok is False


def test_diagnose_reports_built_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "wiki"
    vault.mkdir()
    (vault / "index.md").write_text("# Index\n", encoding="utf-8")
    index = vault / ".wiki_index"
    index.mkdir()
    (index / "meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WIKI_VAULT", str(vault))
    monkeypatch.delenv("WIKI_INDEX_DIR", raising=False)
    checks = wiki_init.diagnose()
    assert {c.name for c in checks} == {
        "WIKI_VAULT",
        "vault directory",
        "index.md",
        "search index",
    }
    assert all(c.ok for c in checks)


def test_mcp_snippet_embeds_vault(tmp_path: Path) -> None:
    snippet = wiki_init.mcp_snippet(tmp_path / "wiki")
    assert str(tmp_path / "wiki") in snippet
    assert "erik-wiki" in snippet
    # The portable form is the repo-local `uv run --directory <repo>`, not the
    # unpublished `uvx --from wiki-core`.
    assert "uvx" not in snippet
    assert "--directory" in snippet
    assert str(wiki_init._repo_root()) in snippet
