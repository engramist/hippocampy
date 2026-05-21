# B256 - Verify MCP Server Exposes All Memory OS Tools

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every registered tool in `TOOL_HANDLERS` is reachable through the SSE MCP endpoint. Add a smoke test. Fix any gaps.

**Architecture:** Connect to `http://127.0.0.1:7799/sse`, call `tools/list`, compare returned tool names against the keys in `mcp_engine/tools/__init__.py:TOOL_HANDLERS`. Report mismatches.

**Tech Stack:** Python, pytest, httpx/requests, MCP protocol

---

### Task 1: Extract Expected Tool List

**Files:**
- Create: `tests/test_mcp_tool_surface.py`

- [ ] **Step 1: Write the test that imports TOOL_HANDLERS**

```python
# tests/test_mcp_tool_surface.py
"""Verify all TOOL_HANDLERS are exposed via the MCP SSE endpoint."""
import pytest
from mcp_engine.tools import TOOL_HANDLERS

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
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_mcp_tool_surface.py::test_tool_handlers_has_expected_tools -v`
Expected: PASS (all tools should be registered)

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_tool_surface.py
git commit -m "test(B256): verify TOOL_HANDLERS contains all expected tools"
```

---

### Task 2: SSE Endpoint Smoke Test

**Files:**
- Modify: `tests/test_mcp_tool_surface.py`

- [ ] **Step 1: Write the SSE smoke test**

```python
# Add to tests/test_mcp_tool_surface.py
import json
import requests

DAEMON_URL = "http://127.0.0.1:7799"

def _send_mcp(method: str, params: dict = None) -> dict:
    """Send an MCP JSON-RPC request to the daemon."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params
    try:
        resp = requests.post(f"{DAEMON_URL}/mcp", json=payload, timeout=5)
        return resp.json()
    except requests.ConnectionError:
        pytest.skip("Daemon not running at http://127.0.0.1:7799")

@pytest.mark.integration
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

@pytest.mark.integration
def test_memory_os_tools_reachable():
    """Specifically verify the Memory OS tools (B249-B254) are reachable."""
    memory_os_tools = ["compile_context", "memory_decision", "ingest_data"]
    result = _send_mcp("tools/list")
    sse_tools = {t["name"] for t in result.get("result", {}).get("tools", [])}

    for tool in memory_os_tools:
        assert tool in sse_tools, f"Memory OS tool '{tool}' not found in SSE endpoint"
```

- [ ] **Step 2: Run test (requires running daemon)**

Run: `pytest tests/test_mcp_tool_surface.py -m integration -v`
Expected: PASS if daemon is running, SKIP if not

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_tool_surface.py
git commit -m "test(B256): add SSE endpoint smoke test for all MCP tools"
```

---

### Task 3: Add to CI Configuration

**Files:**
- Modify: `pytest.ini` or `pyproject.toml` (whichever exists)

- [ ] **Step 1: Register integration marker**

In `pyproject.toml` or `pytest.ini`, add:

```ini
[tool.pytest.ini_options]
markers = [
    "integration: requires running daemon (deselect with '-m not integration')",
]
```

- [ ] **Step 2: Verify non-integration tests run without daemon**

Run: `pytest tests/test_mcp_tool_surface.py -m "not integration" -v`
Expected: PASS (only `test_tool_handlers_has_expected_tools` runs)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml tests/test_mcp_tool_surface.py
git commit -m "test(B256): register integration marker, add to CI config"
```
