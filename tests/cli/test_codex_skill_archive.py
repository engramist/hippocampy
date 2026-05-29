from pathlib import Path

from campy.cli.plugin_installer import find_plugin_dir, install_codex_plugin


def test_install_codex_plugin_archives_legacy_process_skills(monkeypatch, tmp_path):
    """Codex install should archive known non-Campy duplicate process skills."""
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".codex" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    # Simulate previously installed non-Campy process skills.
    for name in ("diagnose", "grill-me", "handoff", "tdd"):
        skill_dir = skills_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"name: {name}\n")

    plugin_dir = find_plugin_dir()
    assert plugin_dir is not None
    assert install_codex_plugin(plugin_dir) is True

    archive_root = skills_root / "_archived_by_campy"
    stamp_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert stamp_dirs, "expected timestamped archive folder"
    archived_dir = stamp_dirs[0]

    # Legacy duplicates should be moved out of top-level skills directory.
    assert not (skills_root / "grill-me").exists()
    for name in ("diagnose", "grill-me", "handoff", "tdd"):
        assert (archived_dir / name / "SKILL.md").exists()

    # Campy skills should still be installed in top-level skills directory.
    assert (skills_root / "campy-grill" / "SKILL.md").exists()
    assert (skills_root / "campy-diagnose" / "SKILL.md").exists()
    assert (skills_root / "campy-handoff" / "SKILL.md").exists()
    assert (skills_root / "campy-tdd" / "SKILL.md").exists()
    assert "name: campy-grill" in (skills_root / "campy-grill" / "SKILL.md").read_text()
    assert "name: campy-diagnose" in (skills_root / "campy-diagnose" / "SKILL.md").read_text()
    assert "name: campy-handoff" in (skills_root / "campy-handoff" / "SKILL.md").read_text()
    assert "name: campy-tdd" in (skills_root / "campy-tdd" / "SKILL.md").read_text()
