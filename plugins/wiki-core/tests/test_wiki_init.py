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
    by_name = {c.name: c for c in checks}
    assert "python" in by_name
    assert by_name["WIKI_VAULT"].ok is False
    # Vault-dependent checks are skipped entirely when WIKI_VAULT is unset.
    assert "vault directory" not in by_name


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
    by_name = {c.name: c for c in checks}
    vault_checks = {"WIKI_VAULT", "vault directory", "index.md", "search index"}
    assert vault_checks <= set(by_name)
    assert by_name["python"].ok
    for name in vault_checks:
        assert by_name[name].ok


def test_mcp_snippet_embeds_vault(tmp_path: Path) -> None:
    snippet = wiki_init.mcp_snippet(tmp_path / "wiki")
    assert str(tmp_path / "wiki") in snippet
    assert "jarvis-vault" in snippet
    # The portable form is the repo-local `uv run --directory <repo>`, not the
    # unpublished `uvx --from wiki-core`.
    assert "uvx" not in snippet
    assert "--directory" in snippet
    assert str(wiki_init._repo_root()) in snippet


def test_copilot_mcp_snippet_emits_command_and_config(tmp_path: Path) -> None:
    snippet = wiki_init.copilot_mcp_snippet(tmp_path / "wiki")
    assert "copilot mcp add jarvis-vault" in snippet
    assert "~/.copilot/mcp-config.json" in snippet
    assert "mcpServers" in snippet
    assert str(tmp_path / "wiki") in snippet
    assert str(wiki_init._repo_root()) in snippet
    assert "uvx" not in snippet


def test_ensure_raw_root_creates_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault" / "wiki"
    vault.mkdir(parents=True)
    monkeypatch.setenv("WIKI_VAULT", str(vault))
    monkeypatch.delenv("WIKI_RAW", raising=False)
    created = wiki_init.ensure_raw_root()
    assert set(created) == {"raw", "raw/assets", "raw/x"}
    raw = tmp_path / "vault" / "raw"
    assert (raw / "assets").is_dir()
    assert (raw / "x").is_dir()


def test_ensure_raw_root_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault" / "wiki"
    vault.mkdir(parents=True)
    monkeypatch.setenv("WIKI_VAULT", str(vault))
    monkeypatch.delenv("WIKI_RAW", raising=False)
    wiki_init.ensure_raw_root()
    assert wiki_init.ensure_raw_root() == []


def test_file_mentions_server_detects_quoted_key(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('// comment\n{"servers": {"jarvis-vault": {}}}\n', encoding="utf-8")
    assert wiki_init._file_mentions_server(config, "jarvis-vault") is True
    assert wiki_init._file_mentions_server(config, "other") is False
    assert wiki_init._file_mentions_server(tmp_path / "missing.json", "jarvis-vault") is False


def test_mcp_registrations_finds_vscode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".vscode").mkdir(parents=True)
    (repo / ".vscode" / "mcp.json").write_text(
        '{"servers": {"jarvis-vault": {}}}\n', encoding="utf-8"
    )
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert wiki_init.mcp_registrations() == ["VS Code (.vscode/mcp.json)"]
