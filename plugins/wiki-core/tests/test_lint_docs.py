"""Hermetic tests for the repository markdown + SKILL.md frontmatter linter.

Each test builds a minimal ``tmp_path`` repository tree and drives
``lint_docs.main`` against it via ``--root``. The live repository and the
external vault are never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core import lint_docs

CLEAN_DOC = "# Demo\n\nBody paragraph.\n"

VALID_SKILL = """\
---
name: demo-skill
description: "Does a demonstrable thing."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-06-28"
---

# Demo Skill

Body text.
"""

# A heading with trailing punctuation yields exactly one violation:
# PyMarkdown MD026 (no-trailing-punctuation in heading).
BAD_DOC = "# Title.\n\nbody\n"


def _build_repo(tmp_path: Path) -> Path:
    """A clean repo tree that the linter passes with exit code 0."""
    (tmp_path / "README.md").write_text(CLEAN_DOC, encoding="utf-8")
    skill_dir = tmp_path / "plugins" / "demo" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    return tmp_path


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = lint_docs.main(["--root", str(root)])
    return code, capsys.readouterr().out


def test_clean_repo_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _build_repo(tmp_path)
    code, out = _run(root, capsys)
    assert code == 0
    assert "structural violations: 0" in out
    assert "SKILL.md frontmatter violations: 0" in out


def test_structural_violation_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _build_repo(tmp_path)
    (root / "broken.md").write_text(BAD_DOC, encoding="utf-8")
    code, out = _run(root, capsys)
    assert code == 1
    assert "structural violations: 1" in out
    assert "MD026" in out


def test_templates_are_excluded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _build_repo(tmp_path)
    templates = root / "plugins" / "demo" / "templates" / "vault"
    templates.mkdir(parents=True)
    (templates / "bad.md").write_text(BAD_DOC, encoding="utf-8")
    code, out = _run(root, capsys)
    assert code == 0
    assert "structural violations: 0" in out


def test_skill_name_mismatch_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _build_repo(tmp_path)
    skill = root / "plugins" / "demo" / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(VALID_SKILL.replace("name: demo-skill", "name: wrong-name"), "utf-8")
    code, out = _run(root, capsys)
    assert code == 1
    assert "SKILL.md frontmatter violations: 1" in out
    assert "!= directory 'demo-skill'" in out


def test_skill_missing_metadata_key_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _build_repo(tmp_path)
    skill = root / "plugins" / "demo" / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(VALID_SKILL.replace('  spec_version: "1.0"\n', ""), "utf-8")
    code, out = _run(root, capsys)
    assert code == 1
    assert "metadata missing spec_version" in out


def test_skill_empty_description_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _build_repo(tmp_path)
    skill = root / "plugins" / "demo" / "skills" / "demo-skill" / "SKILL.md"
    mutated = VALID_SKILL.replace('description: "Does a demonstrable thing."', 'description: ""')
    skill.write_text(mutated, encoding="utf-8")
    code, out = _run(root, capsys)
    assert code == 1
    assert "empty or missing description" in out
