"""Test suite for Campy memory skill (B246).

Validates canonical memory usage policy as documented in skills/campy-memory/SKILL.md.
"""

import os
from pathlib import Path

from campy.cli.register import install_codex_memory_skill


def test_memory_skill_file_exists():
    """Verify the canonical skill file exists."""
    skill_path = "skills/campy-memory/SKILL.md"
    assert os.path.exists(skill_path), f"Skill file not found at {skill_path}"
    
    with open(skill_path, "r") as f:
        content = f.read()
        assert len(content) > 500, "Skill file appears to be empty or too short"


def test_memory_skill_includes_core_sections():
    """Verify skill includes required sections."""
    skill_path = "skills/campy-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    required_sections = [
        "Purpose",
        "Core Rule",
        "Write vs Recall",
        "Recall Decision Tree",
        "Tool Map",
        "Anti-Bloat Rules",
        "Examples",
        "Activity Indicator",
        "Failure Modes",
    ]
    
    for section in required_sections:
        assert section in content, f"Section '{section}' not found in skill"


def test_memory_skill_mentions_core_tools():
    """Verify skill mentions all core recall tools."""
    skill_path = "skills/campy-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    core_tools = [
        "current_truth",
        "diff_since",
        "reconstruct_timeline",
        "recall_plans",
        "recall_procedures",
        "recall_relevant_lessons",
        "analogical_search",
        "memory_decision",
        "context_status",
    ]
    
    for tool in core_tools:
        assert tool in content, f"Tool '{tool}' not mentioned in skill"


def test_memory_skill_mentions_arc_tools():
    """Verify skill mentions ARC recall tools."""
    skill_path = "skills/campy-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    arc_tools = [
        "recall_mechanic_priors",
        "recall_scene_graph_priors",
    ]
    
    for tool in arc_tools:
        assert tool in content, f"ARC tool '{tool}' not mentioned in skill"


def test_memory_skill_mentions_campy():
    """Verify skill mentions Campy/HippoCampy."""
    skill_path = "skills/campy-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    assert "Campy" in content
    assert "HippoCampy" in content


def test_memory_skill_activity_command():
    """Verify skill mentions campy activity command."""
    skill_path = "skills/campy-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    assert "campy activity --follow" in content


def test_packaged_memory_skill_copy_matches_canonical():
    canonical = Path("skills/campy-memory/SKILL.md").read_text()
    packaged = Path("campy/data/campy-memory/SKILL.md").read_text()

    assert packaged == canonical
