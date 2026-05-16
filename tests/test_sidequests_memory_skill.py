"""Test suite for SideQuests memory skill (LEGACY) (B246).

Validates legacy forwarding compatibility.
"""

import os
from pathlib import Path

from campy.cli.register import install_codex_memory_skill


def test_legacy_memory_skill_file_exists():
    """Verify the legacy skill file exists."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    assert os.path.exists(skill_path), f"Skill file not found at {skill_path}"
    
    with open(skill_path, "r") as f:
        content = f.read()
        assert "replaced by" in content.lower()
        assert "campy-memory" in content.lower()


def test_install_codex_memory_skill_prefers_campy(tmp_path, monkeypatch):
    """Codex registration installs campy-memory by default."""
    monkeypatch.setenv("HOME", str(tmp_path))
    target = install_codex_memory_skill(Path.cwd())

    assert target == tmp_path / ".codex" / "skills" / "campy-memory" / "SKILL.md"
    assert target.exists()
    assert "Campy Memory Skill" in target.read_text()


def test_packaged_legacy_memory_skill_copy_matches_canonical():
    canonical = Path("skills/sidequests-memory/SKILL.md").read_text()
    packaged = Path("campy/data/sidequests-memory/SKILL.md").read_text()

    assert packaged == canonical
