"""Hermetic tests for the ``wiki-init`` / ``wiki-doctor`` onboarding helpers.

Seeding is tested against a throwaway template built in ``tmp_path`` so the
suite never depends on the shipped template's contents, and diagnostics are
tested with a monkeypatched empty ``.env`` so an unset ``WIKI_VAULT`` is
genuinely unconfigured regardless of the developer's environment.
"""

from __future__ import annotations

import json
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


def _write_copilot_settings(home: Path, specs: dict[str, bool]) -> None:
    settings = home / ".copilot" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"enabledPlugins": specs}),
        encoding="utf-8",
    )


def _materialize_skills(home: Path, skills: list[str]) -> None:
    skills_dir = home / ".copilot" / "skills"
    for skill in skills:
        (skills_dir / skill).mkdir(parents=True, exist_ok=True)


_ALL_SKILLS = ["wiki-ingest", "wiki-lint", "wiki-query", "x-import", "x-transcribe"]


def test_plugin_skills_matches_repo_layout() -> None:
    """PLUGIN_SKILLS must mirror ``plugins/<name>/skills/*/`` (drift guard).

    The hard-coded map is the authoritative expectation that makes
    ``_plugins_check`` able to detect a stale ``enabledPlugins`` flag; a runtime
    directory scan would silently pass if it ever returned empty. Asserting the
    invariant here catches drift at commit time instead: adding or removing a
    skill directory without updating the constant fails this test.
    """
    repo = wiki_init._repo_root()
    for plugin, skills in wiki_init.PLUGIN_SKILLS.items():
        skills_dir = repo / "plugins" / plugin / "skills"
        on_disk = {child.name for child in skills_dir.iterdir() if (child / "SKILL.md").is_file()}
        assert set(skills) == on_disk, f"{plugin} skills drifted from {skills_dir}"


def test_plugins_check_passes_when_skills_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _write_copilot_settings(home, {"wiki-core@jarvis-vault": True})
    _materialize_skills(home, _ALL_SKILLS)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: tmp_path / "repo")
    check = wiki_init._plugins_check()
    assert check.warn_only is True
    assert check.ok is True


def test_plugins_check_warns_when_enabled_but_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    # Both flags enabled, but no skills were materialized -- the stale-flag case.
    _write_copilot_settings(
        home,
        {"wiki-core@jarvis-vault": True, "wiki-connector-x@jarvis-vault": True},
    )
    repo = tmp_path / "repo"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: repo)
    check = wiki_init._plugins_check()
    assert check.ok is False
    assert check.warn_only is True
    assert "enabled but skills not installed" in check.detail
    assert "copilot plugin install wiki-core@jarvis-vault" in check.detail
    assert "copilot plugin install wiki-connector-x@jarvis-vault" in check.detail


def test_plugins_check_reports_partial_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _write_copilot_settings(home, {"wiki-core@jarvis-vault": True})
    # wiki-connector-x fully installed; wiki-core missing one skill.
    _materialize_skills(home, ["wiki-ingest", "wiki-lint", "x-import", "x-transcribe"])
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: tmp_path / "repo")
    check = wiki_init._plugins_check()
    assert check.ok is False
    assert "partial: missing wiki-query" in check.detail
    assert "wiki-connector-x" not in check.detail


def test_plugins_check_warns_and_prints_install_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    # A disabled plugin and an unrelated one -- neither required plugin is installed.
    _write_copilot_settings(home, {"wiki-core@jarvis-vault": False, "other@elsewhere": True})
    repo = tmp_path / "repo"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: repo)
    check = wiki_init._plugins_check()
    assert check.ok is False
    assert check.warn_only is True
    assert "wiki-core" in check.detail
    assert "wiki-connector-x" in check.detail
    assert f"copilot plugin marketplace add {repo}" in check.detail
    assert "copilot plugin install wiki-core@jarvis-vault" in check.detail
    assert "copilot plugin install wiki-connector-x@jarvis-vault" in check.detail


def test_plugins_check_omits_marketplace_add_when_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    settings = home / ".copilot" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "enabledPlugins": {"wiki-core@jarvis-vault": True},
                "extraKnownMarketplaces": {"jarvis-vault": {}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: tmp_path / "repo")
    check = wiki_init._plugins_check()
    assert check.ok is False
    assert "copilot plugin marketplace add" not in check.detail
    assert "copilot plugin install wiki-core@jarvis-vault" in check.detail


def test_plugins_check_fail_soft_when_settings_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(wiki_init, "_repo_root", lambda: tmp_path / "repo")
    check = wiki_init._plugins_check()
    assert check.ok is False
    assert check.warn_only is True


def test_copilot_cli_check_reports_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki_core.wiki_init.shutil.which", lambda _: "/usr/local/bin/copilot")
    check = wiki_init._copilot_cli_check()
    assert check.ok is True
    assert check.warn_only is True
    assert check.detail == "/usr/local/bin/copilot"


def test_copilot_cli_check_warns_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki_core.wiki_init.shutil.which", lambda _: None)
    check = wiki_init._copilot_cli_check()
    assert check.ok is False
    assert check.warn_only is True
    assert "not found on PATH" in check.detail


def test_print_diagnostics_warn_does_not_fail(capsys: pytest.CaptureFixture[str]) -> None:
    checks = [
        wiki_init.Diagnostic("python", True, "3.12"),
        wiki_init.Diagnostic("skill plugins", False, "not enabled", warn_only=True),
    ]
    all_ok = wiki_init._print_diagnostics(checks)
    assert all_ok is True
    out = capsys.readouterr().out
    assert "[warn] skill plugins" in out
    assert "[ok  ] python" in out


def test_print_diagnostics_required_failure_fails(capsys: pytest.CaptureFixture[str]) -> None:
    checks = [
        wiki_init.Diagnostic("vault directory", False, "missing"),
        wiki_init.Diagnostic("skill plugins", False, "not enabled", warn_only=True),
    ]
    all_ok = wiki_init._print_diagnostics(checks)
    assert all_ok is False
    out = capsys.readouterr().out
    assert "[FAIL] vault directory" in out
