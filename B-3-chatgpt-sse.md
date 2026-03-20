# B-3 — ChatGPT Desktop SSE Endpoint: Tests, Smoke Test, & Polish

## Overview

The MCP-over-SSE transport in `web/server.py` (lines 607–729) is **already implemented**.
The installer already detects ChatGPT Desktop and prints a URL. What's missing:

1. **Tests** for `/sse` and `/mcp` SSE endpoints (zero coverage today)
2. **Smoke test integration** — `sidequests status` should verify the SSE endpoint responds
3. **Git context injection** — the SSE dispatcher doesn't inject `workspace_path`, `repo_root`, `git_branch`, or `token_limit` into tool calls (the stdio adapters do this via `_inject_context()`)
4. **Tool list freshness** — `_dispatch_mcp()` imports `TOOLS` from `adapters/claude_code/adapter.py` instead of having its own list or a shared canonical source; if the tool lists diverge, ChatGPT Desktop gets stale tools

## Architecture Decisions

- **No standalone adapter file needed** — `adapters/chatgpt_desktop/adapter.py` stays as a docstring stub. The SSE endpoint in `web/server.py` handles everything in-process (no socket hop, lower latency).
- **Shared tool list** — Extract `TOOLS` into a shared module (`mcp_engine/tool_schemas.py`) so all adapters and the SSE endpoint import from one canonical source. This prevents tool list drift.
- **Context injection** — The SSE endpoint must inject the same context the stdio adapters do. Since there's no git repo for a ChatGPT Desktop user, `workspace_path` comes from the OS home dir, `repo_root` and `git_branch` are empty strings, and `token_limit` is the ChatGPT model's context window size.

## Implementation Order

### Phase 1: Extract shared tool schemas

**File: `mcp_engine/tool_schemas.py`** (NEW)

Extract the `TOOLS` list from `adapters/claude_code/adapter.py` into a shared module. All 4 stdio adapters + the SSE endpoint import from here.

```python
"""
mcp_engine/tool_schemas.py — Canonical MCP tool schema definitions.

Single source of truth for tool names, descriptions, and input schemas.
All adapters (stdio + SSE) import from here to prevent drift.
"""

TOOLS: list[dict] = [
    # Copy the exact TOOLS list from adapters/claude_code/adapter.py
    # All 11 tools: notify_turn, current_truth, branch_quest, diff_since,
    # get_open_loops, analogical_search, ingest_document, explore_graph,
    # complete_quest, set_quest, context_status
    ...
]
```

Then update all consumers:
- `adapters/claude_code/adapter.py` — `from mcp_engine.tool_schemas import TOOLS`
- `adapters/codex/adapter.py` — `from mcp_engine.tool_schemas import TOOLS`
- `adapters/claude_desktop/adapter.py` — `from mcp_engine.tool_schemas import TOOLS`
- `adapters/gemini_cli/adapter.py` — `from mcp_engine.tool_schemas import TOOLS`
- `web/server.py` — `from mcp_engine.tool_schemas import TOOLS` (replace the current `from adapters.claude_code.adapter import TOOLS as _TOOLS`)

**Verification:** Run `python3 -m pytest tests/ -v` — all 442+ tests must pass. The tool list is identical, just imported from a new location.

### Phase 2: SSE context injection

**File: `web/server.py`** — modify `_dispatch_mcp()`

The stdio adapters call `_inject_context(params)` before forwarding to `_call_brain()`. The SSE endpoint must do the same for `tools/call`. Since there's no git repo or workspace for a ChatGPT Desktop session, inject sensible defaults:

```python
# In _dispatch_mcp(), inside the tools/call handler, before calling the tool handler:

def _inject_sse_context(tool_args: dict) -> dict:
    """Inject context for SSE clients (no git repo, no workspace)."""
    enriched = dict(tool_args)
    enriched.setdefault("repo_root", "")
    enriched.setdefault("git_branch", "")
    enriched.setdefault("workspace_path", str(Path.home()))
    enriched.setdefault("token_limit", 128000)  # GPT-4o default
    return enriched
```

Update the `tools/call` block in `_dispatch_mcp()`:

```python
if method == "tools/call":
    tool_name = params.get("name", "")
    tool_args = params.get("arguments", {})
    tool_args = _inject_sse_context(tool_args)  # ADD THIS LINE
    handler = TOOL_HANDLERS.get(tool_name)
    ...
```

