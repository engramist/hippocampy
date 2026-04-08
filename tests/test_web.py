"""
Tests for M7 Memory Control Panel (FastAPI web server).

Run with: python3 -m pytest tests/test_web.py -v
"""

from __future__ import annotations
import sys
import os

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

class EmptyResult:
    """Mock query result with no rows."""
    def has_next(self): return False


class SingleRowResult:
    """Mock query result with one row."""
    def __init__(self, row):
        self._row = row
        self._read = False
    def has_next(self):
        return not self._read
    def get_next(self):
        self._read = True
        return self._row


class MultiRowResult:
    """Mock query result with multiple rows."""
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0
    def has_next(self): return self._idx < len(self._rows)
    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class EmptyDB:
    """DB that always returns empty results and accepts writes silently."""
    def execute(self, q, p=None): return EmptyResult()
    async def execute_write(self, q, p=None): pass


def make_client(db=None) -> TestClient:
    from web.server import create_app
    return TestClient(create_app(db or EmptyDB()))


# ---------------------------------------------------------------------------
# App creation + static serving
# ---------------------------------------------------------------------------

def test_app_creates_successfully():
    from web.server import create_app
    app = create_app(EmptyDB())
    assert app is not None


def test_index_returns_html():
    client = make_client()
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_index_contains_title():
    client = make_client()
    r = client.get("/")
    assert "SideQuest" in r.text


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------

def test_stats_returns_dict_with_expected_keys():
    client = make_client()
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    for key in ("concept", "decision", "constraint", "message"):
        assert key in data


def test_stats_returns_zero_for_empty_db():
    client = make_client()
    r = client.get("/api/stats")
    data = r.json()
    assert data["concept"] == 0
    assert data["decision"] == 0


def test_stats_returns_counts_from_db():
    class CountDB:
        def execute(self, q, p=None):
            return SingleRowResult([42])
        async def execute_write(self, q, p=None): pass

    client = make_client(CountDB())
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    # At least one count should be 42
    assert any(v == 42 for v in data.values())


# ---------------------------------------------------------------------------
# /api/graph
# ---------------------------------------------------------------------------

def test_graph_empty_db_returns_empty():
    client = make_client()
    r = client.get("/api/graph")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data
    assert data["nodes"] == []
    assert data["edges"] == []


def test_graph_returns_concept_nodes():
    class GraphDB:
        _concept_rows = [
            ["cid1", "Use PostgreSQL", "Restriction", 0.9, 1.2, False],
            ["cid2", "No external APIs", "Restriction", 0.7, 0.8, True],
        ]
        _call = 0
        def execute(self, q, p=None):
            # Return concepts on first call, empty for subsequent queries
            if "Concept" in q and "archived" in q and "gist_class" in q:
                return MultiRowResult(self._concept_rows)
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(GraphDB())
    r = client.get("/api/graph")
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["id"] == "cid1"
    assert data["nodes"][0]["type"] == "Concept"
    assert data["nodes"][1]["soft_lock"] is True


def test_graph_includes_node_count():
    client = make_client()
    r = client.get("/api/graph")
    data = r.json()
    assert "node_count" in data
    assert "edge_count" in data
    assert data["node_count"] == 0
    assert data["edge_count"] == 0


# ---------------------------------------------------------------------------
# /api/open-loops
# ---------------------------------------------------------------------------

def test_open_loops_empty_returns_zero():
    client = make_client()
    r = client.get("/api/open-loops")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []


