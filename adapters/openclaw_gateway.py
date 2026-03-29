"""
adapters/openclaw_gateway.py — OpenClaw Gateway Integration (LLM Workflow)

Implements the system prompt construction logic for OpenClaw sessions.
Uses a two-layer model (Always-On + Onboarding) to ensure the LLM
understands its role as a memory-augmented agent.
"""

from __future__ import annotations
import os
import subprocess
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Prompt Templates (Layer 1 + Layer 2)
# ---------------------------------------------------------------------------

LAYER_1_TEMPLATE = (
    "[SideQuests Brain: Memory active]\n"
    "Before answering questions about past decisions, architecture, or constraints:\n"
    "→ Call memory_recall to check the knowledge graph\n"
    "For stored facts: use memory_store\n"
    "For analogical reasoning: use memory_search_analogies\n"
    "Check memory_status to see what's been captured"
)

LAYER_2_ONBOARDING = (
    "SideQuests Brain is your persistent knowledge graph. One automatic duty:\n"
    "- notify_turn: After EVERY response, forward your output to SideQuests (session_id + role='assistant' + full text)\n"
    "  This is how the Brain learns what you've done. Response is instant, never blocks.\n\n"
    "Tools you control:\n"
    "- memory_recall(query): Retrieve relevant decisions/constraints before answering architecture questions\n"
    "- memory_search_analogies(query): Find similar problems from other projects/sessions\n"
    "- memory_store(role, content): Save custom facts or forward turns to the Brain\n"
    "Check memory_status for how much is captured."
)

# ---------------------------------------------------------------------------
# Git Context Detection
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str = ".") -> str:
    """Run a git command, return stdout stripped. Returns '' on failure."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""

def get_git_context() -> dict:
    """Return repo_root and git_branch for the current working directory."""
    repo_root = _run_git(["rev-parse", "--show-toplevel"])
    git_branch = _run_git(["branch", "--show-current"])
    return {
        "repo_root": repo_root,
        "git_branch": git_branch or "main",
        "workspace_path": os.getcwd()
    }

# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

async def build_openclaw_prompt(session_id: str, onboarded: bool = False, quest_info: dict = None) -> str:
    """
    Construct the full system prompt for an OpenClaw session.
    
    Args:
        session_id: Unique ID for the OpenClaw session.
        onboarded: If True, only inject Layer 1. If False, inject Layer 1 + Layer 2.
        quest_info: Optional dict with quest_name, branch, etc.
    """
    quest_header = "[SideQuest | Brain: ACTIVE]"
    if quest_info:
        name = quest_info.get("name", "Unknown Quest")
        branch = quest_info.get("branch", "main")
        quest_header = f"[SideQuest | Quest: {name} | Branch: {branch}]"
    
    prompt = f"{quest_header}\n{LAYER_1_TEMPLATE}"
    
    if not onboarded:
        prompt += f"\n\n--- ONBOARDING ---\n{LAYER_2_ONBOARDING}"
        
    return prompt
