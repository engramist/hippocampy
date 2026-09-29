"""CAMPY_HOME relocates all runtime state, with no fallback to the user's
personal ~/.campy or ~/.sidequests (campy-benchmarks' isolated mode runs a
throwaway daemon this way; any leak would read or write personal memory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from campy import paths
from campy.brain.brainstem import activity_log
from campy.brain.brainstem.config import load_config
from campy.brain.hippocampus.graph import vector_store


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A HOME that already has personal state in both runtime dirs."""
    home = tmp_path / "home"
    for d in (".campy", ".sidequests"):
        (home / d).mkdir(parents=True)
        (home / d / "config.toml").write_text('[llm]\nmodel = "personal"\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CAMPY_HOME", raising=False)
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    return home


@pytest.fixture
def isolated(tmp_path, monkeypatch, fake_home):
    iso = tmp_path / "iso"
    monkeypatch.setenv("CAMPY_HOME", str(iso))
    return iso


def test_runtime_dir_uses_campy_home_and_creates_it(isolated):
    assert paths.runtime_dir() == isolated
    assert isolated.is_dir()


def test_campy_home_skips_legacy_fallback(isolated, fake_home):
    # ~/.sidequests exists; without the override a missing ~/.campy would
    # route there. With CAMPY_HOME it must not.
    (fake_home / ".campy" / "config.toml").unlink()
    (fake_home / ".campy").rmdir()
    assert paths.runtime_dir() == isolated


def test_all_runtime_paths_follow_campy_home(isolated):
    for p in (
        paths.get_daemon_socket_path(),
        paths.get_database_path(),
        paths.get_workspace_root(),
        paths.get_activity_log_path(),
        paths.get_daemon_log_path(),
        paths.get_config_path(),
        paths.primary_runtime_dir(),
        vector_store._default_db_path(),
        activity_log._default_activity_log(),
    ):
        assert p == isolated or isolated in p.parents, p


def test_config_loads_from_campy_home_not_personal(isolated):
    isolated.mkdir()
    (isolated / "config.toml").write_text('[llm]\nmodel = "isolated"\n')
    cfg = load_config()
    assert cfg["llm"]["model"] == "isolated"
    assert Path(cfg["_config_path"]) == isolated / "config.toml"


def test_config_never_falls_back_to_personal_under_campy_home(isolated):
    with pytest.raises(FileNotFoundError):
        load_config()


def test_default_behaviour_unchanged_without_campy_home(fake_home):
    assert paths.runtime_dir() == fake_home / ".campy"
    assert vector_store._default_db_path() == fake_home / ".campy" / "vectors.db"
    assert load_config()["llm"]["model"] == "personal"
