# B-Streamable-HTTP — Upgrade MCP Transport from SSE to Streamable HTTP

## Overview

Upgrade the Brain Daemon's web server from the deprecated MCP 2024-11-05 SSE transport to the MCP 2025-03-26 Streamable HTTP transport. Also update the OpenClaw extension's BrainClient to use the new simpler protocol.

**Current (broken):**
1. Client GETs `/sse` → receives `connection_id` via SSE stream
2. Client POSTs to `/mcp?connection_id=xxx` → server returns `{"status":"ok"}`
3. Actual JSON-RPC result sent back via SSE stream event
4. Extension reads POST body → gets `{"status":"ok"}` → all tool results lost

**Target (Streamable HTTP):**
1. Client POSTs to `/mcp` with JSON-RPC body
2. Server returns JSON-RPC result **directly in the HTTP response body**
3. No connection_id, no SSE stream parsing for simple request-response
4. Keep legacy `/sse` endpoint alive for backwards compatibility (ChatGPT Desktop adapter)

## Files to Read First

| File | Why |
|------|-----|
| `web/server.py` lines 620-750 | Current SSE + MCP endpoint implementation |
| `extensions/sidequests-brain/src/index.ts` | BrainClient that needs updating |
| `mcp_engine/tools.py` line 1-20 (TOOL_HANDLERS) | Dispatch table reference |

## Files to Modify

| File | Change |
|------|--------|
| `web/server.py` | Rewrite `mcp_post()` to return JSON directly; keep `mcp_sse()` for legacy |
| `extensions/sidequests-brain/src/index.ts` | Simplify `BrainClient.callTool()` and `ping()` |

## Implementation

### Step 1: Update `web/server.py` — New Streamable HTTP POST handler

Find the existing `mcp_post` function (around line 658). Replace it entirely.

**Current signature:** `async def mcp_post(request: Request)`

**New implementation:**

```python
@app.post("/mcp")
async def mcp_post(request: Request):
    """
    Streamable HTTP transport (MCP 2025-03-26).
    
    Accepts JSON-RPC 2.0 requests and returns results directly in the
    HTTP response body. No connection_id or SSE stream needed.
    
    Also supports legacy SSE transport via connection_id query param
    for backwards compatibility with ChatGPT Desktop adapter.
    """
    # Legacy SSE transport — if connection_id is present, use old flow
    connection_id = request.query_params.get("connection_id")
    if connection_id:
        return await _mcp_post_legacy_sse(request, connection_id)
    
    # Streamable HTTP transport — return result directly
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    
    result = await _dispatch_mcp(body, _db_ref, _cfg_ref)
    
    # Notifications return no result
    if result is None:
        return Response(status_code=202)
    
    return JSONResponse(result)
```

**Important:** The `_db_ref` and `_cfg_ref` variables — check how the existing code accesses the database and config. They may be module-level globals or passed through the app state. Match whatever pattern the existing `mcp_post` uses.

Look at the existing `mcp_post` function to find how it accesses `db` and `config`. It likely uses something like:
- `app.state.db` and `app.state.config`, or
- Module-level variables set during startup, or
- Arguments passed to `_dispatch_mcp`

Use the same pattern. Do NOT invent a new way to access them.

### Step 2: Rename the old SSE POST handler

The existing `mcp_post` function handles the legacy `POST /mcp?connection_id=xxx` flow. Extract that logic into a helper:

```python
async def _mcp_post_legacy_sse(request: Request, connection_id: str):
    """Legacy SSE transport (MCP 2024-11-05). Kept for ChatGPT Desktop adapter."""
    # ... move the existing mcp_post body here, unchanged ...
```

This way:
- `POST /mcp` (no query params) → Streamable HTTP → direct JSON response
- `POST /mcp?connection_id=xxx` → Legacy SSE → result via SSE stream

### Step 3: Add CORS and required headers

The Streamable HTTP spec requires servers to validate the `Origin` header. Add to the new `mcp_post`:

```python
# After the JSONResponse line, before returning:
# The response should include standard headers
# FastAPI's JSONResponse handles Content-Type: application/json automatically
```

No special headers needed beyond what FastAPI provides. The existing CORS middleware (if any) should handle Origin validation. Check if the existing code has CORS configuration and leave it as-is.

### Step 4: Update `extensions/sidequests-brain/src/index.ts` — Simplify BrainClient

Replace the entire `BrainClient` class with this simpler version:

