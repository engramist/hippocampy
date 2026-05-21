# tests/adapters/test_hermes_adapter.py
"""Test Hermes agent adapter."""
import asyncio


def test_hermes_adapter_importable():
    """HermesAdapter should be importable."""
    from adapters.hermes.adapter import HermesAdapter
    assert HermesAdapter is not None


def test_hermes_get_adapter_factory():
    """get_adapter factory should work."""
    from adapters.hermes.adapter import get_adapter
    
    adapter = get_adapter({
        "session_id": "test-session",
        "memory_url": "http://127.0.0.1:7799"
    })
    assert adapter is not None
    assert adapter._session_id == "test-session"


def test_hermes_adapter_initialization():
    """HermesAdapter should initialize properly."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter(memory_url="http://localhost:9999")
    assert adapter.memory_url == "http://localhost:9999"
    assert adapter.name == "hermes-campy"
    assert adapter.version == "0.1.0"


def test_hermes_adapter_configure():
    """Adapter.configure should accept config."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter()
    config = {"session_id": "custom-session"}
    success = adapter.configure(config)
    
    assert success is True
    assert adapter._session_id == "custom-session"


def test_hermes_adapter_health_check():
    """Adapter.health_check should return bool."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter()
    result = adapter.health_check()
    assert isinstance(result, bool)
    # If daemon not running, result will be False, which is OK for this test


def test_hermes_detect_function():
    """detect_hermes should be available."""
    from campy.cli.detect import detect_hermes
    assert callable(detect_hermes)


def test_hermes_register_function():
    """register_hermes should be available."""
    from campy.cli.register import register_hermes
    assert callable(register_hermes)


def test_hermes_in_setup_targets():
    """Hermes should be available as a setup target."""
    from campy.cli.main import setup
    import inspect
    
    source = inspect.getsource(setup)
    assert "hermes" in source.lower()


def test_hermes_readme_exists():
    """Hermes README should exist."""
    from pathlib import Path
    
    readme = Path(__file__).parent.parent.parent / "adapters" / "hermes" / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "HermesAdapter" in content or "Hermes" in content
