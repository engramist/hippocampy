# B262 - REST API Endpoints for External Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add REST API routes (`/api/v1/*`) to the existing daemon alongside the MCP SSE endpoint, providing standard JSON access to Campy memory for external tools and scripts.

**Architecture:** Create a FastAPI/Starlette router in `mcp_engine/rest_api.py` that wraps existing tool handlers. Mount it on the same ASGI app as the MCP SSE endpoint. All endpoints return `{"ok": bool, "data": ...}` JSON responses.

**Tech Stack:** Python, FastAPI/Starlette, existing tool handlers from `mcp_engine/tools/__init__.py`

---

### Task 1: Create REST API Router Module

**Files:**
- Create: `mcp_engine/rest_api.py`
- Create: `tests/test_rest_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rest_api.py
"""Test REST API router module."""

def test_rest_router_importable():
    """REST API router should be importable."""
    from mcp_engine.rest_api import create_router
    router = create_router()
    assert router is not None

def test_rest_router_has_routes():
    """Router should have the expected API routes."""
    from mcp_engine.rest_api import create_router
    router = create_router()
    route_paths = [r.path for r in router.routes if hasattr(r, 'path')]
    assert "/api/v1/recall" in route_paths
    assert "/api/v1/status" in route_paths
    assert "/api/v1/bundle" in route_paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rest_api.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create rest_api.py**

```python
# mcp_engine/rest_api.py
"""REST API endpoints for Campy — thin wrappers around MCP tool handlers."""
import json
import logging
import time
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)


def _ok(data: dict) -> JSONResponse:
    """Standard success response."""
    return JSONResponse({"ok": True, "data": data})


def _err(message: str, status: int = 400) -> JSONResponse:
    """Standard error response."""
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def create_router(db=None, config: dict = None):
    """Create the REST API route list. db and config are injected at mount time."""

    async def _call_tool(tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool handler directly."""
        from mcp_engine.tools import TOOL_HANDLERS
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            result = await handler(arguments=arguments, db=db, config=config or {})
            return result
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return {"error": str(e)}

    async def recall_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/recall?q=<query>&scope=both"""
        query = request.query_params.get("q", "")
        if not query:
            return _err("Missing required parameter: q")
        scope = request.query_params.get("scope", "both")
        session_id = request.query_params.get("session_id", "rest-api")
        result = await _call_tool("current_truth", {
            "query": query, "scope": scope, "session_id": session_id,
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def bundle_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/bundle — body: {query, token_budget?, agent_type?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        query = body.get("query", "")
        if not query:
            return _err("Missing required field: query")
        result = await _call_tool("compile_context", {
            "query": query,
            "token_budget": body.get("token_budget", 32000),
            "agent_type": body.get("agent_type", "generic"),
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def timeline_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/timeline?since=<ISO>&limit=20"""
        args = {"limit": int(request.query_params.get("limit", "20"))}
        since = request.query_params.get("since")
        if since:
            args["since_iso"] = since
        quest_id = request.query_params.get("quest_id")
        if quest_id:
            args["quest_id"] = quest_id
        result = await _call_tool("reconstruct_timeline", args)
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def diff_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/diff?since=<ISO>"""
        since = request.query_params.get("since")
        if not since:
            return _err("Missing required parameter: since")
        result = await _call_tool("diff_since", {"since_iso": since})
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def decide_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/decide — body: {query, session_id?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        query = body.get("query", "")
        if not query:
            return _err("Missing required field: query")
        args = {"query": query}
        if body.get("session_id"):
            args["session_id"] = body["session_id"]
        result = await _call_tool("memory_decision", args)
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def status_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/status"""
        result = await _call_tool("context_status", {})
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def notify_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/notify — body: {role, content, session_id?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        role = body.get("role", "")
        content = body.get("content", "")
        if not role or not content:
            return _err("Missing required fields: role, content")
        result = await _call_tool("notify_turn", {
            "role": role,
            "content": content,
            "session_id": body.get("session_id", "rest-api"),
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def tools_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/tools — list available tools"""
        from mcp_engine.tools import TOOL_HANDLERS
        tools = [{"name": name} for name in sorted(TOOL_HANDLERS.keys())]
        return _ok({"tools": tools, "count": len(tools)})

    routes = [
        Route("/api/v1/recall", recall_endpoint, methods=["GET"]),
        Route("/api/v1/bundle", bundle_endpoint, methods=["POST"]),
        Route("/api/v1/timeline", timeline_endpoint, methods=["GET"]),
        Route("/api/v1/diff", diff_endpoint, methods=["GET"]),
        Route("/api/v1/decide", decide_endpoint, methods=["POST"]),
        Route("/api/v1/status", status_endpoint, methods=["GET"]),
        Route("/api/v1/notify", notify_endpoint, methods=["POST"]),
        Route("/api/v1/tools", tools_endpoint, methods=["GET"]),
    ]
    return routes
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_rest_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_engine/rest_api.py tests/test_rest_api.py
git commit -m "feat(B262): create REST API router with all endpoints"
```

---

### Task 2: Mount REST Router on Daemon

**Files:**
- Modify: `brain_daemon.py` or `mcp_engine/server.py` (whichever creates the ASGI app)

- [ ] **Step 1: Identify the ASGI app creation point**

Read `brain_daemon.py` to find where the Starlette/FastAPI app is created and the SSE endpoint is mounted.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_rest_api.py (add to existing)
@pytest.mark.integration
def test_rest_api_reachable():
    """REST API should be reachable on the running daemon."""
    import requests
    try:
        resp = requests.get("http://127.0.0.1:7799/api/v1/tools", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["tools"]) > 0
    except requests.ConnectionError:
        pytest.skip("Daemon not running")
```

- [ ] **Step 3: Mount REST routes alongside SSE**

In the daemon's app creation code, add:

```python
from mcp_engine.rest_api import create_router as create_rest_routes

# After existing SSE/MCP route setup:
rest_routes = create_rest_routes(db=db, config=config)
for route in rest_routes:
    app.routes.append(route)
```

The exact integration depends on how the daemon creates its ASGI app. Read the file first, then add the routes alongside the existing `/sse` endpoint.

- [ ] **Step 4: Run integration test**

Run: `pytest tests/test_rest_api.py -m integration -v`
Expected: PASS if daemon running, SKIP otherwise

- [ ] **Step 5: Commit**

```bash
git add brain_daemon.py mcp_engine/rest_api.py tests/test_rest_api.py
git commit -m "feat(B262): mount REST API on daemon alongside MCP SSE"
```

---

### Task 3: Response Envelope Tests

**Files:**
- Modify: `tests/test_rest_api.py`

- [ ] **Step 1: Write unit tests for response format**

```python
from mcp_engine.rest_api import _ok, _err

def test_ok_envelope():
    resp = _ok({"foo": "bar"})
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["data"]["foo"] == "bar"

def test_err_envelope():
    resp = _err("something broke", 500)
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "something broke"
    assert resp.status_code == 500

def test_err_default_status():
    resp = _err("bad input")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_rest_api.py -v -m "not integration"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_rest_api.py
git commit -m "test(B262): add REST API response envelope unit tests"
```
