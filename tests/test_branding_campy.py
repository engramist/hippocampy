from pathlib import Path

from typer.testing import CliRunner

from campy.branding import PRODUCT_NAME, PRIMARY_CLI, LEGACY_CLI
from campy.cli.main import app
from campy.paths import runtime_dir


def test_cli_help_uses_campy_branding():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert PRODUCT_NAME in result.output


def test_runtime_dir_prefers_campy_for_fresh_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert runtime_dir() == tmp_path / ".campy"
    assert (tmp_path / ".campy").exists()


def test_runtime_dir_preserves_legacy_sidequests_home(tmp_path, monkeypatch):
    legacy = tmp_path / ".sidequests"
    legacy.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert runtime_dir() == legacy


def test_cli_alias_names_are_documented():
    assert PRIMARY_CLI == "campy"
    assert LEGACY_CLI == "sidequests"
