# tests/cli/test_openclaw_adapter.py
"""Test OpenClaw adapter detection and registration."""
import json
import tempfile
from pathlib import Path


def test_detect_openclaw_exists():
    """detect_openclaw should be importable."""
    from campy.cli.detect import detect_openclaw
    assert callable(detect_openclaw)


def test_register_openclaw_importable():
    """register_openclaw should be importable."""
    from campy.cli.register_openclaw import register_openclaw
    assert callable(register_openclaw)


def test_register_openclaw_creates_config():
    """register_openclaw should create or update OpenClaw config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from campy.cli.register_openclaw import register_openclaw
        
        # Create a mock OpenClaw config directory and file
        config_dir = Path(tmpdir)
        config_file = config_dir / "openclaw.json"
        
        # Create initial config
        initial_config = {"mcpServers": {}}
        config_file.write_text(json.dumps(initial_config))
        
        # Register
        success = register_openclaw(str(config_dir))
        assert success is True
        
        # Verify config was updated
        updated = json.loads(config_file.read_text())
        assert "campy-memory" in updated["mcpServers"]
        assert updated["mcpServers"]["campy-memory"]["command"] == "python"


def test_register_openclaw_missing_config():
    """register_openclaw should handle missing config gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from campy.cli.register_openclaw import register_openclaw
        
        # Don't create a config file
        success = register_openclaw(str(tmpdir))
        assert success is False


def test_openclaw_in_setup_targets():
    """OpenClaw should be available as a setup target."""
    from campy.cli.main import setup
    import inspect
    
    source = inspect.getsource(setup)
    assert "openclaw" in source.lower()
