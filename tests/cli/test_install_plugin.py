import os
import subprocess
import sys

# Wide, colorless terminal so rich doesn't truncate option names with an
# ellipsis at the CI default of 80 columns.
_HELP_ENV = {**os.environ, "COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"}

def test_install_plugin_help():
    """campy install --help should mention --plugin flag."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "install", "--help"],
        capture_output=True, text=True, env=_HELP_ENV
    )
    assert "--plugin" in result.stdout
