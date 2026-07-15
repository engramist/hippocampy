# tests/adapters/test_claude_code_setup.py
"""Regression tests for project-root .mcp.json handling in `campy setup`.

The project-root .mcp.json is git-tracked and may contain server entries
campy did not create — other MCP servers, or a hand-authored campy entry
pointing at the HTTP daemon. Registration must merge into the existing
file, never overwrite it (regression: setup/install flows twice reset the
file to an empty/replaced mcpServers map, wiping the user's campy entry).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.claude_code import setup as S


USER_HTTP_ENTRY = {"type": "http", "url": "http://127.0.0.1:7799/mcp"}


class TestWriteMcpJsonMerge:
    def test_creates_entry_when_file_missing(self, tmp_path):
        S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        entry = data["mcpServers"]["campy"]
        assert entry["args"] == ["-m", "campy.adapters.mcp_server"]

    def test_preserves_other_server_entries(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"serena": {"command": "uvx", "args": ["serena"]}}
        }))
        S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["serena"] == {"command": "uvx", "args": ["serena"]}
        assert "campy" in data["mcpServers"]

    def test_preserves_user_managed_campy_http_entry(self, tmp_path):
        original = {"mcpServers": {"campy": USER_HTTP_ENTRY}}
        (tmp_path / ".mcp.json").write_text(json.dumps(original))
        S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["campy"] == USER_HTTP_ENTRY

    def test_refreshes_campy_created_stdio_entry(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "campy": {
                    "command": "/stale/venv/bin/python",
                    "args": ["-m", "campy.adapters.mcp_server"],
                },
                "serena": {"command": "uvx", "args": ["serena"]},
            }
        }))
        S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["campy"]["command"] != "/stale/venv/bin/python"
        assert data["mcpServers"]["campy"]["args"] == ["-m", "campy.adapters.mcp_server"]
        assert "serena" in data["mcpServers"]

    def test_preserves_unknown_top_level_keys(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {},
            "somethingElse": {"a": 1},
        }))
        S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["somethingElse"] == {"a": 1}
        assert "campy" in data["mcpServers"]

    def test_leaves_corrupt_json_untouched(self, tmp_path):
        (tmp_path / ".mcp.json").write_text("not valid json {{{")
        S._write_mcp_json(tmp_path)
        assert (tmp_path / ".mcp.json").read_text() == "not valid json {{{"

    def test_idempotent_reruns_never_empty_the_file(self, tmp_path):
        """Regression: repeated setup runs must not converge to {"mcpServers": {}}."""
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"campy": USER_HTTP_ENTRY}
        }))
        for _ in range(3):
            S._write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"] == {"campy": USER_HTTP_ENTRY}


class TestIsCampyCreatedEntry:
    def test_module_stdio_entry_is_campy_created(self):
        assert S._is_campy_created_entry(
            {"command": "python", "args": ["-m", "campy.adapters.mcp_server"]}
        )

    def test_http_entry_is_not_campy_created(self):
        assert not S._is_campy_created_entry(USER_HTTP_ENTRY)

    def test_non_dict_is_not_campy_created(self):
        assert not S._is_campy_created_entry("http://127.0.0.1:7799/mcp")
