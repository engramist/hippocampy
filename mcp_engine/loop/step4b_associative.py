"""
Step 4b — Associative Pattern Check (Anticipatory Engine, Online Mode)

Named IP Claims:
  - Prospective Memory: auto-discovery of trigger bindings from graph state
  - Associative Priming: embedding similarity gates trigger creation

Runs after Step 4's confidence gate, before Step 5's candidate retrieval.
When the current message contains error/failure signals, checks embedding
similarity against stored Lessons and Procedures. If similarity exceeds
threshold, auto-binds trigger metadata to the matched node.

Cost model: near-zero — vector search queries only, no LLM calls.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# Similarity threshold for auto-binding triggers.
# Must be high enough to avoid false positives (bad triggers waste context
# window), but low enough to catch genuine matches. 0.65 is conservative
# for all-MiniLM-L6-v2 (384-dim) — typical true matches score 0.70-0.85.
TRIGGER_SIMILARITY_THRESHOLD = 0.65

# Maximum number of trigger bindings created per message to avoid runaway
# writes on noisy inputs.
MAX_BINDINGS_PER_MESSAGE = 3

# Error/failure indicators — reuse step4_pattern.py signals plus shell-specific patterns.
_ERROR_INDICATORS = [
    r"\bfailed\b", r"\berror\b", r"\bexception\b", r"\btraceback\b",
    r"\bcommand not found\b", r"\bpermission denied\b", r"\btimeout\b",
    r"\bsegmentation fault\b", r"\bcore dumped\b", r"\bkilled\b",
    r"\bno such file\b", r"\bconnection refused\b", r"\bdenied\b",
    r"\bexpired\b", r"\binvalid\b", r"\bcannot\b", r"\bunable to\b",
    r"\bnot found\b", r"\bfatal\b",
    # Step 4 failure signals
    r"\bthat broke\b", r"\brevert\b", r"\bundo\b", r"\brollback\b",
    r"\btry again\b", r"\bwrong approach\b", r"\bstart over\b",
]

# Action indicators — significant operations worth matching against procedures.
_ACTION_INDICATORS = [
    r"\bdocker\b", r"\bkubectl\b", r"\baws\b", r"\bgit push\b",
    r"\bdeploy\b", r"\bmigrat", r"\bbuild\b", r"\brelease\b",
    r"\binstall\b", r"\bconfigure\b", r"\bsetup\b",
]


def _has_signal(text: str) -> str | None:
    """Check if text contains error or action signals. Returns signal type or None."""
    text_lower = text.lower()
    for pat in _ERROR_INDICATORS:
        if re.search(pat, text_lower):
            return "error"
    for pat in _ACTION_INDICATORS:
        if re.search(pat, text_lower):
            return "action"
    return None


async def check_associative_triggers(
    entity_text: str,
    entity_vector: list[float],
    full_message: str,
    db,
    config: dict,
) -> dict:
    """
    Check if incoming entity matches stored Lessons/Procedures that lack
    trigger metadata. If so, auto-bind trigger patterns.

    Args:
        entity_text: The entity string being processed
        entity_vector: Pre-computed embedding vector (from Step 2)
        full_message: Full message text for signal detection
        db: KuzuClient instance
        config: Campy config dict

    Returns:
        {
            "signal_type": "error"|"action"|None,
            "lessons_matched": int,
            "procedures_matched": int,
            "triggers_bound": int,
        }
    """
    result = {
        "signal_type": None,
        "lessons_matched": 0,
        "procedures_matched": 0,
        "triggers_bound": 0,
    }

    # Gate 1: Does the message contain an error/action signal?
    signal_type = _has_signal(full_message)
    if not signal_type:
        return result
    result["signal_type"] = signal_type

    # Gate 2: Do we have a vector to search with?
    if not entity_vector:
        return result

    similarity_threshold = config.get("anticipatory", {}).get(
        "similarity_threshold", TRIGGER_SIMILARITY_THRESHOLD
    )
    max_bindings = config.get("anticipatory", {}).get(
        "max_bindings_per_message", MAX_BINDINGS_PER_MESSAGE
    )

    bindings_created = 0

    # --- Check Lessons ---
    try:
        lesson_rows = db.vector_search(
            "Lesson", "lesson_emb_idx", entity_vector, 5
        )
        for row in lesson_rows:
            if bindings_created >= max_bindings:
                break
            node = row.get("node", {})
            score = row.get("score", 0.0)
            if score < similarity_threshold:
                continue
            if node.get("archived"):
                continue
            # Skip if trigger already bound
            existing_pattern = node.get("trigger_pattern") or ""
            if existing_pattern.strip():
                result["lessons_matched"] += 1
                continue

            # Auto-bind trigger metadata
            lesson_id = node.get("lesson_id")
            if not lesson_id:
                continue

            # Build trigger pattern from the entity text — escape regex
            # special chars, use case-insensitive word boundary match
            trigger_pattern = _build_trigger_pattern(entity_text)
            hook_type = "PostToolUse" if signal_type == "error" else "PreToolUse"

            try:
                await db.execute_write(
                    "MATCH (l:Lesson {lesson_id: $lid}) "
                    "SET l.trigger_pattern = $pattern, "
                    "    l.trigger_hook_type = $hook_type, "
                    "    l.trigger_tool = $tool, "
                    "    l.trigger_project_scope = $scope",
                    {
                        "lid": lesson_id,
                        "pattern": trigger_pattern,
                        "hook_type": hook_type,
                        "tool": "Bash",  # Default to Bash; most error/action patterns are CLI
                        "scope": "",      # All projects
                    },
                )
                bindings_created += 1
                result["lessons_matched"] += 1
                _logger.info(
                    "[Step4b] Auto-bound trigger to Lesson %s: pattern=%r hook=%s",
                    lesson_id[:8], trigger_pattern, hook_type,
                )
            except Exception as e:
                _logger.warning(
                    "[Step4b] Failed to bind trigger to Lesson %s: %s",
                    lesson_id[:8], e,
                )

    except Exception as e:
        _logger.debug("[Step4b] Lesson vector search failed: %s", e)

    # --- Check Procedures ---
    try:
        proc_rows = db.vector_search(
            "Procedure", "procedure_emb_idx", entity_vector, 3
        )
        for row in proc_rows:
            if bindings_created >= max_bindings:
                break
            node = row.get("node", {})
            score = row.get("score", 0.0)
            if score < similarity_threshold:
                continue
            if node.get("archived"):
                continue
            existing_pattern = node.get("trigger_pattern") or ""
            if existing_pattern.strip():
                result["procedures_matched"] += 1
                continue

            procedure_id = node.get("procedure_id")
            if not procedure_id:
                continue

            trigger_pattern = _build_trigger_pattern(entity_text)
            # Procedures are PreToolUse — warn before doing something
            hook_type = "PreToolUse"

            try:
                await db.execute_write(
                    "MATCH (p:Procedure {procedure_id: $pid}) "
                    "SET p.trigger_pattern = $pattern, "
                    "    p.trigger_hook_type = $hook_type, "
                    "    p.trigger_tool = $tool, "
                    "    p.trigger_project_scope = $scope",
                    {
                        "pid": procedure_id,
                        "pattern": trigger_pattern,
                        "hook_type": hook_type,
                        "tool": "",       # Match all tools for procedures
                        "scope": "",
                    },
                )
                bindings_created += 1
                result["procedures_matched"] += 1
                _logger.info(
                    "[Step4b] Auto-bound trigger to Procedure %s: pattern=%r",
                    procedure_id[:8], trigger_pattern,
                )
            except Exception as e:
                _logger.warning(
                    "[Step4b] Failed to bind trigger to Procedure %s: %s",
                    procedure_id[:8], e,
                )

    except Exception as e:
        _logger.debug("[Step4b] Procedure vector search failed: %s", e)

    result["triggers_bound"] = bindings_created
    return result


def _build_trigger_pattern(entity_text: str) -> str:
    """
    Build a regex trigger pattern from entity text.

    Strategy: extract key terms (2+ chars, non-stopword) and join with
    regex OR. This produces patterns like "docker|container|OAUTH" that
    will match future tool inputs containing any of those terms.
    """
    _STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "and", "but", "or", "nor", "not",
        "so", "if", "this", "that", "these", "those", "it", "its",
        "my", "your", "his", "her", "our", "their", "what", "which",
        "who", "when", "where", "why", "how", "all", "each", "every",
        "both", "few", "more", "most", "other", "some", "such", "no",
        "only", "own", "same", "than", "too", "very", "just", "because",
        "about", "up",
    }
    # Split on non-alphanumeric, keep terms 3+ chars, skip stopwords
    terms = []
    for word in re.split(r"[^a-zA-Z0-9_-]+", entity_text):
        if len(word) >= 3 and word.lower() not in _STOPWORDS:
            terms.append(re.escape(word))
    if not terms:
        # Fallback: use the whole entity text, escaped
        return re.escape(entity_text)
    # Cap at 5 terms to keep the pattern focused
    return "|".join(terms[:5])
