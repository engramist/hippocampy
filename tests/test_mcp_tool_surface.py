"""Verify all TOOL_HANDLERS are exposed via the MCP SSE endpoint."""
import pytest

try:
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    KUZU_AVAILABLE = True
except ModuleNotFoundError as e:
    if "kuzu" in str(e):
        KUZU_AVAILABLE = False
        TOOL_HANDLERS = {}
    else:
        raise

@pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")
def test_tool_handlers_has_expected_tools():
    """TOOL_HANDLERS should contain all Memory OS tools."""
    expected_tools = {
        "notify_turn", "current_truth", "branch_quest", "complete_quest",
        "diff_since", "reconstruct_timeline", "get_open_loops",
        "ingest_document", "ingest_data", "compile_context",
        "analogical_search", "explore_graph", "set_quest", "context_status",
        "get_anomalies", "upsert_lesson", "recall_relevant_lessons",
        "recall_scene_graph_priors", "get_openclaw_prompt",
        "register_plan", "report_outcome", "recall_plans",
        "recall_procedures", "get_knowledge_gaps",
        "register_task_graph", "get_ready_tasks", "advance_task",
        "fail_task", "get_task_graph",
        "get_disambiguation_queue", "resolve_disambiguation",
        "reload_domain_dictionary",
        "ingest_arc_artifacts", "publish_mechanic_summary",
        "recall_mechanic_priors", "memory_decision",
    }
    actual = set(TOOL_HANDLERS.keys())
    missing = expected_tools - actual
    assert not missing, f"Missing tools from TOOL_HANDLERS: {missing}"


class _EmptyDB:
    """B360: tools/list never touches the db -- a minimal stub is enough."""
    def execute(self, q, p=None):
        raise NotImplementedError

    async def execute_write(self, q, p=None):
        raise NotImplementedError


def _send_mcp(method: str, params: dict = None) -> dict:
    """Send an MCP JSON-RPC request to an in-process app built from the
    *current* checkout's code.

    B360: this used to POST to a real http://127.0.0.1:7799 -- whatever
    ambient `campy-daemon` process happened to be running on the developer's
    machine, possibly started from an older checkout and not yet restarted
    to pick up the very code these tests are meant to check. That's why
    these tests passed reliably in isolation (a moment where the live
    daemon happened to agree with the checkout) but flaked intermittently
    under a full suite run (a longer wall-clock window, more chances for
    that agreement to not hold) -- not the state-leak-between-tests
    hypothesis this card originally suspected. An in-process TestClient
    against a freshly-built app is deterministic and requires no ambient
    process at all.
    """
    from fastapi.testclient import TestClient
    from web.server import create_app

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params
    client = TestClient(create_app(_EmptyDB()))
    resp = client.post("/mcp", json=payload)
    return resp.json()


@pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")
def test_sse_exposes_all_tool_handlers():
    """Every key in TOOL_HANDLERS should appear in the SSE tools/list response."""
    result = _send_mcp("tools/list")
    if "error" in result:
        pytest.fail(f"tools/list returned error: {result['error']}")

    sse_tools = {t["name"] for t in result.get("result", {}).get("tools", [])}
    expected = set(TOOL_HANDLERS.keys())
    missing = expected - sse_tools
    extra = sse_tools - expected

    assert not missing, f"Tools in TOOL_HANDLERS but NOT in SSE: {missing}"
    # Extra tools in SSE are OK (might be framework-injected) — just log
    if extra:
        print(f"Note: SSE has extra tools not in TOOL_HANDLERS: {extra}")


@pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")
def test_memory_os_tools_reachable():
    """Specifically verify the Memory OS tools (B249-B254) are reachable."""
    memory_os_tools = ["compile_context", "memory_decision", "ingest_data"]
    result = _send_mcp("tools/list")
    sse_tools = {t["name"] for t in result.get("result", {}).get("tools", [])}

    for tool in memory_os_tools:
        assert tool in sse_tools, f"Memory OS tool '{tool}' not found in SSE endpoint"
