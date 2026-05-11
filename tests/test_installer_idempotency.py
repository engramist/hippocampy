import json
from pathlib import Path

from sidequests.cli.register import (
    _strip_codex_adapter_path_tables,
    _upsert_codex_mcp_block,
    register_vscode,
)


def test_codex_mcp_upsert_is_idempotent():
    content = "[profile.main]\nmodel = \"gpt-5\"\n"
    once = _upsert_codex_mcp_block(content, "/venv/bin/python", "/repo/adapters/codex/adapter.py")
    twice = _upsert_codex_mcp_block(once, "/venv/bin/python", "/repo/adapters/codex/adapter.py")

    assert twice.count("[mcp_servers.sidequests]") == 1
    assert twice == once


def test_codex_strips_duplicate_malformed_adapter_tables(tmp_path):
    adapter = tmp_path / "repo" / "adapters" / "codex" / "adapter.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("# adapter")
    malformed = f'["{adapter.resolve()}"]\n["{adapter.resolve()}"]\n[mcp_servers]\n'

    cleaned = _strip_codex_adapter_path_tables(malformed, str(adapter))

    assert f'["{adapter.resolve()}"]' not in cleaned
    assert "[mcp_servers]" in cleaned


def test_vscode_registration_is_idempotent(tmp_path):
    adapter = tmp_path / "repo" / "adapters" / "codex" / "adapter.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("# adapter")
    config_path = tmp_path / "Code" / "User" / "mcp.json"

    assert register_vscode(str(adapter), str(config_path)) is True
    first = json.loads(config_path.read_text())
    assert register_vscode(str(adapter), str(config_path)) is True
    second = json.loads(config_path.read_text())

    assert second == first
    assert list(second["servers"]).count("sidequests") == 1

