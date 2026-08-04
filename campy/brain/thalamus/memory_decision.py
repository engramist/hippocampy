"""Memory decision helper for SideQuests.

Provides deterministic, transparent routing to recommend whether and how agents
should recall SideQuests memory for a given user prompt.

Related card: B235 - MCP Memory Decision Helper Tool
"""

from typing import Optional

# B254: mirrors the _TOKEN_LIMIT constant each adapter already declares
# (adapters/*/adapter.py, B18) - kept here as a separate copy rather than
# imported, since campy/brain/ must not depend on adapters/ (adapters wrap
# campy, not the other way around; see docs/ecosystem-rules.md). If an
# adapter's _TOKEN_LIMIT changes, update the matching entry here too.
_CLIENT_CONTEXT_WINDOWS = {
    "claude_code": 128000,
    "codex": 128000,
    "chatgpt_desktop": 128000,
    "claude_desktop": 200000,
    "gemini_cli": 1000000,
}

_DEFAULT_BUNDLE_TOKEN_BUDGET = 32000  # matches the 128k-class adapters' share below
_MAX_BUNDLE_TOKEN_BUDGET = 128000  # a memory bundle this large is already excessive
_BUNDLE_SHARE_OF_WINDOW = 0.25  # a bundle shouldn't crowd out the rest of the context


def _token_budget_for_client(client_name: Optional[str]) -> int:
    """Suggested compile_context token_budget, scaled to the requesting
    agent's context window - a quarter of the window, capped at
    _MAX_BUNDLE_TOKEN_BUDGET so a huge-context client (e.g. gemini_cli's
    1M-token window) doesn't get a quarter-million-token bundle
    recommendation. Falls back to the pre-B254 default for no/unknown
    client_name so existing callers see unchanged behavior.
    """
    if not client_name:
        return _DEFAULT_BUNDLE_TOKEN_BUDGET
    normalized = client_name.strip().lower().replace("-", "_")
    window = _CLIENT_CONTEXT_WINDOWS.get(normalized)
    if window is None:
        return _DEFAULT_BUNDLE_TOKEN_BUDGET
    return min(int(window * _BUNDLE_SHARE_OF_WINDOW), _MAX_BUNDLE_TOKEN_BUDGET)


