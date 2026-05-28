"""
tests/test_junk_entity_filter.py — Coverage for B34 junk entity filter.

Validates that _is_junk_entity() correctly rejects markdown artifacts,
prepositional fragments, snake_case/camelCase identifiers, generic words,
and other noise — while passing real concepts through.
"""

import pytest
from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity


# ---------------------------------------------------------------------------
# Real concepts — must NOT be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "SideQuests Brain",
    "PostgreSQL",
    "Redis",
    "decision",
    "KV store",
    "Kùzu",
    "HNSW index",
    "Claude Code",
    "OpenAI",
    "semantic routing",
    "Anthropic",
    "Codex",
    "MCP protocol",
    "provisional patent",
])
def test_real_concepts_pass(text):
    assert not _is_junk_entity(text), f"Should not filter real concept: {text!r}"


# ---------------------------------------------------------------------------
# B34: Markdown headings — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "### Open Loops",
    "## Decisions",
    "# Project",
    "#tag",
    "#### Sub-section",
])
def test_markdown_headings_filtered(text):
    assert _is_junk_entity(text), f"Should filter markdown heading: {text!r}"


# ---------------------------------------------------------------------------
# B34: Markdown bold markers — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Project Setup:**",
    "**Important**",
    "Result: **success**",
    "note:**",
])
def test_markdown_bold_filtered(text):
    assert _is_junk_entity(text), f"Should filter markdown bold artifact: {text!r}"


# ---------------------------------------------------------------------------
# B34: Prepositional fragments — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "to persist summaries",
    "for the database",
    "with the Brain",
    "from the session",
    "by the agent",
    "in the graph",
    "on the node",
    "at the endpoint",
    "of the quest",
])
def test_prepositional_fragments_filtered(text):
    assert _is_junk_entity(text), f"Should filter prepositional fragment: {text!r}"


# ---------------------------------------------------------------------------
# B34: snake_case code identifiers — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "last_loop_summary",
    "config_path",
    "session_id",
    "brain_daemon",
    "routing_method",
    "pathway_strength",
    "confidence_low",
    "embedding_model",
])
def test_snake_case_filtered(text):
    assert _is_junk_entity(text), f"Should filter snake_case identifier: {text!r}"


# ---------------------------------------------------------------------------
# B34: camelCase code identifiers — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "questId",
    "loopSummary",
    "sessionId",
    "routingMethod",
    "brainDaemon",
])
def test_camelcase_filtered(text):
    assert _is_junk_entity(text), f"Should filter camelCase identifier: {text!r}"


# ---------------------------------------------------------------------------
# B34: Generic single words — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "constraints",
    "decisions",
    "requirements",
    "sessions",
    "quests",
    "routes",
    "config",
    "status",
    "data",
    "items",
    "results",
    "options",
    "settings",
    "parameters",
])
def test_generic_words_filtered(text):
    assert _is_junk_entity(text), f"Should filter generic word: {text!r}"


# ---------------------------------------------------------------------------
# B34: Too-short single words — must be filtered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ab",
    "x",
    "id",
])
def test_too_short_filtered(text):
    assert _is_junk_entity(text), f"Should filter too-short word: {text!r}"


# ---------------------------------------------------------------------------
# Pre-existing junk filters (regression)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "",
    "   ",
    "0.92",
    "384",
    "18",
    "─────",
    "╮",
    "3f4e9a1b2c3d4e5f6a7b8c9d0e1f2a3b",  # hex hash
    "first",
    "second",
    "3rd",
    "notify_turn",
    "current_truth",
    "mainquest",
    "\n",
])
def test_preexisting_junk_filtered(text):
    assert _is_junk_entity(text), f"Should filter pre-existing junk: {text!r}"