### Phase 3: Tests for SSE endpoints

**File: `tests/test_web.py`** — add SSE endpoint tests at the bottom

Use the existing `make_client()` + `EmptyDB` pattern from the file. FastAPI's `TestClient` supports SSE via streaming responses.

```python
# ---------------------------------------------------------------------------
# B3 — SSE endpoint tests
# ---------------------------------------------------------------------------

def test_sse_endpoint_returns_event_stream():
    """GET /sse returns text/event-stream content type."""
    client = make_client()
    with client.stream("GET", "/sse") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        # Read just the first event (endpoint announcement)
        first_chunk = next(r.iter_lines())
        assert "event: endpoint" in first_chunk or "endpoint" in first_chunk
        # Don't hang — break after first event
        break  # TestClient may not support clean SSE close


def test_sse_endpoint_returns_connection_id():
    """GET /sse first event contains a connection_id in the endpoint URL."""
    client = make_client()
    with client.stream("GET", "/sse") as r:
        lines = []
        for line in r.iter_lines():
            lines.append(line)
            if len(lines) >= 3:  # event: endpoint\ndata: /mcp?...\n\n
                break
        joined = "\n".join(lines)
        assert "connection_id=" in joined


def test_mcp_post_without_connection_returns_400():
    """POST /mcp with no active SSE connection returns 400."""
    client = make_client()
    r = client.post("/mcp?connection_id=nonexistent", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert r.status_code == 400


def test_mcp_post_invalid_json_returns_400():
    """POST /mcp with invalid JSON returns 400."""
    import asyncio, uuid
    # We need an active SSE connection — simulate by accessing _sse_connections
    # Instead, test the error path directly
    client = make_client()
    r = client.post(
        "/mcp?connection_id=fake",
        content=b"not json",
        headers={"content-type": "application/json"}
    )
    # Should return 400 for either "no connection" or "invalid json"
    assert r.status_code == 400


def test_dispatch_mcp_initialize():
    """_dispatch_mcp returns correct initialize response."""
    import asyncio
    from web.server import create_app

    db = EmptyDB()
    app = create_app(db)

    # Access _dispatch_mcp from the app's scope
    # Since _dispatch_mcp is a local function, test via the POST endpoint
    # We need to establish an SSE connection first
    # Use a simpler approach: test the full round-trip via threading

    # Alternative: test that the SSE endpoint serves tools/list correctly
    # by extracting _dispatch_mcp to module level
    pass  # Covered by integration test below


def test_sse_mcp_initialize_round_trip():
    """Full round-trip: open SSE → POST initialize → receive response on SSE stream."""
    import threading
    import time

    client = make_client()
    results = {"endpoint": None, "response": None}

    def sse_reader():
        """Read SSE events in a background thread."""
        with client.stream("GET", "/sse") as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and "connection_id=" in line:
                    results["endpoint"] = line[6:]  # strip "data: "
                elif line.startswith("data: ") and "protocolVersion" in line:
                    results["response"] = line[6:]
                    break
                if results.get("endpoint") and results.get("response"):
                    break

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(0.2)  # Let SSE connection establish

    if results["endpoint"]:
        # POST initialize request
        endpoint_url = results["endpoint"]
        r = client.post(endpoint_url, json={
            "jsonrpc": "2.0", "id": "1",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}}
        })
        assert r.status_code == 200

    t.join(timeout=2)

    if results["response"]:
        import json
        resp = json.loads(results["response"])
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert "sidequests-brain" in resp["result"]["serverInfo"]["name"]


def test_sse_mcp_tools_list_round_trip():
    """SSE round-trip for tools/list returns all expected tools."""
    import threading
    import time
    import json

    client = make_client()
    results = {"endpoint": None, "response": None}

    def sse_reader():
        with client.stream("GET", "/sse") as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and "connection_id=" in line:
                    results["endpoint"] = line[6:]
                elif line.startswith("data: ") and "tools" in line:
                    results["response"] = line[6:]
                    break

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(0.2)

    if results["endpoint"]:
        r = client.post(results["endpoint"], json={
            "jsonrpc": "2.0", "id": "2",
            "method": "tools/list", "params": {}
        })
        assert r.status_code == 200

    t.join(timeout=2)

    if results["response"]:
        resp = json.loads(results["response"])
        tool_names = {t["name"] for t in resp["result"]["tools"]}
        assert "notify_turn" in tool_names
        assert "current_truth" in tool_names
        assert "set_quest" in tool_names
        assert "context_status" in tool_names


def test_sse_context_injection():
    """SSE tool calls include workspace_path and token_limit."""
    import threading
    import time
    import json

    received_params = {}

    class SpyDB(EmptyDB):
        """DB that captures tool params."""
        pass

    # We need to intercept the tool handler call to verify params
    # Use monkeypatch-style approach via the test
    # Since TOOL_HANDLERS are module-level, we can patch them
    from mcp_engine import tools as tools_mod
    original_handler = tools_mod.TOOL_HANDLERS.get("get_open_loops")

    async def spy_handler(params, db, config):
        received_params.update(params)
        return {"items": [], "count": 0}

    tools_mod.TOOL_HANDLERS["get_open_loops"] = spy_handler

    try:
        client = make_client()
        results = {"endpoint": None}

        def sse_reader():
            with client.stream("GET", "/sse") as r:
                for line in r.iter_lines():
                    if line.startswith("data: ") and "connection_id=" in line:
                        results["endpoint"] = line[6:]
                    elif line.startswith("data: ") and "content" in line:
                        break

        t = threading.Thread(target=sse_reader, daemon=True)
        t.start()
        time.sleep(0.2)

        if results["endpoint"]:
            r = client.post(results["endpoint"], json={
                "jsonrpc": "2.0", "id": "3",
                "method": "tools/call",
                "params": {"name": "get_open_loops", "arguments": {}}
            })

        t.join(timeout=2)

        assert "workspace_path" in received_params, "SSE should inject workspace_path"
        assert "token_limit" in received_params, "SSE should inject token_limit"
    finally:
        tools_mod.TOOL_HANDLERS["get_open_loops"] = original_handler


def test_sse_unknown_tool_returns_error():
    """SSE tools/call with unknown tool returns -32601."""
    import threading
    import time
    import json

    client = make_client()
    results = {"endpoint": None, "response": None}

    def sse_reader():
        with client.stream("GET", "/sse") as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and "connection_id=" in line:
                    results["endpoint"] = line[6:]
                elif line.startswith("data: ") and "error" in line:
                    results["response"] = line[6:]
                    break

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(0.2)

    if results["endpoint"]:
        r = client.post(results["endpoint"], json={
            "jsonrpc": "2.0", "id": "4",
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}}
        })

    t.join(timeout=2)

    if results["response"]:
        resp = json.loads(results["response"])
        assert resp["error"]["code"] == -32601


def test_sse_unknown_method_returns_error():
    """SSE unknown method returns -32601."""
    import threading
    import time
    import json

    client = make_client()
    results = {"endpoint": None, "response": None}

    def sse_reader():
        with client.stream("GET", "/sse") as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and "connection_id=" in line:
                    results["endpoint"] = line[6:]
                elif line.startswith("data: ") and "error" in line:
                    results["response"] = line[6:]
                    break

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(0.2)

    if results["endpoint"]:
        r = client.post(results["endpoint"], json={
            "jsonrpc": "2.0", "id": "5",
            "method": "weird/method", "params": {}
        })

    t.join(timeout=2)

    if results["response"]:
        resp = json.loads(results["response"])
        assert resp["error"]["code"] == -32601
```

