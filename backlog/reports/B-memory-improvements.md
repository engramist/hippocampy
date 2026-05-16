# B-Memory-Improvements — SideQuests Brain Test Report

**Tested by:** SideClaw (AI CTO)  
**Date:** 2026-03-21  
**Method:** Direct MCP tool calls via SSE/HTTP + REST API endpoints + source code review

---

## Executive Summary

The Brain Daemon is functional — ingestion, recall, analogies, and open loops all work. But there are **10 concrete issues** ranging from critical bugs to quality improvements. The biggest wins are fixing the OpenClaw extension's response parsing (critical), restarting the daemon to pick up new tools, and improving recall relevance.

---

## Critical Bugs

### 1. 🔴 Brain Daemon Uses Deprecated SSE Transport — Upgrade to Streamable HTTP

**Severity:** CRITICAL — extension can't read tool results, entire protocol is outdated  
**Files:** `web/server.py`, `extensions/hippocampy/src/index.ts`

The Brain Daemon uses the **deprecated MCP 2024-11-05 SSE transport**:
1. Client GETs `/sse` → receives `connection_id`
2. Client POSTs to `/mcp?connection_id=xxx` → server returns `{"status":"ok"}`
3. Actual result sent back via SSE stream

MCP spec 2025-03-26 replaced this with **Streamable HTTP**:
1. Client POSTs to `/mcp` → server returns result **directly in response body** as `application/json`
2. No connection_id needed, no SSE stream for simple request-response
3. SSE is optional (only for streaming/server-initiated messages)

**Evidence:**
```
POST response: {"status":"ok"}     ← extension reads this (empty)
SSE stream:    {"jsonrpc":"2.0","id":42,"result":{...}}  ← actual data (never read)
```

**Fix — `web/server.py`:**
```python
@app.post("/mcp")
async def mcp_post(request: Request):
    body = await request.json()
    result = await _dispatch_mcp(body, db, config)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)  # Direct response, no SSE
```

**Fix — `extensions/hippocampy/src/index.ts` (BrainClient):**
```typescript
async callTool(toolName: string, args: Record<string, unknown>): Promise<unknown> {
    const resp = await fetch(`${this.baseUrl}/mcp`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        body: JSON.stringify({
            jsonrpc: "2.0",
            id: ++this.requestId,
            method: "tools/call",
            params: { name: toolName, arguments: args }
        })
    });
    const rpcResp = await resp.json();
    // Extract result directly from response
    const content = rpcResp.result?.content;
    if (content?.[0]?.type === "text") {
        return JSON.parse(content[0].text);
    }
    return rpcResp.result;
}
```

**Impact:** ALL tool results are invisible to the OpenClaw extension. `memory_recall` returns nothing. Only `memory_store` (notify_turn) works by accident because the caller doesn't need the result.

### 2. 🔴 Two Tools Not Registered in Running Daemon

**Severity:** HIGH — `context_status` and `set_quest` return "Unknown tool"  
**Cause:** Daemon process was started before these tools were added to `TOOL_HANDLERS`. Module cache serves stale version.

**Fix:** Restart the Brain Daemon:
```bash
kill $(pgrep -f brain_daemon) && sleep 2
~/.sidequests/../.venv/bin/python brain_daemon.py &
```

**Evidence:** `tools/list` shows them registered, but `tools/call` returns `-32601 Unknown tool` for both.

---

## Data Quality Issues

### 3. 🟡 Recall Returns Wrong Results for Specific Queries

**Severity:** MEDIUM — semantic search finds related but wrong nodes

When I stored "We decided to use Redis for caching" and queried "What caching technology did we choose?", the top results were JWT, Session, API — none related to Redis or caching.

**Root cause candidates:**
- The consolidation loop extracts single-word NER entities ("Redis") but the ranking formula `(pathway_strength * confidence)` heavily favors old, frequently-seen nodes over new, relevant ones
- `all-MiniLM-L6-v2` at 384 dimensions may not distinguish "caching technology" from generic tech terms well enough
- No recency boost — old nodes from `sidequests-test` dominate over freshly stored ones

**Improvement:** Add a recency factor to the ranking formula in `current_truth`:
```python
recency = 1.0 / (1 + days_since_creation)  # decay over time
rank = (ps * conf * 0.4) + (similarity * 0.4) + (recency * 0.2)
```

### 4. 🟡 Duplicate Concepts in Graph

**Severity:** MEDIUM — clutters recall and open loops

Multiple "JWT" concepts exist (3 separate nodes with different IDs, all text_raw = "JWT"). Same for "API".

**Evidence:**
```json
{"text_raw": "JWT", "confidence": 0.97, "pathway_strength": 2.35}
{"text_raw": "JWT", "confidence": 0.82, "pathway_strength": 1.51}  
{"text_raw": "JWT", "confidence": 0.82, "pathway_strength": 1.51}
```

**Fix:** Dedup on (text_raw, node_type) before creating new Concept nodes. Or merge during the consolidation loop's Step 6 (arbitration).