def test_open_loops_returns_soft_lock_nodes():
    class LoopDB:
        def execute(self, q, p=None):
            if "Concept" in q and "confidence_low" in q:
                return MultiRowResult([
                    ["cid1", "Unclear decision about auth", 0.72, "2024-01-01T00:00:00"],
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(LoopDB())
    r = client.get("/api/open-loops")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["node_id"] == "cid1"
    assert data["items"][0]["node_type"] == "Concept"
    assert "Unclear decision" in data["items"][0]["text_raw"]


# ---------------------------------------------------------------------------
# POST /api/confirm/{node_id}
# ---------------------------------------------------------------------------

def test_confirm_node_found_in_concept_table():
    writes = []

    class ConfirmDB:
        def execute(self, q, p=None):
            if "Concept" in q:
                return SingleRowResult(["cid1"])
            return EmptyResult()
        async def execute_write(self, q, p=None):
            writes.append(q)

    client = make_client(ConfirmDB())
    r = client.post("/api/confirm/cid1")
    assert r.status_code == 200
    data = r.json()
    assert data["confirmed"] is True
    assert data["node_id"] == "cid1"
    assert data["node_type"] == "Concept"
    assert len(writes) == 1
    assert "confidence_low = false" in writes[0]


def test_confirm_node_not_found_returns_404():
    client = make_client()  # EmptyDB → no rows in any table
    r = client.post("/api/confirm/nonexistent-id")
    assert r.status_code == 404


def test_confirm_searches_decision_table_if_not_concept():
    writes = []

    class DecisionConfirmDB:
        def execute(self, q, p=None):
            if "Decision" in q:
                return SingleRowResult(["did1"])
            return EmptyResult()  # Concept table returns empty
        async def execute_write(self, q, p=None):
            writes.append(q)

    client = make_client(DecisionConfirmDB())
    r = client.post("/api/confirm/did1")
    assert r.status_code == 200
    data = r.json()
    assert data["node_type"] == "Decision"


# ---------------------------------------------------------------------------
# POST /api/reject/{node_id}
# ---------------------------------------------------------------------------

def test_reject_node_archives_it():
    writes = []

    class RejectDB:
        def execute(self, q, p=None):
            if "Constraint" in q:
                return SingleRowResult(["cst1"])
            return EmptyResult()
        async def execute_write(self, q, p=None):
            writes.append(q)

    client = make_client(RejectDB())
    r = client.post("/api/reject/cst1")
    assert r.status_code == 200
    data = r.json()
    assert data["rejected"] is True
    assert "archived = true" in writes[0]


def test_reject_node_not_found_returns_404():
    client = make_client()
    r = client.post("/api/reject/ghost-id")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/merge-events
# ---------------------------------------------------------------------------

def test_merge_events_empty():
    client = make_client()
    r = client.get("/api/merge-events")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["events"] == []


def test_merge_events_returns_list():
    class MergeDB:
        def execute(self, q, p=None):
            if "MergeEvent" in q:
                return MultiRowResult([
                    ["meid1", 0.5, 0.2,
                     "contradiction:old=old123,new=new456",
                     "2024-01-01T10:00:00"],
                    ["meid2", 0.8, 0.1,
                     "additive",
                     "2024-01-01T11:00:00"],
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(MergeDB())
    r = client.get("/api/merge-events")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["events"][0]["merge_type"] == "contradiction"
    assert data["events"][1]["merge_type"] == "additive"
    assert data["events"][0]["already_rolled_back"] is False


def test_merge_events_flags_already_rolled_back():
    class RolledDB:
        def execute(self, q, p=None):
            return MultiRowResult([
                ["meid1", 0.5, 0.0, "contradiction:old=x,new=y;rolled_back=true", "2024-01-01"],
            ])
        async def execute_write(self, q, p=None): pass

    client = make_client(RolledDB())
    r = client.get("/api/merge-events")
    data = r.json()
    assert data["events"][0]["already_rolled_back"] is True


# ---------------------------------------------------------------------------
# DELETE /api/merge-events/{id}
# ---------------------------------------------------------------------------

def test_rollback_merge_not_found_returns_404():
    client = make_client()
    r = client.delete("/api/merge-events/ghost-id")
    assert r.status_code == 404


def test_rollback_contradiction_merge():
    writes = []

    class RollbackDB:
        def execute(self, q, p=None):
            if "MergeEvent" in q:
                return SingleRowResult([
                    "contradiction:old=old123,new=new456", 0.65
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None):
            writes.append({"q": q, "p": p})

    client = make_client(RollbackDB())
    r = client.delete("/api/merge-events/meid1")
    assert r.status_code == 200
    data = r.json()
    assert data["rolled_back"] is True
    assert data["old_concept_restored"] == "old123"
    assert data["new_concept_archived"] == "new456"
    # Should have 4 writes: un-archive old, archive new, delete DEPRECATED_BY, update metadata
    assert len(writes) == 4
    # W2 fix: verify DEPRECATED_BY edge removal is included
    assert any("DEPRECATED_BY" in w["q"] and "DELETE" in w["q"] for w in writes)


def test_rollback_already_rolled_back_returns_409():
    class AlreadyRolledDB:
        def execute(self, q, p=None):
            return SingleRowResult([
                "contradiction:old=x,new=y;rolled_back=true", 0.5
            ])
        async def execute_write(self, q, p=None): pass

    client = make_client(AlreadyRolledDB())
    r = client.delete("/api/merge-events/meid1")
    assert r.status_code == 409


def test_rollback_additive_only_updates_metadata():
    writes = []

    class AdditiveRollbackDB:
        def execute(self, q, p=None):
            if "MergeEvent" in q:
                return SingleRowResult(["additive", 0.7])
            return EmptyResult()
        async def execute_write(self, q, p=None):
            writes.append(q)

    client = make_client(AdditiveRollbackDB())
    r = client.delete("/api/merge-events/meid-additive")
    assert r.status_code == 200
    data = r.json()
    assert data["rolled_back"] is True
    # Additive rollback: only metadata update (no concept un-archive)
    assert len(writes) == 1
    assert "rolled_back=true" in writes[0] or "metadata_patch" in writes[0]


# ---------------------------------------------------------------------------
# /api/export/constraint-ledger
# ---------------------------------------------------------------------------

def test_export_ledger_md_returns_markdown():
    client = make_client()
    r = client.get("/api/export/constraint-ledger")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "Constraint Ledger" in r.text


def test_export_ledger_md_with_data():
    class LedgerDB:
        def execute(self, q, p=None):
            if "Constraint" in q and "archived" in q:
                return MultiRowResult([
                    ["cst1", "No external API calls without security review",
                     0.9, False, 1.5, "2024-01-01"],
                    ["cst2", "All endpoints must use JWT auth",
                     0.6, True, 0.8, "2024-01-02"],
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(LedgerDB())
    r = client.get("/api/export/constraint-ledger")
    assert "No external API calls" in r.text
    assert "JWT auth" in r.text
    assert "✓" in r.text   # confirmed
    assert "?" in r.text    # uncertain


def test_export_ledger_md_empty_db():
    client = make_client()
    r = client.get("/api/export/constraint-ledger")
    assert "No active constraints" in r.text


def test_export_ledger_json_returns_json():
    client = make_client()
    r = client.get("/api/export/constraint-ledger.json")
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]
    data = r.json()
    assert "constraints" in data
    assert "count" in data
    assert "exported_at" in data


def test_export_ledger_json_with_data():
    class LedgerDB:
        def execute(self, q, p=None):
            # _collect_ledger queries "Constraint" then "GlobalConstraint"
            # Only return data for Constraint; GlobalConstraint returns empty
            if "GlobalConstraint" in q:
                return EmptyResult()
            if "Constraint" in q and "archived" in q:
                return MultiRowResult([
                    ["cst1", "No external APIs", 0.95, False, 2.0, "2024-01-01"],
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(LedgerDB())
    r = client.get("/api/export/constraint-ledger.json")
    data = r.json()
    assert data["count"] == 1
    assert data["constraints"][0]["text_raw"] == "No external APIs"
    assert data["constraints"][0]["confidence_low"] is False


# ---------------------------------------------------------------------------
# /api/quests
# ---------------------------------------------------------------------------

def test_quests_empty_db():
    client = make_client()
    r = client.get("/api/quests")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["quests"] == []


def test_quests_returns_main_quests():
    class QuestDB:
        _quest_rows = [
            ["qid1", "myapp [main]", "active", "Build memory system", "2024-01-01"],
        ]
        def execute(self, q, p=None):
            if "MainQuest" in q and "archived" in q and "BELONGS_TO" not in q:
                return MultiRowResult(self._quest_rows)
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(QuestDB())
    r = client.get("/api/quests")
    data = r.json()
    assert data["count"] == 1
    assert data["quests"][0]["name"] == "myapp [main]"
    assert data["quests"][0]["type"] == "MainQuest"
    assert data["quests"][0]["side_quests"] == []


def test_quests_nests_side_quests():
    class NestDB:
        def execute(self, q, p=None):
            if "MainQuest" in q and "BELONGS_TO" not in q:
                return MultiRowResult([
                    ["qid-main", "myapp [main]", "active", "Build brain", "2024-01-01"],
                ])
            if "SideQuest" in q and "BELONGS_TO" in q:
                return MultiRowResult([
                    ["sqid1", "Auth Spike", "active", "OAuth2 exploration",
                     "2024-01-02", "qid-main"],
                ])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(NestDB())
    r = client.get("/api/quests")
    data = r.json()
    assert data["count"] == 1
    main = data["quests"][0]
    assert len(main["side_quests"]) == 1
    assert main["side_quests"][0]["name"] == "Auth Spike"
    assert main["side_quests"][0]["type"] == "SideQuest"


# ---------------------------------------------------------------------------
# Security: host binding check (brain_daemon integration)
# ---------------------------------------------------------------------------

def test_create_app_does_not_bind_to_all_interfaces():
    """Confirm the server module does not contain a binding to 0.0.0.0."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "web" / "server.py").read_text()
    # The binding check: host="0.0.0.0" or host='0.0.0.0' should not appear
    assert 'host="0.0.0.0"' not in src
    assert "host='0.0.0.0'" not in src


# ---------------------------------------------------------------------------
# B3 — SSE endpoint tests
# ---------------------------------------------------------------------------

def test_mcp_post_without_connection_returns_400():
    """POST /mcp with no active SSE connection returns 400."""
    client = make_client()
    r = client.post("/mcp?connection_id=nonexistent", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert r.status_code == 400


def test_mcp_post_invalid_json_returns_400():
    """POST /mcp with invalid JSON returns 400."""
    client = make_client()
    r = client.post(
        "/mcp?connection_id=fake",
        content=b"not json",
        headers={"content-type": "application/json"}
    )
    # Should return 400 for either "no connection" or "invalid json"
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_dispatch_mcp_initialize_direct():
    """Test _dispatch_mcp directly without SSE transport."""
    from web.server import _dispatch_mcp
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        EmptyDB(), {}
    )
    assert resp["result"]["protocolVersion"] == "2025-03-26"


@pytest.mark.asyncio
async def test_dispatch_mcp_tools_list_direct():
    from web.server import _dispatch_mcp
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        EmptyDB(), {}
    )
    tool_names = {t["name"] for t in resp["result"]["tools"]}
    assert "notify_turn" in tool_names
    assert len(tool_names) == 26  # Prior 23 + B158 disambiguation tools (2) + B160 reload_domain_dictionary (1)

@pytest.mark.asyncio
async def test_dispatch_mcp_unknown_method_direct():
    from web.server import _dispatch_mcp
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 3, "method": "fake/method", "params": {}},
        EmptyDB(), {}
    )
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_dispatch_mcp_unknown_tool_direct():
    from web.server import _dispatch_mcp
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
        EmptyDB(), {}
    )
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_sse_context_injection_direct():
    """Test that _dispatch_mcp injects context for tools/call."""
    from web.server import _dispatch_mcp
    from mcp_engine import tools as tools_mod

    received_params = {}

    async def spy_handler(params, db, config):
        received_params.update(params)
        return {"items": [], "count": 0}

    # Patch handler
    original = tools_mod.TOOL_HANDLERS.get("get_open_loops")
    tools_mod.TOOL_HANDLERS["get_open_loops"] = spy_handler

    try:
        await _dispatch_mcp(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "get_open_loops", "arguments": {}}},
            EmptyDB(), {}
        )
        assert "workspace_path" in received_params
        assert "token_limit" in received_params
        assert received_params["token_limit"] == 128000
    finally:
        tools_mod.TOOL_HANDLERS["get_open_loops"] = original