**IMPORTANT:** The SSE round-trip tests use `threading` + `time.sleep(0.2)` because FastAPI's `TestClient` is synchronous. If the streaming approach proves flaky in CI, fall back to testing `_dispatch_mcp` directly by refactoring it to module level. The tests above are the ideal coverage; adjust the mechanism if TestClient SSE support is limited.

**Fallback test approach** (if streaming is too flaky): Extract `_dispatch_mcp` and `_inject_sse_context` as module-level functions and test them directly with `asyncio.run()`:

```python
@pytest.mark.asyncio
async def test_dispatch_mcp_initialize_direct():
    """Test _dispatch_mcp directly without SSE transport."""
    from web.server import _dispatch_mcp  # after refactoring to module level
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        EmptyDB(), {}
    )
    assert resp["result"]["protocolVersion"] == "2024-11-05"

@pytest.mark.asyncio
async def test_dispatch_mcp_tools_list_direct():
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        EmptyDB(), {}
    )
    tool_names = {t["name"] for t in resp["result"]["tools"]}
    assert len(tool_names) == 11

@pytest.mark.asyncio
async def test_dispatch_mcp_unknown_method_direct():
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 3, "method": "fake/method", "params": {}},
        EmptyDB(), {}
    )
    assert resp["error"]["code"] == -32601

@pytest.mark.asyncio
async def test_dispatch_mcp_unknown_tool_direct():
    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
        EmptyDB(), {}
    )
    assert resp["error"]["code"] == -32601
```