def decide_memory_action(
    user_prompt: str,
    task_phase: str = "unknown",
    available_context_summary: Optional[str] = None,
    session_id: Optional[str] = None,
    client_name: Optional[str] = None,
) -> dict:
    """Recommend whether and how to recall SideQuests memory.

    Uses transparent lexical/phase-based rules to route user prompts to appropriate
    recall tools or recommend no recall.

    Args:
        user_prompt: The user's current message/question.
        task_phase: Optional phase hint (e.g., "planning", "debugging", "refactoring").
        available_context_summary: Optional summary of what's already in context.
        session_id: Optional session ID for potential future stateful hints.
        client_name: Optional client identifier (e.g., "codex", "claude-desktop").

    Returns:
        dict with keys:
            - should_recall (bool): Whether to call a recall tool
            - recommended_tool (str): Name of tool or "none"
            - query (str): Optimized query for the tool
            - reason (str): Explanation of the recommendation
            - confidence (float): 0.0-1.0 confidence in the recommendation
            - context_budget (str): "compact", "moderate", or "exhaustive"
            - anti_bloat_guidance (str): Guidance on using the result
    """

    # Normalize prompt to lowercase for matching
    prompt_lower = user_prompt.lower()

    # Rule 0 (Early): Multi-entity or broad context query -> compile_context (B252, B254)
    # Check this BEFORE context_status to avoid false matches on "full context"
    bundle_triggers = [
        "everything about",
        "full context",
        "brief me on",
        "what do we know about",
        "summary of",
        "overview of",
        "bundle",
        "compile",
    ]
    if any(trigger in prompt_lower for trigger in bundle_triggers) or _is_multi_entity(user_prompt):
        return {
            "should_recall": True,
            "recommended_tool": "compile_context",
            "query": _extract_key_entities(user_prompt),
            "reason": "Multi-entity query spanning decisions, constraints, and data.",
            "confidence": 0.85,
            "context_budget": "moderate",
            "anti_bloat_guidance": "Bundle is pre-compressed to token budget. Inject directly, do not re-summarize.",
            "suggested_params": {
                "token_budget": _token_budget_for_client(client_name),
                "include_tabular": True,
                "output_format": "claude_code",
            },
        }

    # Rule 1: Check context/token health (high priority)
    context_triggers = [
        "context",
        "token",
        "bloat",
        "memory usage",
        "how much space",
        "memory have i used",
    ]
    if any(trigger in prompt_lower for trigger in context_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "context_status",
            "query": "context window health",
            "reason": "User asks about context or token health.",
            "confidence": 0.92,
            "context_budget": "compact",
            "anti_bloat_guidance": "Show metrics and warnings; no recall needed.",
        }

    # Rule 1: ARC mechanics/scene graphs/world models (use word boundaries)
    if (" arc " in prompt_lower or prompt_lower.startswith("arc ") or
        "world model" in prompt_lower or "world-model" in prompt_lower or
        "mechanic" in prompt_lower or "transformation" in prompt_lower or
        "scene graph" in prompt_lower or "puzzle" in prompt_lower or
        "grid" in prompt_lower or "layout" in prompt_lower):
        # Prefer scene graph for spatial patterns
        if any(t in prompt_lower for t in ["scene", "spatial", "grid", "layout", "position"]):
            return {
                "should_recall": True,
                "recommended_tool": "recall_scene_graph_priors",
                "query": _extract_key_entities(user_prompt),
                "reason": "User asks about ARC scene graphs or spatial patterns.",
                "confidence": 0.74,
                "context_budget": "compact",
                "anti_bloat_guidance": "Show scene signature and success rate; explain variations.",
            }
        else:
            return {
                "should_recall": True,
                "recommended_tool": "recall_mechanic_priors",
                "query": _extract_key_entities(user_prompt),
                "reason": "User asks about ARC mechanics or world-model patterns.",
                "confidence": 0.76,
                "context_budget": "compact",
                "anti_bloat_guidance": "Show mechanic signature and confidence; cite evidence.",
            }

    # Rule 2: Prior decisions, architecture, constraints, preferences -> current_truth
    decision_triggers = [
        "what did we decide",
        "what decision",
        "prior decision",
        "constraint",
        "preference",
        "did we choose",
        "are the requirements",
        "what's the standard",
        "are the rules",
    ]
    if any(trigger in prompt_lower for trigger in decision_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "current_truth",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about prior decisions, architecture, constraints, or preferences.",
            "confidence": 0.86,
            "context_budget": "compact",
            "anti_bloat_guidance": "Use top 3 results; summarize, do not paste raw memory.",
        }

    # Rule 3: What changed -> diff_since
    change_triggers = [
        "what changed",
        "since last",
        "since the",
        "since when",
        "diff",
        "difference",
        "what's different",
        "other agent",
        "sub agent",
        "finished",
    ]
    if any(trigger in prompt_lower for trigger in change_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "diff_since",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about changes since a prior state or other session.",
            "confidence": 0.80,
            "context_budget": "compact",
            "anti_bloat_guidance": "Present structured diff; highlight key changes only.",
        }

    # Rule 4: Timeline/sequence/history -> reconstruct_timeline
    timeline_triggers = [
        "timeline",
        "sequence",
        "what happened",
        "in order",
        "step by step",
        "chronolog",
        "debug history",
        "trace",
        "walk me through",
        "how did we get here",
    ]
    if any(trigger in prompt_lower for trigger in timeline_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "reconstruct_timeline",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about sequence, timeline, or debugging history.",
            "confidence": 0.82,
            "context_budget": "compact",
            "anti_bloat_guidance": "Show chronological sequence with timestamps; omit verbose metadata.",
        }

    # Rule 5: Analogy/similar project -> analogical_search (checked before plan triggers)
    analogy_triggers = [
        "like before",
        "similar situation",
        "similar problem",
        "analogy",
        "analogous",
        "resembles",
        "reminds me",
        "we did this",
        "comparable",
    ]
    if any(trigger in prompt_lower for trigger in analogy_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "analogical_search",
            "query": _extract_key_entities(user_prompt),
            "reason": "User seeks analogies from similar past projects.",
            "confidence": 0.72,
            "context_budget": "compact",
            "anti_bloat_guidance": "Highlight key parallels; note differences from current situation.",
        }

    # Rule 6: Planning similar work -> recall_plans
    plan_triggers = [
        "plan",
        "implement",
        "backlog card",
        "how did we",
        "last time we",
        "before we",
        "strategy",
        "approach",
    ]
    if any(trigger in prompt_lower for trigger in plan_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "recall_plans",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about implementation strategies or similar prior work.",
            "confidence": 0.75,
            "context_budget": "compact",
            "anti_bloat_guidance": "Show plans with outcomes; cite lessons, do not repeat full details.",
        }

    # Rule 7: Procedures/workflows -> recall_procedures
    procedure_triggers = [
        "procedure",
        "workflow",
        "how do we usually",
        "standard",
        "process",
        "routine",
        "checklist",
        "steps",
    ]
    if any(trigger in prompt_lower for trigger in procedure_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "recall_procedures",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about reusable workflows or standard procedures.",
            "confidence": 0.83,
            "context_budget": "compact",
            "anti_bloat_guidance": "List key steps; reference variants without full expansion.",
        }

    # Rule 8: Lessons/learning -> recall_relevant_lessons
    lesson_triggers = [
        "lesson",
        "learned",
        "avoid",
        "mistake",
        "best practice",
        "should we",
        "don't",
        "pitfall",
    ]
    if any(trigger in prompt_lower for trigger in lesson_triggers):
        return {
            "should_recall": True,
            "recommended_tool": "recall_relevant_lessons",
            "query": _extract_key_entities(user_prompt),
            "reason": "User asks about lessons learned or cross-session learning.",
            "confidence": 0.78,
            "context_budget": "compact",
            "anti_bloat_guidance": "Present key lesson and its context; avoid lengthy narrative.",
        }

    # Default: No recall needed
    return {
        "should_recall": False,
        "recommended_tool": "none",
        "query": "",
        "reason": "User prompt does not match recall triggers; current context is likely sufficient.",
        "confidence": 0.80,
        "context_budget": "compact",
        "anti_bloat_guidance": "No recall needed. Continue with current context.",
    }


