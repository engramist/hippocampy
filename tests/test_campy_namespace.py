import subprocess
import sys
import os

def test_import_campy():
    import campy
    assert campy.__name__ == "campy"

def test_campy_paths():
    import campy.paths
    # Just verify it doesn't crash and has some expected attributes
    assert hasattr(campy.paths, "runtime_dir")
    rt_dir = campy.paths.runtime_dir()
    assert rt_dir is not None

def test_campy_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "HippoCampy AI Memory System CLI" in result.stdout

def test_campy_adapters_import():
    import campy.adapters.mcp_server
    assert hasattr(campy.adapters.mcp_server, "main")

def test_packaging_includes_campy():
    # This is a bit harder to test without building, but we can check if it's in the current dir
    assert os.path.exists("campy/__init__.py")
    assert os.path.exists("campy/cli/main.py")
    assert os.path.exists("campy/adapters/mcp_server.py")
