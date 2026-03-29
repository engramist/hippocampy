"""
Tests for M8 Cross-Quest Analogical Reasoning.

Run with: python3 -m pytest tests/test_analogical.py -v
"""

from __future__ import annotations
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# _get_quest_for_artifact
# ---------------------------------------------------------------------------

def test_get_quest_for_artifact_returns_empty_when_no_chain():
    from mcp_engine.analogical import _get_quest_for_artifact

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, q, p=None): return EmptyResult()

    result = _get_quest_for_artifact(MockDB(), "Decision", "decision_id", "did1")
    assert result == {"quest_id": "", "quest_name": ""}


def test_get_quest_for_artifact_returns_quest_when_chain_exists():
    from mcp_engine.analogical import _get_quest_for_artifact

    class ChainResult:
        def has_next(self): return True
        def get_next(self): return ["quest-abc", "myapp [main]"]

    class MockDB:
        def execute(self, q, p=None): return ChainResult()

    result = _get_quest_for_artifact(MockDB(), "Decision", "decision_id", "did1")
    assert result["quest_id"] == "quest-abc"
    assert result["quest_name"] == "myapp [main]"


def test_get_quest_for_artifact_degrades_on_db_error():
    from mcp_engine.analogical import _get_quest_for_artifact

    class BrokenDB:
        def execute(self, q, p=None):
            raise RuntimeError("DB unavailable")

    result = _get_quest_for_artifact(BrokenDB(), "Constraint", "constraint_id", "cst1")
    assert result == {"quest_id": "", "quest_name": ""}


# ---------------------------------------------------------------------------
# analogical_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analogical_search_empty_query():
    from mcp_engine.analogical import analogical_search

    class MockDB:
        def vector_search(self, table_name, idx, vec, limit): return []

    result = await analogical_search({"query": ""}, MockDB(), {})
    assert result["results"] == []
    assert result["cross_quest"] is True


@pytest.mark.asyncio
async def test_analogical_search_returns_cross_quest_flag():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, table_name, idx, vec, limit): return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "database selection"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert result["cross_quest"] is True
    assert "query" in result
    assert "searched_tables" in result


@pytest.mark.asyncio
async def test_analogical_search_returns_results_above_threshold():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": "did1", "text_raw": "Use PostgreSQL",
                               "archived": False, "confidence": 0.9,
                               "pathway_strength": 1.2},
                     "score": 0.88},
                    {"node": {"decision_id": "did2", "text_raw": "Use SQLite",
                               "archived": False, "confidence": 0.7,
                               "pathway_strength": 0.5},
                     "score": 0.60},  # below default threshold of 0.70
                ]
            return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "database choice", "min_similarity": 0.70},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    # Only the 0.88-similarity result should be included
    assert len(result["results"]) == 1
    assert result["results"][0]["text_raw"] == "Use PostgreSQL"
    assert result["results"][0]["similarity"] == 0.88


