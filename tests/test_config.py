"""
Tests for mcp_engine/config.py — T5 coverage.
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# load_config — explicit path
# ---------------------------------------------------------------------------

def test_load_config_explicit_path(tmp_path):
    """Explicit path is used when provided."""
    from mcp_engine.config import load_config
    cfg_file = tmp_path / "sidequests.toml"
    cfg_file.write_text('[llm]\nprovider = "ollama"\nmodel = "llama3.1:8b"\n')
    config = load_config(str(cfg_file))
    assert config["llm"]["provider"] == "ollama"
    assert config["_config_path"] == str(cfg_file)


def test_load_config_sets_config_path_key(tmp_path):
    """_config_path key is always set to the resolved file path."""
    from mcp_engine.config import load_config
    cfg_file = tmp_path / "sidequests.toml"
    cfg_file.write_text('[embeddings]\nmodel = "all-MiniLM-L6-v2"\n')
    config = load_config(str(cfg_file))
    assert "_config_path" in config
    assert str(cfg_file) == config["_config_path"]


def test_load_config_parses_nested_sections(tmp_path):
    """Multi-section TOML is fully parsed."""
    from mcp_engine.config import load_config
    cfg_file = tmp_path / "sidequests.toml"
    cfg_file.write_text(
        '[llm]\nprovider = "openai"\nmodel = "gpt-4o"\n\n'
        '[embeddings]\nmodel = "sentence-transformers/all-MiniLM-L6-v2"\n\n'
        '[pruning]\nsweep_interval_seconds = 120\narchive_threshold = 0.10\n'
    )
    config = load_config(str(cfg_file))
    assert config["llm"]["model"] == "gpt-4o"
    assert config["embeddings"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert config["pruning"]["sweep_interval_seconds"] == 120
    assert config["pruning"]["archive_threshold"] == pytest.approx(0.10)


def test_load_config_raises_when_not_found(tmp_path, monkeypatch):
    """FileNotFoundError raised when no config file exists anywhere."""
    from mcp_engine.config import load_config
    # Point cwd to empty dir; provide a nonexistent explicit path
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="sidequests.toml not found"):
        load_config(str(tmp_path / "nonexistent.toml"))


def test_load_config_cwd_fallback(tmp_path, monkeypatch):
    """Falls back to sidequests.toml in cwd when no explicit path given."""
    from mcp_engine.config import load_config
    cfg_file = tmp_path / "sidequests.toml"
    cfg_file.write_text('[llm]\nprovider = "ollama"\n')
    monkeypatch.chdir(tmp_path)
    config = load_config()   # no explicit path — should find cwd version
    assert config["llm"]["provider"] == "ollama"


def test_load_config_explicit_path_takes_priority(tmp_path, monkeypatch):
    """Explicit path wins over cwd sidequests.toml."""
    from mcp_engine.config import load_config
    cwd_cfg = tmp_path / "sidequests.toml"
    cwd_cfg.write_text('[llm]\nprovider = "ollama"\n')

    subdir = tmp_path / "sub"
    subdir.mkdir()
    explicit_cfg = subdir / "custom.toml"
    explicit_cfg.write_text('[llm]\nprovider = "openai"\n')

    monkeypatch.chdir(tmp_path)
    config = load_config(str(explicit_cfg))
    assert config["llm"]["provider"] == "openai"   # explicit wins
