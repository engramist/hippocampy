from typer.testing import CliRunner

from campy.cli.main import app
from campy.cli.doctor import DoctorChecker


def test_doctor_command_is_registered():
    result = CliRunner().invoke(app, ["doctor", "--help"])

    assert result.exit_code == 0
    assert "repair" in result.output


def test_doctor_checker_records_python_version():
    checker = DoctorChecker()
    checker._check_python_version()

    assert checker.checks
    assert checker.checks[0][0] == "Python Version"


# --- B417: legacy Kùzu brain.db detection ----------------------------------

def test_check_database_flags_legacy_non_directory_file(tmp_path, monkeypatch):
    """If db_path exists but is a regular file (the pre-cutover Kùzu
    scenario), doctor must call it out by name rather than silently
    reporting 'exists' — even though OxigraphClient now self-heals this on
    next daemon start, the operator should know now, not be surprised."""
    legacy = tmp_path / "brain.db"
    legacy.write_bytes(b"legacy kuzu content")
    monkeypatch.setattr("campy.paths.get_database_path", lambda: legacy)

    checker = DoctorChecker()
    checker._check_database()

    name, passed, msg = checker.checks[0]
    assert name == "Database"
    assert passed is True, "self-healing on next start, not a hard failure"
    assert "legacy" in msg.lower()
    assert "kùzu" in msg.lower() or "kuzu" in msg.lower()


def test_check_database_flags_unmigrated_backup_alongside_a_healthy_store(tmp_path, monkeypatch):
    """After the daemon has auto-healed once, the live store is a real
    directory but a .kuzu-bak-* sibling holds unmigrated data — doctor
    should surface that so it isn't forgotten."""
    db_path = tmp_path / "brain.db"
    db_path.mkdir()
    backup = tmp_path / "brain.db.kuzu-bak-20260909120000000000"
    backup.write_bytes(b"legacy content")
    monkeypatch.setattr("campy.paths.get_database_path", lambda: db_path)

    checker = DoctorChecker()
    checker._check_database()

    name, passed, msg = checker.checks[0]
    assert name == "Database"
    assert passed is True
    assert "backup" in msg.lower() or "unmigrated" in msg.lower()


def test_check_database_normal_case_unaffected(tmp_path, monkeypatch):
    """A real directory store with no stray backups reports plainly, as before."""
    db_path = tmp_path / "brain.db"
    db_path.mkdir()
    monkeypatch.setattr("campy.paths.get_database_path", lambda: db_path)

    checker = DoctorChecker()
    checker._check_database()

    name, passed, msg = checker.checks[0]
    assert name == "Database"
    assert passed is True
    assert "exists" in msg.lower()
    assert "legacy" not in msg.lower()
    assert "backup" not in msg.lower()