@pytest.mark.asyncio
async def test_analogical_search_excludes_archived_nodes():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": "did-archived", "text_raw": "Old choice",
                               "archived": True, "confidence": 0.9,
                               "pathway_strength": 0.8},
                     "score": 0.95},
                ]
            return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "database"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_analogical_search_excludes_current_quest():
    from mcp_engine.analogical import analogical_search

    class SameQuestResult:
        def has_next(self): return True
        def get_next(self): return ["quest-current", "current project"]

    class MockDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": "did1", "text_raw": "Use Redis",
                               "archived": False, "confidence": 0.9,
                               "pathway_strength": 1.0},
                     "score": 0.85},
                ]
            return []
        def execute(self, q, p=None): return SameQuestResult()

    result = await analogical_search(
        {"query": "caching", "current_quest_id": "quest-current"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    # Result belongs to current quest → excluded
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_analogical_search_includes_cross_quest_results():
    from mcp_engine.analogical import analogical_search

    class OtherQuestResult:
        def has_next(self): return True
        def get_next(self): return ["quest-other", "other project"]

    class MockDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": "did1", "text_raw": "Use Redis for sessions",
                               "archived": False, "confidence": 0.9,
                               "pathway_strength": 1.0},
                     "score": 0.85},
                ]
            return []
        def execute(self, q, p=None): return OtherQuestResult()

    result = await analogical_search(
        {"query": "session caching", "current_quest_id": "quest-current"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    # Result from a different quest → included
    assert len(result["results"]) == 1
    assert result["results"][0]["quest_id"] == "quest-other"
    assert result["results"][0]["quest_name"] == "other project"


@pytest.mark.asyncio
async def test_analogical_search_respects_limit():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    class LimitDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": f"did{i}", "text_raw": f"Decision {i}",
                               "archived": False, "confidence": 0.9,
                               "pathway_strength": 1.0},
                     "score": 0.80}
                    for i in range(20)
                ]
            return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "architecture", "limit": 3},
        LimitDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert len(result["results"]) <= 3


