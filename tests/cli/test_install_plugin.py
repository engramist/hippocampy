import subprocess
import sys

def test_install_plugin_help():
    """campy install --help should mention --plugin flag."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "install", "--help"],
        capture_output=True, text=True
    )
    assert "--plugin" in result.stdout
