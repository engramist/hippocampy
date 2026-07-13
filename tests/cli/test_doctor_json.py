"""Test doctor --json output."""
import json
import os
import subprocess
import sys

# Wide, colorless terminal so rich doesn't truncate option names with an
# ellipsis at the CI default of 80 columns.
_HELP_ENV = {**os.environ, "COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"}


def test_doctor_json_flag_exists():
    """campy doctor should accept --json flag."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "doctor", "--help"],
        capture_output=True, text=True, env=_HELP_ENV
    )
    assert "--json" in result.stdout


def test_doctor_json_output_is_valid_json():
    """campy doctor --json should produce valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "doctor", "--json"],
        capture_output=True, text=True, timeout=30
    )
    # Should exit 0 or 1 but always produce JSON
    try:
        data = json.loads(result.stdout)
        assert "checks" in data
        assert isinstance(data["checks"], list)
    except json.JSONDecodeError:
        assert False, f"Invalid JSON output: {result.stdout[:200]}"
