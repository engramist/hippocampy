"""
tests/test_daemon_start_stop.py — B364: `campy start`/`stop` on macOS.

Covers:
  1. `campy start`'s Darwin branch, when no plist has ever been generated for
     this install (load_plist() fails outright): generates one and retries,
     rather than reporting failure with no recovery path.
  2. The last-resort raw-subprocess fallback when launchd remains unusable
     even after plist generation.
  3. `unload_plist()`'s retry-before-reporting-failure fix for the
     `is_loaded()` race against launchd's own state update.
"""

from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from campy.cli.main import app
from campy.cli.launchd import unload_plist

runner = CliRunner()


def test_start_generates_plist_and_retries_when_none_exists():
    """B364: load_plist() failing (no plist yet) must trigger write_plist()
    + a retry, not an immediate failure report."""
    load_plist_calls = []

    def fake_load_plist():
        load_plist_calls.append(True)
        return len(load_plist_calls) >= 2  # fails first call, succeeds on retry

    with patch("platform.system", return_value="Darwin"), \
         patch("campy.cli.launchd.load_plist", side_effect=fake_load_plist), \
         patch("campy.cli.launchd.write_plist") as mock_write_plist:
        result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    assert len(load_plist_calls) == 2, "must retry load_plist() after generating a plist"
    mock_write_plist.assert_called_once()
    assert "started via launchd" in result.output


def test_start_falls_back_to_raw_subprocess_when_launchd_unusable():
    """B364: if load_plist() still fails after plist generation, fall back
    to a raw subprocess rather than leaving the daemon offline."""
    with patch("platform.system", return_value="Darwin"), \
         patch("campy.cli.launchd.load_plist", return_value=False), \
         patch("campy.cli.launchd.write_plist"), \
         patch("campy.cli.launchd._daemon_script", return_value="/fake/brain_daemon.py"), \
         patch("subprocess.Popen") as mock_popen:
        result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_popen.assert_called_once()
    args = mock_popen.call_args.args[0]
    assert "/fake/brain_daemon.py" in args
    assert "Brain Daemon started." in result.output


def test_unload_plist_retries_before_reporting_failure(tmp_path):
    """B364: is_loaded() returning True immediately after unload/remove --
    launchd's own state update lagging behind, not a real failure -- must
    not be reported as a failure if a later poll shows it did unload."""
    plist_path = tmp_path / "fake.plist"
    plist_path.write_text("<plist/>")

    is_loaded_results = iter([True, True, False])  # settles on the 3rd check

    with patch("campy.cli.launchd.subprocess.run") as mock_run, \
         patch("campy.cli.launchd.is_loaded", side_effect=lambda label: next(is_loaded_results)), \
         patch("campy.cli.launchd.time.sleep"):
        mock_run.return_value = MagicMock(returncode=1)  # `unload` itself "fails"
        result = unload_plist(label="test.label", plist_path=plist_path)

    assert result is True, "a delayed but real unload must not be reported as a failure"


def test_unload_plist_reports_real_failure(tmp_path):
    """B364: a genuinely still-loaded service after every retry is a real
    failure, not swallowed by the new retry logic."""
    nonexistent_plist = tmp_path / "does_not_exist.plist"

    with patch("campy.cli.launchd.subprocess.run") as mock_run, \
         patch("campy.cli.launchd.is_loaded", return_value=True), \
         patch("campy.cli.launchd.time.sleep"):
        mock_run.return_value = MagicMock(returncode=1)
        result = unload_plist(label="test.label", plist_path=nonexistent_plist)

    assert result is False
