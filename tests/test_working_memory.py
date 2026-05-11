"""
Tests for B18 Context Window Awareness (Working Memory).

Run with: python3 -m pytest tests/test_working_memory.py -v
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Token estimation tests
# ---------------------------------------------------------------------------

class TestTokenEstimation:

    def test_estimate_tokens_basic(self):
        from mcp_engine.working_memory import estimate_tokens
        assert estimate_tokens("hello world") > 0

    def test_estimate_tokens_empty(self):
        from mcp_engine.working_memory import estimate_tokens
        assert estimate_tokens("") == 0

    def test_estimate_tokens_scales_with_length(self):
        from mcp_engine.working_memory import estimate_tokens
        short = estimate_tokens("hello")
        long = estimate_tokens("hello " * 100)
        assert long > short * 10

# ---------------------------------------------------------------------------
# Load tracking tests
# ---------------------------------------------------------------------------

class TestLoadTracking:

    @pytest.mark.asyncio
    async def test_track_loaded_creates_edges(self):
        """track_loaded creates LOADED edges for each result."""
        from mcp_engine.working_memory import track_loaded

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        results = [
            {"node_id": "d1", "node_type": "Decision", "text_raw": "Use PostgreSQL"},
            {"node_id": "c1", "node_type": "Constraint", "text_raw": "No external APIs"},
        ]

        count = await track_loaded(MockDB(), "sess-1", results)

        assert count == 2
        combined = " ".join(w["query"] for w in writes)
        assert "LOADED" in combined
        assert "loaded_node_count" in combined

    @pytest.mark.asyncio
    async def test_track_loaded_skips_unknown_types(self):
        """Skips nodes with unrecognized node_type."""
        from mcp_engine.working_memory import track_loaded

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(query)

        results = [
            {"node_id": "x1", "node_type": "UnknownType", "text_raw": "data"},
        ]

        count = await track_loaded(MockDB(), "sess-1", results)
        assert count == 0

    @pytest.mark.asyncio
    async def test_track_loaded_skips_raw_message_nodes(self):
        """Raw episodic recall is token-counted elsewhere, not LOADED-tracked."""
        from mcp_engine.working_memory import track_loaded

        class MockDB:
            def execute(self, *args, **kwargs):
                raise AssertionError("raw nodes should not query LOADED")
            async def execute_write(self, *args, **kwargs):
                raise AssertionError("raw nodes should not create LOADED")

        results = [
            {"node_id": "m1", "node_type": "Message", "text_raw": "raw transcript text"},
            {"node_id": "e1", "node_type": "DocumentExtract", "text_raw": "raw extract text"},
        ]

        count = await track_loaded(MockDB(), "sess-1", results)
        assert count == 0

# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

class TestDeduplication:

    def test_demotes_loaded_nodes(self):
        """Already-loaded nodes get demoted in ranking."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0, "text_raw": "old"},
            {"node_id": "d2", "_rank": 0.8, "text_raw": "new"},
        ]
        loaded_ids = {"d1"}

        deduped = deduplicate_results(results, loaded_ids)

        assert deduped[0]["node_id"] == "d2"  # new node now ranks first
        assert deduped[1]["already_in_context"] is True
        assert deduped[0]["already_in_context"] is False

    def test_empty_loaded_no_change(self):
        """No loaded nodes → no demotion."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0},
            {"node_id": "d2", "_rank": 0.8},
        ]

        deduped = deduplicate_results(results, set())

        assert deduped[0]["node_id"] == "d1"
        assert all(not r["already_in_context"] for r in deduped)

    def test_same_query_twice_demotes_second_time(self):
        """Second call with same results ranks fresh content higher."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0, "text_raw": "fact A"},
            {"node_id": "d2", "_rank": 0.9, "text_raw": "fact B"},
            {"node_id": "d3", "_rank": 0.5, "text_raw": "fact C"},
        ]

        # First call: nothing loaded
        deduped1 = deduplicate_results(results, set())
        assert deduped1[0]["node_id"] == "d1"

        # Second call: d1 and d2 are now loaded
        for r in results:
            r["_rank"] = {"d1": 1.0, "d2": 0.9, "d3": 0.5}[r["node_id"]]
        deduped2 = deduplicate_results(results, {"d1", "d2"})
        assert deduped2[0]["node_id"] == "d3"  # fresh content ranks first

