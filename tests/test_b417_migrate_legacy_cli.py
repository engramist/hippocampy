"""tests/test_b417_migrate_legacy_cli.py — B417 item 3: `campy migrate-legacy` CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

kuzu = pytest.importorskip("kuzu", reason="needs the optional kuzu package")

from campy.cli.main import app


def _make_legacy_backup(path):
    db = kuzu.Database(str(path))
    conn = kuzu.Connection(db)
    conn.execute("CREATE NODE TABLE Concept(concept_id STRING, text_raw STRING, PRIMARY KEY(concept_id))")
    conn.execute("CREATE (c:Concept {concept_id: 'c1', text_raw: 'migrated via CLI'})")
    conn.close()


def test_command_is_registered():
    result = CliRunner().invoke(app, ["migrate-legacy", "--help"])
    assert result.exit_code == 0
    assert "kuzu" in result.output.lower()


def test_refuses_when_daemon_appears_running(tmp_path, monkeypatch):
    monkeypatch.setattr("campy.cli.main._daemon_is_running", lambda: True)
    result = CliRunner().invoke(app, ["migrate-legacy"])
    assert result.exit_code == 1
    assert "campy stop" in result.output


def test_no_backup_found_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr("campy.cli.main._daemon_is_running", lambda: False)
    monkeypatch.setattr("campy.paths.get_database_path", lambda: tmp_path / "brain.db")
    result = CliRunner().invoke(app, ["migrate-legacy"])
    assert result.exit_code == 0
    assert "no legacy backup" in result.output.lower()


def test_migrates_an_explicit_backup_file(tmp_path, monkeypatch):
    backup = tmp_path / "brain.db.kuzu-bak-20260101000000000000"
    _make_legacy_backup(backup)
    live_db = tmp_path / "live" / "brain.db"

    monkeypatch.setattr("campy.cli.main._daemon_is_running", lambda: False)
    monkeypatch.setattr("campy.paths.get_database_path", lambda: live_db)

    result = CliRunner().invoke(app, ["migrate-legacy", "--from", str(backup)])

    assert result.exit_code == 0, result.output
    assert "Migrated 1 node" in result.output
    assert live_db.is_dir(), "the live store must have been created"
    assert backup.exists(), "the backup file must NOT be deleted or modified"


def test_auto_discovers_the_newest_backup(tmp_path, monkeypatch):
    live_db = tmp_path / "brain.db"
    older = tmp_path / "brain.db.kuzu-bak-20260101000000000000"
    newer = tmp_path / "brain.db.kuzu-bak-20260601000000000000"
    _make_legacy_backup(older)
    _make_legacy_backup(newer)

    monkeypatch.setattr("campy.cli.main._daemon_is_running", lambda: False)
    monkeypatch.setattr("campy.paths.get_database_path", lambda: live_db)

    result = CliRunner().invoke(app, ["migrate-legacy"])

    assert result.exit_code == 0, result.output
    assert newer.name in result.output
