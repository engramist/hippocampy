import json
import subprocess
from pathlib import Path

from campy.cli.register import (
    _strip_codex_adapter_path_tables,
    _upsert_codex_mcp_block,
    register_vscode,
)


def test_codex_mcp_upsert_is_idempotent():
    content = "[profile.main]\nmodel = \"gpt-5\"\n"
    once = _upsert_codex_mcp_block(content, "/venv/bin/python", "/repo/adapters/codex/adapter.py")
    twice = _upsert_codex_mcp_block(once, "/venv/bin/python", "/repo/adapters/codex/adapter.py")

    assert twice.count("[mcp_servers.campy]") == 1
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
    assert list(second["servers"]).count("campy") == 1


# ============================================================================
# Bootstrap Idempotency Tests (B237)
# ============================================================================


def test_bootstrap_dry_run_twice():
    """Running bootstrap --dry-run twice should succeed both times."""
    for _ in range(2):
        result = subprocess.run(
            ["bash", "scripts/bootstrap.sh", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0


def test_bootstrap_help_is_stable():
    """--help output should be consistent across runs."""
    results = []
    for _ in range(2):
        result = subprocess.run(
            ["bash", "scripts/bootstrap.sh", "--help"],
            capture_output=True, text=True, timeout=10
        )
        results.append(result.stdout)
    assert results[0] == results[1]


def test_bootstrap_does_not_delete_campy_dir():
    """Bootstrap should never contain rm -rf on .campy directory."""
    content = Path("scripts/bootstrap.sh").read_text()
    # Check that no line does rm -rf on the .campy directory
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            continue
        if "rm -rf" in line and (".campy" in line or "brain.db" in line):
            assert False, f"Dangerous delete: {line}"