def _is_multi_entity(prompt: str) -> bool:
    """Heuristic: does this prompt reference multiple distinct topics?

    Counts proper nouns (capitalized words NOT at sentence start) or quoted terms.
    This avoids false positives from "What did we...", "How should we...", etc.
    """
    import re

    # Find capitalized words that are NOT at the start of a sentence
    # Pattern: not preceded by start-of-string or period/question mark
    # This filters out sentence-initial capitals like "What", "How"
    sentences = re.split(r'[.!?]\s+', prompt)
    capitalized_count = 0

    for sentence in sentences:
        # In each sentence, find capitalized words after the first word
        words = sentence.split()
        for i, word in enumerate(words[1:], 1):  # Skip first word (often capitalized)
            # Check if word is capitalized (not all caps)
            if word and word[0].isupper() and not word.isupper():
                capitalized_count += 1

    # Count quoted terms (more reliable multi-entity indicator)
    quoted = re.findall(r'"[^"]+"|\'[^\']+\'', prompt)

    # Multi-entity if 2+ proper nouns or 2+ quoted terms
    return capitalized_count >= 2 or len(quoted) >= 2


def _extract_key_entities(prompt: str) -> str:
    """Extract key entities from prompt to use as a recall query.

    This is a simple approach: take the first noun phrase or key term.
    Future versions can use NER or more sophisticated extraction.

    Args:
        prompt: User prompt text.

    Returns:
        Optimized query string for recall tool.
    """
    # Simple heuristic: take up to the first question mark or period, max 50 chars
    query = prompt.split("?")[0].split(".")[0].strip()
    if len(query) > 50:
        query = query[:47] + "..."
    return query


__all__ = [
    "decide_memory_action",
]
