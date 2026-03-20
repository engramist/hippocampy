"""
Tests for B2 Cowork Plugin structure and content.

Validates the plugin directory structure, manifest schema, MCP config,
and skill file presence — ensuring the plugin is installable.
"""

import json
import pytest
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugin"


def test_plugin_directory_exists():
    """Plugin directory exists at repo root."""
    assert PLUGIN_DIR.exists(), f"Plugin directory not found at {PLUGIN_DIR}"
    assert PLUGIN_DIR.is_dir()


def test_plugin_manifest_exists():
    """plugin.json manifest exists."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    assert manifest.exists(), "Missing .claude-plugin/plugin.json"


def test_plugin_manifest_valid_json():
    """plugin.json is valid JSON with required fields."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text())
    assert "name" in data
    assert "version" in data
    assert "description" in data
    assert data["name"] == "sidequests-brain"


def test_plugin_manifest_has_author():
    """plugin.json has author field."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text())
    assert "author" in data
    assert "name" in data["author"]


def test_mcp_json_exists():
    """.mcp.json exists in plugin root."""
    mcp = PLUGIN_DIR / ".mcp.json"
    assert mcp.exists(), "Missing .mcp.json"


def test_mcp_json_valid():
    """.mcp.json is valid JSON with sidequests-brain server."""
    mcp = PLUGIN_DIR / ".mcp.json"
    data = json.loads(mcp.read_text())
    assert "mcpServers" in data
    assert "sidequests-brain" in data["mcpServers"]
    server = data["mcpServers"]["sidequests-brain"]
    assert "url" in server
    assert "127.0.0.1" in server["url"]
    assert "7799" in server["url"]


def test_mcp_json_uses_sse_endpoint():
    """.mcp.json points to the SSE endpoint."""
    mcp = PLUGIN_DIR / ".mcp.json"
    data = json.loads(mcp.read_text())
    url = data["mcpServers"]["sidequests-brain"]["url"]
    assert url.endswith("/sse"), f"Expected SSE endpoint, got {url}"


def test_skills_directory_exists():
    """skills/ directory exists."""
    skills = PLUGIN_DIR / "skills"
    assert skills.exists()
    assert skills.is_dir()


EXPECTED_SKILLS = [
    "memory-awareness",
    "recall",
    "quest-management",
    "status",
]


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_directory_exists(skill_name):
    """Each expected skill has a directory."""
    skill_dir = PLUGIN_DIR / "skills" / skill_name
    assert skill_dir.exists(), f"Missing skill directory: {skill_name}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_skill_md(skill_name):
    """Each skill directory contains SKILL.md."""
    skill_file = PLUGIN_DIR / "skills" / skill_name / "SKILL.md"
    assert skill_file.exists(), f"Missing SKILL.md in {skill_name}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_md_not_empty(skill_name):
    """Each SKILL.md has meaningful content (>100 chars)."""
    skill_file = PLUGIN_DIR / "skills" / skill_name / "SKILL.md"
    content = skill_file.read_text()
    assert len(content) > 100, f"SKILL.md in {skill_name} is too short ({len(content)} chars)"


def test_skill_memory_awareness_mentions_notify_turn():
    """memory-awareness skill teaches Claude about notify_turn."""
    content = (PLUGIN_DIR / "skills" / "memory-awareness" / "SKILL.md").read_text()
    assert "notify_turn" in content


def test_skill_recall_mentions_current_truth():
    """recall skill teaches Claude about current_truth."""
    content = (PLUGIN_DIR / "skills" / "recall" / "SKILL.md").read_text()
    assert "current_truth" in content


def test_skill_quest_management_mentions_branch_quest():
    """quest-management skill teaches Claude about branch_quest."""
    content = (PLUGIN_DIR / "skills" / "quest-management" / "SKILL.md").read_text()
    assert "branch_quest" in content


def test_skill_status_mentions_context_status():
    """status skill teaches Claude about context_status."""
    content = (PLUGIN_DIR / "skills" / "status" / "SKILL.md").read_text()
    assert "context_status" in content


def test_readme_exists():
    """README.md exists in plugin root."""
    readme = PLUGIN_DIR / "README.md"
    assert readme.exists()


def test_readme_mentions_install():
    """README has installation instructions."""
    content = (PLUGIN_DIR / "README.md").read_text()
    assert "install" in content.lower()
    assert "sidequests" in content.lower()