@pytest.mark.asyncio
async def test_analogical_search_results_sorted_by_similarity():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, table_name, index_name, vec, limit):
            if "decision" in index_name:
                return [
                    {"node": {"decision_id": "low",  "text_raw": "Low similarity",
                               "archived": False, "confidence": 0.8, "pathway_strength": 1.0},
                     "score": 0.72},
                    {"node": {"decision_id": "high", "text_raw": "High similarity",
                               "archived": False, "confidence": 0.9, "pathway_strength": 1.2},
                     "score": 0.91},
                ]
            return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "some query"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    scores = [r["similarity"] for r in result["results"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_analogical_search_searches_multiple_tables():
    from mcp_engine.analogical import analogical_search

    class EmptyResult:
        def has_next(self): return False

    searched = []

    class MultiTableDB:
        def vector_search(self, table_name, index_name, vec, limit):
            searched.append(index_name)
            return []
        def execute(self, q, p=None): return EmptyResult()

    result = await analogical_search(
        {"query": "auth design"},
        MultiTableDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    # Should search Decision, Constraint, Requirement, GlobalConstraint, GlobalPreference
    assert "decision_emb_idx" in searched
    assert "constraint_emb_idx" in searched
    assert "requirement_emb_idx" in searched
    assert len(result["searched_tables"]) >= 3


# ---------------------------------------------------------------------------
# find_similar_quests
# ---------------------------------------------------------------------------

def test_find_similar_quests_empty_when_no_current_quest():
    from mcp_engine.analogical import find_similar_quests

    class MockDB:
        def execute(self, q, p=None): return None
        def vector_search(self, t, i, v, l): return []

    result = find_similar_quests("", MockDB(), {})
    assert result == []


def test_find_similar_quests_skips_current_quest():
    from mcp_engine.analogical import find_similar_quests

    class EmbResult:
        def has_next(self): return True
        def get_next(self): return [[0.1]*384, "Current Project"]

    class MockDB:
        def execute(self, q, p=None): return EmbResult()
        def vector_search(self, table_name, index_name, vec, limit):
            return [
                {"node": {"quest_id": "q-current", "name": "Current Project",
                           "purpose": "", "status": "active"},
                 "score": 1.0},
                {"node": {"quest_id": "q-other", "name": "Other Project",
                           "purpose": "Auth work", "status": "completed"},
                 "score": 0.82},
            ]

    result = find_similar_quests("q-current", MockDB(), {}, limit=3)
    # Current quest excluded; other returned
    assert len(result) == 1
    assert result[0]["quest_id"] == "q-other"


def test_find_similar_quests_returns_empty_on_db_error():
    from mcp_engine.analogical import find_similar_quests

    class BrokenDB:
        def execute(self, q, p=None):
            raise RuntimeError("broken")
        def vector_search(self, t, i, v, l):
            raise RuntimeError("broken")

    result = find_similar_quests("q-any", BrokenDB(), {})
    assert result == []


def test_find_similar_quests_returns_empty_when_no_embedding():
    from mcp_engine.analogical import find_similar_quests

    class NoEmbResult:
        def has_next(self): return True
        def get_next(self): return [None, "Project With No Embedding"]

    class MockDB:
        def execute(self, q, p=None): return NoEmbResult()
        def vector_search(self, t, i, v, l): return []

    result = find_similar_quests("q-any", MockDB(), {})
    assert result == []


# ---------------------------------------------------------------------------
# analogical_search tool handler in tools.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analogical_search_tool_handler():
    from mcp_engine.tools import analogical_search as tool_handler

    class EmptyResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, t, i, v, l): return []
        def execute(self, q, p=None): return EmptyResult()

    result = await tool_handler(
        {"query": "auth decisions"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert "results" in result
    assert result["cross_quest"] is True


@pytest.mark.asyncio
async def test_analogical_search_tool_empty_query():
    from mcp_engine.tools import analogical_search as tool_handler

    class MockDB:
        def vector_search(self, t, i, v, l): return []

    result = await tool_handler({"query": ""}, MockDB(), {})
    assert result["results"] == []


# ---------------------------------------------------------------------------
# Codex adapter — tool registration
# ---------------------------------------------------------------------------

def test_codex_adapter_has_all_tools():
    from adapters.codex.adapter import TOOLS
    names = {t["name"] for t in TOOLS}
    expected = {"notify_turn", "current_truth", "branch_quest", "diff_since",
                "get_open_loops", "analogical_search", "ingest_document",
                "explore_graph", "complete_quest", "set_quest", "context_status",
                "get_anomalies", "upsert_lesson", "recall_relevant_lessons"}
    assert names == expected


def test_codex_adapter_analogical_search_schema():
    from adapters.codex.adapter import TOOLS
    tool = next(t for t in TOOLS if t["name"] == "analogical_search")
    assert "query" in tool["inputSchema"]["required"]
    assert "min_similarity" in tool["inputSchema"]["properties"]
    assert "current_quest_id" in tool["inputSchema"]["properties"]


def test_codex_adapter_git_context_functions_exist():
    from adapters.codex.adapter import detect_git_context, _inject_context
    repo, branch = detect_git_context()
    assert isinstance(repo, str)
    assert isinstance(branch, str)

    params = {"query": "auth"}
    injected = _inject_context(params)
    assert "workspace_path" in injected
    assert injected["query"] == "auth"


def test_codex_adapter_binds_same_socket_as_claude_code():
    """Both adapters must use the same Brain socket path."""
    from adapters.codex.adapter import SOCKET_PATH as codex_sock
    from adapters.claude_code.adapter import SOCKET_PATH as cc_sock
    assert codex_sock == cc_sock


def test_codex_adapter_server_info_name():
    """Codex adapter reports a distinct server name from Claude Code adapter."""
    import asyncio
    from adapters.codex.adapter import handle_mcp_request

    async def _run():
        req = {"jsonrpc": "2.0", "id": "1", "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {}}}
        resp = await handle_mcp_request(req)
        return resp

    resp = asyncio.run(_run())
    info = resp["result"]["serverInfo"]
    assert "codex" in info["name"]


# ---------------------------------------------------------------------------
# Claude Code adapter — analogical_search registered
# ---------------------------------------------------------------------------

def test_claude_code_adapter_has_analogical_search():
    from adapters.claude_code.adapter import TOOLS
    names = [t["name"] for t in TOOLS]
    assert "analogical_search" in names


def test_claude_code_adapter_analogical_search_requires_query():
    from adapters.claude_code.adapter import TOOLS
    tool = next(t for t in TOOLS if t["name"] == "analogical_search")
    assert "query" in tool["inputSchema"]["required"]
