# Transport Audit — Streamable HTTP Migration Status

**B36 · Audit All Adapters/Plugins for Streamable HTTP Transport**
**Date:** 2026-03-28
**Status:** Complete — all surfaces audited and documented.

---

## Summary

The Brain Daemon's web endpoint was upgraded to Streamable HTTP (MCP spec 2025-03-26) as of
commit `feat: upgrade MCP transport from SSE to Streamable HTTP` (2026-03-21). This document
audits every integration surface against the current transport contract.

---

## Transport Inventory (Validated 2026-03-28)

| Integration | Transport | Status | Notes |
|-------------|-----------|--------|-------|
| **OpenClaw extension** | Streamable HTTP (`POST /mcp → JSON`) | ✅ **Primary** | Upgraded 2026-03-21. Single round-trip per tool call. SSE removed. |
| **Claude Code adapter** | stdio → Unix socket IPC | ✅ **N/A** | Not HTTP. Uses `_dispatch()` via raw JSON-RPC on `~/.sidequests/brain.sock`. |
| **Claude Desktop adapter** | stdio → Unix socket IPC | ✅ **N/A** | Same socket path as Claude Code. Functionally identical. |
| **Codex adapter** | stdio → Unix socket IPC | ✅ **N/A** | Same socket path. All 11 tools available. |
| **Gemini CLI adapter** | stdio → Unix socket IPC | ✅ **N/A** | Completed 2026-03-18. Same socket IPC pattern. |
| **ChatGPT Desktop** | SSE (`GET /sse`) | 🟡 **Legacy** | ChatGPT Desktop still uses SSE-based Connector model. Streamable HTTP upgrade blocked until ChatGPT Desktop supports it natively. SSE fallback route retained in `web/server.py`. |
| **Brain Daemon web server** | Streamable HTTP (primary) + SSE (fallback) | ✅ **Both** | `POST /mcp` returns JSON-RPC result directly. `GET /sse` retained for ChatGPT Desktop compatibility. |
| **Brain Daemon IPC** | Unix socket raw JSON-RPC | ⚠️ **Divergent** | See §IPC Dispatch Divergence below. |
| **Plugin `.mcp.json`** | SSE endpoint URL | 🟡 **Legacy** | Config file still points to SSE endpoint. Should add Streamable HTTP option for clients that support it. |

---

## IPC Dispatch Divergence

**Risk:** Medium. Currently working, but a source of future confusion.

The Brain Daemon has two dispatch paths:

### Path 1 — Web (`_dispatch_mcp` in `web/server.py`)
- Transport: Streamable HTTP (`POST /mcp`)
- Protocol: Full MCP JSON-RPC
  ```json
  { "method": "tools/call", "params": { "name": "notify_turn", "arguments": {...} } }
  ```
- Used by: OpenClaw extension, ChatGPT Desktop

### Path 2 — Unix Socket IPC (`_dispatch` in `brain_daemon.py`)
- Transport: Unix domain socket
- Protocol: Simplified raw method invocation
  ```json
  { "method": "notify_turn", "params": {...} }
  ```
- Used by: Claude Code, Claude Desktop, Codex, Gemini CLI adapters

**Why both paths exist:** Stdio-based adapters communicate via the local socket to avoid HTTP overhead on the same machine. Web-facing clients use HTTP because they may run in different processes or network namespaces.

**Impact today:** Both paths work correctly. The divergence is documented and tested (see `tests/test_adapters.py`).

**Future risk:** If the daemon evolves its internal API, maintainers must update both paths. Consider unifying under a shared `_route_tool_call(name, args)` function that both dispatch paths delegate to — the protocol normalization (MCP envelope vs. raw method) stays at the transport layer.

**Recommendation:** Unify dispatch in a future refactor (not blocking any current feature).

---

## ChatGPT Desktop Path

ChatGPT Desktop remains on SSE (`GET /sse`) because:
1. ChatGPT Desktop's Connector model uses SSE per the current public API.
2. Streamable HTTP support has not been announced for the Connector API.

**Action:** Check `https://platform.openai.com/docs/plugins` and ChatGPT Desktop Connector release notes after each major update. When Streamable HTTP support arrives, update `adapters/chatgpt_desktop/adapter.py` docs and the Connector URL to point to `POST /mcp`.

SSE fallback retained at `GET /sse` indefinitely for backward compatibility.

---

## Plugin `.mcp.json` Config

The plugin `.mcp.json` still declares the SSE endpoint URL. This is correct for ChatGPT Desktop
compatibility today, but should be updated to offer both when clients start advertising support:

```json
// Current
{ "url": "http://127.0.0.1:7799/sse" }

// Future (when Streamable HTTP is widely supported)
{
  "url": "http://127.0.0.1:7799/mcp",
  "transport": "http",
  "fallback": "http://127.0.0.1:7799/sse"
}
```

Update the `.mcp.json` when Smithery listing (B5) is prepared — align with whatever transport
the Smithery schema prefers.

---

## Smithery Listing (B5) Note

When publishing (post-patent), the `smithery.yaml` server definition should advertise
Streamable HTTP as the primary transport. Smithery v4.7.4+ understands both SSE and HTTP
transports — declare `http` as primary, `sse` as fallback.

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| Each integration marked as validated with transport and fallback | ✅ Done (table above) |
| No adapter path depends on deprecated SSE-only where Streamable HTTP is supported | ✅ Done (ChatGPT Desktop is intentional exception) |
| IPC dispatch divergence documented | ✅ Done (§ above) |

---

## Conclusion

All surfaces are audited. The only deliberately-retained SSE path is ChatGPT Desktop — not a
regression, just waiting on the Connector API to support Streamable HTTP. The IPC dispatch
divergence is documented and low-risk. No migration work is needed today beyond tracking
ChatGPT Desktop Connector API changes.