### 5. 🟡 Junk Concepts Still Leaking

**Severity:** LOW-MEDIUM — noted in SESSION-STATUS.md, still present

Open loops include:
- `"### Open Loops"` — markdown heading stored as Concept
- `"to persist summaries"` — fragment, not a meaningful entity
- `"last_loop_summary"` — internal variable name
- `"constraints"` — generic word, not a specific constraint
- `"quests"` — generic word

**Fix:** Extend `_is_junk_entity()` in `step1_ner.py`:
- Filter text starting with `#` (markdown headings)
- Filter fragments starting with prepositions ("to ", "for ", "with ")
- Filter snake_case/camelCase strings (code variables)
- Minimum entity length of 3 chars for single-word entities

### 6. 🟡 Zero Edges in Graph

**Severity:** MEDIUM — knowledge graph has nodes but no relationships

The graph API returns 25 nodes but 0 edges. `explore_graph` on the SQLAlchemy Decision found zero neighbors.

**Evidence:**
```json
{"start_node_id": "5f18bd51-...", "start_node_type": "Decision", "nodes": [], "edges": []}
```

**Impact:** Graph traversal is useless without edges. Cross-referencing ("what decisions affect this constraint?") is impossible. The Consolidation Loop's Step 1b (relations) and Step 3b (schema.org relations) may not be creating edges, or they're failing silently.

---

## Architectural Improvements

### 7. 🟢 Keep Legacy SSE Endpoint for Backwards Compatibility

**Severity:** LOW — only needed if ChatGPT Desktop adapter still uses old SSE transport

The old `GET /sse` + `POST /mcp?connection_id=xxx` flow can stay for backwards compat but shouldn't be the primary path. New Streamable HTTP `POST /mcp` (returning `application/json` directly) should be the default.

### 8. 🟢 Consolidation Loop Doesn't Run for New Sessions Without Git Context

**Severity:** MEDIUM — quest_id is empty for non-git sessions

When `notify_turn` is called without `repo_root`, hippocampus routing runs but returns empty quest_id. New conversations from OpenClaw (which has no git context) get messages stored but possibly not linked to any quest.

**Evidence:** Both test stores returned `"quest_id": ""`.

**Fix:** Hippocampus should create a default quest when no match is found, or the OpenClaw extension should call `set_quest` to bind the session first.

### 9. 🟢 Message Count Shows 0 Despite Successful Stores

**Severity:** LOW — stats endpoint may be filtering differently

After successfully storing 4+ messages via `notify_turn`, `/api/stats` still shows `"message": 0`. But concepts went from 20 → 22, confirming ingestion worked.

**Possible cause:** Messages may have `archived=true` by default, or the stats query filters them out. Worth investigating.

### 10. 🟢 OpenClaw Extension Missing Tools

**Severity:** LOW — extension only exposes 5 of 11 Brain tools

The extension registers: `memory_recall`, `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops`.

Missing from extension (but available in Brain):
- `set_quest` — critical for binding sessions to projects
- `explore_graph` — useful for deep dives
- `diff_since` — useful for session handoff
- `branch_quest` — useful for tangent tracking
- `complete_quest` — lesson synthesis
- `ingest_document` — file ingestion

At minimum, `set_quest` and `explore_graph` should be added.

---

## Priority Order

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | Upgrade to Streamable HTTP (server + extension) | Medium | Critical — nothing works without it |
| 2 | Restart daemon for new tools | Trivial | High |
| 6 | Fix zero edges in graph | Medium | High — graph traversal is broken |
| 3 | Improve recall ranking (recency + similarity weight) | Small | High |
| 4 | Deduplicate concepts | Medium | Medium |
| 8 | Fix empty quest_id for non-git sessions | Small | Medium |
| 5 | Extend junk entity filter | Small | Medium |
| 10 | Add missing tools to extension | Small | Low |
| 9 | Fix message count in stats | Trivial | Low |

---

## What Works Well

- **Ingestion pipeline:** `notify_turn` reliably queues messages and runs the consolidation loop
- **Empty content handling:** Gracefully returns `{"status": "skipped", "reason": "empty content"}`
- **Analogical search:** Cross-quest search works and correctly identifies quest associations
- **Open loops surfacing:** Returns unconfirmed concepts with useful metadata (gist_class, schema_org_type)
- **REST API:** Stats, graph, quests, open-loops endpoints all work correctly
- **Memory Control Panel:** Web UI at port 7799 serves properly
- **Diff since:** Returns confirmed artifacts created after a timestamp — useful for handoff

---

## Test Environment

- Brain Daemon: running on port 7799 (macOS, Python 3.14)
- LLM: ollama/qwen2.5:3b (configured in sidequests.toml)
- Embedding: sentence-transformers/all-MiniLM-L6-v2 (384-dim)
- Graph DB: Kùzu 0.11.3
- NLP: spacy en_core_web_md