**Use the fallback approach (direct async tests).** The threading approach is fragile. Refactor `_dispatch_mcp` and `_inject_sse_context` to module-level functions in `web/server.py` (still called by the route handlers), then test them directly. This gives reliable, fast tests.

### Phase 4: Smoke test SSE verification

**File: `sidequests/cli/smoke_test.py`** — add SSE health check

Read the existing `smoke_test.py` first to understand the pattern. Add an SSE endpoint check:

```python
def check_sse_endpoint(port: int = 7799) -> bool:
    """Verify the SSE endpoint is responding."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/sse",
            headers={"Accept": "text/event-stream"}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        first_line = resp.readline().decode()
        resp.close()
        if "endpoint" in first_line or "event" in first_line:
            click.echo("  [ok] SSE endpoint responding")
            return True
        click.echo("  [!] SSE endpoint returned unexpected data")
        return False
    except Exception as e:
        click.echo(f"  [!] SSE endpoint unreachable: {e}")
        return False
```

Call this from the existing `check_status()` function (or wherever the smoke test runs) after the socket/daemon check passes.

### Phase 5: Update adapter registration message

**File: `sidequests/cli/install.py`** — update `_register_chatgpt_desktop()`

Make the message clearer and more actionable for a non-technical user:

```python
def _register_chatgpt_desktop(self) -> bool:
    """Print setup instructions for ChatGPT Desktop (SSE connector)."""
    click.echo("    [ok] ChatGPT Desktop — SSE endpoint ready")
    click.echo("")
    click.echo("    To connect ChatGPT Desktop:")
    click.echo("      1. Open ChatGPT Desktop")
    click.echo("      2. Go to Settings → MCP Servers (or Apps → Add Connector)")
    click.echo("      3. Add server URL: http://127.0.0.1:7799/sse")
    click.echo("      4. Save — all SideQuest tools will appear automatically")
    click.echo("")
    return True
```

## Files to Create

| File | Action |
|------|--------|
| `mcp_engine/tool_schemas.py` | NEW — canonical tool list |

## Files to Modify

| File | Change |
|------|--------|
| `web/server.py` | Add `_inject_sse_context()`, refactor `_dispatch_mcp` to module-level, import TOOLS from tool_schemas |
| `adapters/claude_code/adapter.py` | Import TOOLS from `mcp_engine.tool_schemas` instead of defining locally |
| `adapters/codex/adapter.py` | Same |
| `adapters/claude_desktop/adapter.py` | Same |
| `adapters/gemini_cli/adapter.py` | Same |
| `tests/test_web.py` | Add SSE endpoint tests (Phase 3) |
| `tests/test_adapters.py` | May need import path update if TOOLS source changes |
| `tests/test_analogical.py` | May need import path update if TOOLS source changes |
| `sidequests/cli/smoke_test.py` | Add SSE health check (Phase 4) |
| `sidequests/cli/install.py` | Improve ChatGPT Desktop registration message (Phase 5) |

## Files to Read First (existing patterns)

- `adapters/claude_code/adapter.py` — current TOOLS list (source of truth to extract)
- `adapters/codex/adapter.py` — same, verify identical
- `web/server.py` — full file, understand SSE implementation
- `tests/test_web.py` — existing test patterns
- `tests/test_adapters.py` — verify TOOLS import paths
- `tests/test_analogical.py` — verify TOOLS import paths
- `sidequests/cli/smoke_test.py` — existing smoke test pattern
- `sidequests/cli/install.py` — existing registration code

## Verification

1. `python3 -m pytest tests/test_web.py -v` — new SSE tests pass
2. `python3 -m pytest tests/test_adapters.py -v` — adapter tests still pass (TOOLS import change)
3. `python3 -m pytest tests/test_analogical.py -v` — analogical tests still pass
4. `python3 -m pytest tests/ -v` — full suite, 0 failures
5. All 4 adapters + SSE endpoint serve identical tool lists (11 tools)
6. SSE tool calls include `workspace_path` and `token_limit` in params