# ---------------------------------------------------------------------------
# Context health tests
# ---------------------------------------------------------------------------

class TestContextHealth:

    def test_bloat_warning_above_threshold(self):
        """Returns warning when utilization exceeds threshold."""
        from mcp_engine.working_memory import check_context_health

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [100000, 128000, 12, 0, 0]  # ~78% utilization

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        warning = check_context_health(MockDB(), "sess-1")
        assert warning is not None
        assert "78%" in warning or "full" in warning

    def test_no_warning_below_threshold(self):
        """Returns None when utilization is healthy."""
        from mcp_engine.working_memory import check_context_health

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [30000, 128000, 5, 0, 0]  # ~23% utilization

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        warning = check_context_health(MockDB(), "sess-1")
        assert warning is None

# ---------------------------------------------------------------------------
# Session handoff tests
# ---------------------------------------------------------------------------

class TestSessionHandoff:

    def test_handoff_returns_prior_session_nodes(self):
        """Returns loaded nodes from most recent prior session on same quest."""
        from mcp_engine.working_memory import get_handoff_context

        query_count = [0]

        class MockResult:
            def __init__(self, rows=None):
                self._rows = rows or []; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                query_count[0] += 1
                if "WORKING_ON" in query and "session_id" in query:
                    # Prior session found
                    return MockResult([["prev-sess"]])
                if "LOADED" in query and "Decision" in query:
                    return MockResult([["d1", "Use PostgreSQL", 0.95]])
                return MockResult()

        handoff = get_handoff_context(MockDB(), "quest-1", "new-sess")
        assert len(handoff) >= 1
        assert handoff[0]["node_id"] == "d1"
        assert handoff[0]["pathway_strength"] == 0.95

    def test_handoff_returns_empty_for_first_session(self):
        """Returns empty list when no prior session exists."""
        from mcp_engine.working_memory import get_handoff_context

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        handoff = get_handoff_context(MockDB(), "quest-1", "first-sess")
        assert handoff == []

# ---------------------------------------------------------------------------
# Token state test
# ---------------------------------------------------------------------------

class TestTokenState:

    def test_get_session_token_state_returns_defaults(self):
        """Returns sensible defaults when session has no token data."""
        from mcp_engine.working_memory import get_session_token_state

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [None, None, None]

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        state = get_session_token_state(MockDB(), "sess-1")
        assert state["estimated_tokens"] == 0
        assert state["token_limit"] == 128000
        assert state["utilization"] == 0.0
        assert state["loaded_nodes"] == 0

# ---------------------------------------------------------------------------
# context_status tool test
# ---------------------------------------------------------------------------

class TestContextStatusTool:

    @pytest.mark.asyncio
    async def test_context_status_returns_structure(self):
        from mcp_engine.tools import context_status

        class MockResult:
            def __init__(self, rows=None):
                self._rows = rows or []; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                if "token_estimate" in query:
                    return MockResult([[45000, 128000, 12, 0, 0]])
                return MockResult()

        result = await context_status(
            {"session_id": "sess-1"}, MockDB(), {}
        )

        assert "token_estimate" in result
        assert "token_limit" in result
        assert "utilization" in result
        assert "loaded_nodes" in result
        assert "bloat_warning" in result
        assert "handoff_available" in result
        assert "tokens_saved_by_dedup" in result
        assert "injection_count" in result

    @pytest.mark.asyncio
    async def test_context_status_requires_session_id(self):
        from mcp_engine.tools import context_status

        result = await context_status({}, None, {})
        assert "error" in result
