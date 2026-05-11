"""Test suite for SideQuests memory skill (B234).

Validates canonical memory usage policy as documented in skills/sidequests-memory/SKILL.md.
"""

import os
from pathlib import Path

from sidequests.cli.register import install_codex_memory_skill


def test_memory_skill_file_exists():
    """Verify the canonical skill file exists."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    assert os.path.exists(skill_path), f"Skill file not found at {skill_path}"
    
    with open(skill_path, "r") as f:
        content = f.read()
        assert len(content) > 500, "Skill file appears to be empty or too short"


def test_memory_skill_includes_core_sections():
    """Verify skill includes required sections."""
    skill_path = "skills/sidequests-memory/SKILL.md"
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
    skill_path = "skills/sidequests-memory/SKILL.md"
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
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    arc_tools = [
        "recall_mechanic_priors",
        "recall_scene_graph_priors",
    ]
    
    for tool in arc_tools:
        assert tool in content, f"ARC tool '{tool}' not mentioned in skill"


def test_memory_skill_includes_anti_bloat_rules():
    """Verify skill includes anti-bloat guidance."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    anti_bloat_keywords = [
        "bloat",
        "compact",
        "do not recall for every turn",
        "top 3 results",
        "summarize",
        "selective",
    ]
    
    for keyword in anti_bloat_keywords:
        assert keyword.lower() in content.lower(), \
            f"Anti-bloat guidance not found: '{keyword}'"


def test_memory_skill_includes_passive_capture():
    """Verify skill mentions passive capture behavior."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    passive_keywords = [
        "passive",
        "write",
        "always on",
        "continuously captures",
    ]
    
    for keyword in passive_keywords:
        assert keyword.lower() in content.lower(), \
            f"Passive capture not mentioned: '{keyword}'"


def test_memory_skill_includes_activity_indicator():
    """Verify skill mentions activity indicator for verification."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    # Check for activity indicator section
    assert "sidequests activity --follow" in content, \
        "Activity indicator command not found in skill"
    assert "Activity Indicator" in content or "activity" in content.lower(), \
        "Activity indicator section not found"


def test_memory_skill_includes_good_and_bad_examples():
    """Verify skill includes examples of good and bad recall usage."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    # Check for examples section
    assert "good" in content.lower() and "example" in content.lower(), \
        "Good examples not found"
    assert "bad" in content.lower() and "example" in content.lower(), \
        "Bad examples not found"


def test_memory_skill_includes_decision_tree():
    """Verify skill includes recall decision tree."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    # Check for decision tree patterns
    assert "Prior decision" in content or "prior decision" in content.lower(), \
        "Decision tree routing not found"
    assert "What kind of decision" in content or "what kind of decision" in content.lower(), \
        "Decision tree question not found"


def test_memory_skill_includes_failure_modes():
    """Verify skill documents failure modes and recovery."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    failure_keywords = [
        "Brain daemon is offline",
        "timed out",
        "wrong recall results",
        "context bloat",
        "workaround",
    ]
    
    found_failures = 0
    for keyword in failure_keywords:
        if keyword.lower() in content.lower():
            found_failures += 1
    
    assert found_failures >= 3, \
        f"Not enough failure modes documented (found {found_failures}, expected >= 3)"


def test_memory_skill_marked_as_canonical():
    """Verify skill is marked as canonical policy."""
    skill_path = "skills/sidequests-memory/SKILL.md"
    with open(skill_path, "r") as f:
        content = f.read()
    
    canonical_markers = [
        "canonical",
        "all agents",
        "universal",
        "shared",
    ]
    
    found_marker = False
    for marker in canonical_markers:
        if marker.lower() in content.lower():
            found_marker = True
            break
    
    assert found_marker, "Skill not marked as canonical/universal policy"


def test_install_codex_memory_skill_copies_to_codex_home(tmp_path, monkeypatch):
    """Codex registration can install the canonical policy as a local skill."""
    monkeypatch.setenv("HOME", str(tmp_path))
    target = install_codex_memory_skill(Path.cwd())

    assert target == tmp_path / ".codex" / "skills" / "sidequests-memory" / "SKILL.md"
    assert target.exists()
    assert "SideQuests Memory Skill" in target.read_text()


def test_packaged_memory_skill_copy_matches_canonical():
    canonical = Path("skills/sidequests-memory/SKILL.md").read_text()
    packaged = Path("sidequests/data/sidequests-memory/SKILL.md").read_text()

    assert packaged == canonical
