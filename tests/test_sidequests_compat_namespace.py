import subprocess
import sys
import os

def test_import_sidequests():
    import sidequests
    # It might be sidequests or campy depending on how it was imported, 
    # but the path should be in the sidequests dir or forwarding to campy
    assert "sidequests" in sidequests.__name__

def test_sidequests_paths():
    from sidequests.paths import runtime_dir
    rt_dir = runtime_dir()
    assert rt_dir is not None

def test_sidequests_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "sidequests.cli.main", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "HippoCampy AI Memory System CLI" in result.stdout

def test_sidequests_entrypoint():
    # Check if sidequests is in scripts (this tests the installed mode roughly)
    # We can just try to run it if it's in the path, but better to check pyproject.toml
    # for this test, we just check if the shim exists and works
    import sidequests.cli.main
    assert hasattr(sidequests.cli.main, "app")
