"""
Tests for B17 Semantic Quest Routing (Hippocampus).

Run with: python3 -m pytest tests/test_hippocampus.py -v
"""

import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_engine.hippocampus import (
    _system1_git_match,
    _system1_semantic_match,
    route_session,
    update_routing_strength,
    reconsolidate,
    RoutingResult
)

class MockResult:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._idx = 0
    def has_next(self):
        return self._idx < len(self._rows)
    def get_next(self):
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

class TestSystem1GitMatch:

    def test_git_match_finds_by_git_repo_root(self):
        """Finds quest by git_repo_root property."""
        class MockDB:
            def execute(self, query, params=None):
                if "git_repo_root" in query:
                    return MockResult([["quest-abc"]])
                return MockResult([])

        assert _system1_git_match(MockDB(), "/repo/myapp") == "quest-abc"

    def test_git_match_falls_back_to_legacy_hash(self):
        """Falls back to compute_quest_id hash when git_repo_root not populated."""
        from mcp_engine.quest import compute_quest_id
        legacy_id = compute_quest_id("/repo/myapp", "")

        class MockDB:
            def execute(self, query, params=None):
                if "git_repo_root" in query:
                    return MockResult([])  # no match on property
                if legacy_id in str(params):
                    return MockResult([[legacy_id]])
                return MockResult([])

        assert _system1_git_match(MockDB(), "/repo/myapp") == legacy_id

    def test_git_match_returns_none_when_no_match(self):
        """Returns None when neither git_repo_root nor legacy hash matches."""
        class MockDB:
            def execute(self, query, params=None):
                return MockResult([])

        assert _system1_git_match(MockDB(), "/nonexistent") is None


class TestSystem1SemanticMatch:

    def test_returns_sorted_by_similarity(self):
        """Returns candidates sorted by descending similarity."""
        quests = [
            {"quest_id": "q1", "purpose_embedding": [1.0, 0.0, 0.0]},
            {"quest_id": "q2", "purpose_embedding": [0.0, 1.0, 0.0]},
        ]
        content_emb = [0.9, 0.1, 0.0]  # closer to q1
        results = _system1_semantic_match(content_emb, quests)

        assert results[0][0] == "q1"
        assert results[0][1] > results[1][1]

    def test_empty_quests_returns_empty(self):
        assert _system1_semantic_match([1.0, 0.0], []) == []


class TestRouteSession:

    @pytest.mark.asyncio
    async def test_cold_start_creates_new_quest(self):
        """First session with no existing quests creates a new MainQuest."""
        writes = []

        class MockDB:
            def execute(self, query, params=None):
                return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await route_session(
            MockDB(), "sess-1", "Building a web app",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        assert result.is_new_quest is True
        assert result.quest_id != ""
        assert result.routing_state == "tentative"
        assert len(writes) > 0
        combined = " ".join(w["query"] for w in writes)
        assert "MainQuest" in combined
        assert "Session" in combined

    @pytest.mark.asyncio
    async def test_git_match_binds_locked(self):
        """Git repo match binds with locked state."""
        writes = []
        query_count = [0]

        class MockDB:
            def execute(self, query, params=None):
                query_count[0] += 1
                # First call: check existing binding → none
                if "WORKING_ON" in query and "routing_confidence" in query:
                    return MockResult()
                # Second call: git_repo_root match → found
                if "git_repo_root" in query:
                    return MockResult([["quest-git"]])
                return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await route_session(
            MockDB(), "sess-2", "some content",
            "sentence-transformers/all-MiniLM-L6-v2",
            git_repo_root="/repo/myapp"
        )

        assert result.quest_id == "quest-git"
        assert result.method == "git"
        assert result.routing_state == "locked"
        assert result.is_new_quest is False

    @pytest.mark.asyncio
    async def test_existing_binding_returns_cached(self):
        """Session already bound → returns existing binding without re-routing."""
        class MockDB:
            def execute(self, query, params=None):
                if "WORKING_ON" in query and "routing_confidence" in query:
                    return MockResult([["quest-existing", 0.92, "semantic_s1", "consolidated"]])
                return MockResult()
            async def execute_write(self, query, params=None): pass

        result = await route_session(
            MockDB(), "sess-3", "anything",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        assert result.quest_id == "quest-existing"
        assert result.confidence == 0.92
        assert result.routing_state == "consolidated"


class TestConsolidation:

    @pytest.mark.asyncio
    async def test_tentative_promotes_to_consolidated(self):
        """Routing strength above threshold promotes tentative → consolidated."""
        writes = []

        class MockDB:
            def execute(self, query, params=None):
                return MockResult([[0.80, "tentative"]])
            async def execute_write(self, query, params=None):
                writes.append(params)

        emb = [1.0] * 384
        new_conf = await update_routing_strength(MockDB(), "sess-1", emb, emb)

        assert new_conf >= 0.85
        assert any(w.get("state") == "consolidated" for w in writes)

    @pytest.mark.asyncio
    async def test_locked_state_not_changed(self):
        """Locked routing state is never changed by update_routing_strength."""
        writes = []

        class MockDB:
            def execute(self, query, params=None):
                return MockResult([[0.95, "locked"]])
            async def execute_write(self, query, params=None):
                writes.append(params)

        emb = [1.0] * 384
        await update_routing_strength(MockDB(), "sess-1", emb, emb)

        if writes:
            assert all(w.get("state", "locked") == "locked" for w in writes)


class TestReconsolidation:

    @pytest.mark.asyncio
    async def test_reconsolidate_creates_rerouted_from_edge(self):
        """Reconsolidation creates REROUTED_FROM edge to old quest."""
        writes = []
        query_count = [0]

        class MockDB:
            def execute(self, query, params=None):
                query_count[0] += 1
                if "WORKING_ON" in query and "routing_confidence" not in query:
                    if query_count[0] <= 2:
                        return MockResult([["old-quest"]])
                return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await reconsolidate(
            MockDB(), "sess-1", "New topic entirely",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        combined = " ".join(w["query"] for w in writes)
        assert "REROUTED_FROM" in combined
        assert "DELETE" in combined
        assert result.is_new_quest is True


class TestSetQuest:

    @pytest.mark.asyncio
    async def test_set_quest_creates_new_quest_when_not_found(self):
        from mcp_engine.tools import set_quest

        writes = []

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await set_quest(
            {"session_id": "sess-1", "quest_name": "New Project"},
            MockDB(),
            {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
        )

        assert "quest_id" in result
        assert result["routing_state"] == "locked"

    @pytest.mark.asyncio
    async def test_set_quest_requires_session_id(self):
        from mcp_engine.tools import set_quest
        class MockDB: pass
        result = await set_quest({"quest_name": "x"}, MockDB(), {})
        assert "error" in result


class TestBackwardCompat:

    @pytest.mark.asyncio
    async def test_notify_turn_with_repo_root_still_works(self):
        """Legacy git path in notify_turn still creates quest correctly."""
        from mcp_engine.tools import notify_turn, init_loop_queue
        import asyncio

        init_loop_queue(asyncio.Queue())
        writes = []

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(query)

        result = await notify_turn(
            {"role": "user", "content": "test message", "session_id": "s1",
             "repo_root": "/repo/myapp", "git_branch": "main"},
            MockDB(),
            {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
             "ingestion": {"max_ingest_chars": 4000}}
        )

        assert result["status"] == "queued"
        assert result["quest_id"] != ""
        combined = " ".join(writes)
        assert "MainQuest" in combined