```typescript
class BrainClient {
  private baseUrl: string;
  private requestId = 0;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  /**
   * Call an MCP tool on the Brain Daemon via Streamable HTTP.
   * Simple POST to /mcp, result comes back directly in response body.
   */
  async callTool(toolName: string, args: Record<string, unknown>): Promise<unknown> {
    const rpcRequest = {
      jsonrpc: "2.0",
      id: ++this.requestId,
      method: "tools/call",
      params: { name: toolName, arguments: args },
    };

    const resp = await fetch(`${this.baseUrl}/mcp`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
      },
      body: JSON.stringify(rpcRequest),
    });

    if (!resp.ok) {
      throw new Error(`Brain returned HTTP ${resp.status}`);
    }

    const rpcResp = await resp.json();

    if (rpcResp.error) {
      throw new Error(`MCP error ${rpcResp.error.code}: ${rpcResp.error.message}`);
    }

    // Extract text content from MCP tool result
    const content = rpcResp.result?.content;
    if (content?.[0]?.type === "text") {
      try {
        return JSON.parse(content[0].text);
      } catch {
        return content[0].text;
      }
    }
    return rpcResp.result;
  }

  async ping(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.baseUrl}/mcp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 0,
          method: "initialize",
          params: {},
        }),
        signal: AbortSignal.timeout(3000),
      });
      if (!resp.ok) return false;
      const data = await resp.json();
      return !!data.result?.serverInfo;
    } catch {
      return false;
    }
  }
}
```

### Step 5: Update the health check in the register function

Find the `registerService` block at the bottom of the `register` function. Update the `start()` method:

```typescript
async start() {
  const alive = await brain.ping();
  if (alive) {
    console.log(
      `[SideQuests Brain] Connected to Brain Daemon at ${cfg.brainUrl} (Streamable HTTP)`
    );
  } else {
    console.warn(
      `[SideQuests Brain] Brain Daemon not reachable at ${cfg.brainUrl}. ` +
        `Memory tools will fail until the daemon is started.`
    );
  }
},
```

## What NOT to Do

- Do NOT remove the `GET /sse` endpoint — it's still needed for ChatGPT Desktop adapter
- Do NOT remove the `_dispatch_mcp` function — both transports use it
- Do NOT change any tool handler logic in `mcp_engine/tools.py`
- Do NOT change the JSON-RPC message format — only the transport layer changes
- Do NOT add new dependencies
- Do NOT change the legacy SSE flow — just move it to a helper function

## Verification

After implementation, run these tests:

### Test 1: Streamable HTTP POST (no connection_id)
```bash
curl -s -X POST http://127.0.0.1:7799/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 -m json.tool
```
**Expected:** Direct JSON response with tools list.

### Test 2: Streamable HTTP tool call
```bash
curl -s -X POST http://127.0.0.1:7799/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"current_truth","arguments":{"query":"test","session_id":"test-001","scope":"both","limit":3}}}' | python3 -m json.tool
```
**Expected:** Direct JSON response with results array.

### Test 3: Streamable HTTP notify_turn
```bash
curl -s -X POST http://127.0.0.1:7799/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"notify_turn","arguments":{"role":"user","content":"Test message for Streamable HTTP","session_id":"test-streamable-001"}}}' | python3 -m json.tool
```
**Expected:** Direct JSON response with `{"status":"queued","message_id":"..."}`.

### Test 4: Legacy SSE still works (backwards compat)
```bash
# Get connection_id
curl -sN http://127.0.0.1:7799/sse > /tmp/sse_test.txt &
PID=$!; sleep 2
CID=$(grep -o 'connection_id=[a-f0-9-]*' /tmp/sse_test.txt | head -1 | cut -d= -f2)
# POST with connection_id (old way)
curl -s -X POST "http://127.0.0.1:7799/mcp?connection_id=$CID" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
sleep 2
grep '^data:' /tmp/sse_test.txt
kill $PID 2>/dev/null
```
**Expected:** `{"status":"ok"}` from POST, actual result on SSE stream (old behavior).

### Test 5: Initialize (ping)
```bash
curl -s -X POST http://127.0.0.1:7799/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python3 -m json.tool
```
**Expected:** `{"result":{"protocolVersion":"2024-11-05","serverInfo":{"name":"sidequests-brain-sse",...}}}` (update protocolVersion to "2025-03-26" in _dispatch_mcp if you notice it).

### Test 6: Notification (no response expected)
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:7799/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
```
**Expected:** HTTP 202 (no body).

### Test 7: Run existing pytest suite
```bash
cd /Users/djshelton/Desktop/GitProjects/sidequests-brain
.venv/bin/python -m pytest tests/ -v --timeout=60 2>&1 | tail -20
```
**Expected:** All existing tests still pass.

## Summary of Changes

| File | Lines Changed | What |
|------|--------------|------|
| `web/server.py` | ~30 | New `mcp_post` with Streamable HTTP, old logic moved to `_mcp_post_legacy_sse` |
| `extensions/sidequests-brain/src/index.ts` | ~60 | Replace `BrainClient` class with simpler direct-POST version |

Total: ~90 lines changed across 2 files. No new files. No new dependencies.
