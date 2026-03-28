# B29: Cross-Session Context Awareness — Test Harness

## Goal
Define and enforce an end-to-end cross-session recall test: session A stores a decision;
session B starts with a fresh session ID and queries `current_truth`; session B must retrieve
session A's decision without any shared context window.

This test is a **hard gate** — it must pass before claiming OpenClaw memory continuity.

## Root Causes (from B29 analysis)

1. **`notify_turn` enrichment gap** — `notify_turn` writes a `Message` node, but `current_truth`
   does NOT search the `Message` table. Decisions said in conversation land in `Message` but
   are only promoted to artifact nodes (Decision, Constraint, Concept) by the Gated
   Consolidation Loop (M3+). In the meantime, a query by session B won't find them.

2. **Loop queue required** — to be searchable in `current_truth`, content from session A must
   be processed by the Loop (Step 1 NER → Step 4 confidence gate → Step 7 pathway update),
   producing a `Concept` node with embedding.

3. **Auto-recall fires before session B is linked** — `before_agent_start` fires with a fresh
   `session_id` that has no `WORKING_ON` edge yet and no prior `notify_turn` call, so
   `current_truth` can't resolve quest scope via the session. Scope falls back to global,
   which is correct behavior — but the test must confirm it actually returns the cross-session
   artifact.

4. **Agent instructs**: agent defaults to reading markdown files instead of calling
   `current_truth` when asked about recent work. This is an agent behavior issue tested
   separately (B17 system prompt layer). B29 focuses on the mechanical plumbing only.

## What This Plan Covers

- A new test file: `tests/test_cross_session_recall.py`
- Unit tests that bypass the live daemon — use direct `current_truth()` function call with
  a real (temp) Kùzu DB seeded with a known artifact node
- Integration contract assertions on the extension TypeScript: confirm `before_agent_start`
  uses `scope: "both"` (not "branch") when `session_id` is fresh
- Do NOT require a running Brain Daemon or OpenClaw — tests must be fully offline

## Files to Create / Modify

### New file: `tests/test_cross_session_recall.py`

Contains four test cases. All use `pytest`, `pytest-asyncio`, and a real in-process Kùzu
temp DB via the existing schema init path (same pattern as `tests/test_retrieval.py`
`MockVectorSearchDB` for pure unit tests, or direct `KuzuClient` with tmp_path for
integration tests).

---

### Test 1: `test_cross_session_artifact_is_retrievable`

**What it tests:** A Concept node written by session A is returned by `current_truth`
when session B passes a semantically similar query with a fresh session ID.

**Setup:**
1. Create a temp Kùzu DB using `tmp_path` and `mcp_engine.schema.init_schema(db)`.
2. Directly insert a `Concept` node with:
   - `concept_id = "test-decision-001"`
   - `text_raw = "We decided to use Streamable HTTP for MCP transport"`
   - `embedding` = embed the above text with `mcp_engine.graph.embeddings.embed()`
   - `pathway_strength = 0.85`, `confidence = 0.90`, `confidence_low = False`, `archived = False`
3. Create a `MainQuest` node with `quest_id = "test-quest-001"`, `status = "active"`.
4. Create a `Session` node with `session_id = "session-A-001"`, linked via `WORKING_ON` to the quest.
5. Link the Concept to the quest via a `SideQuest` or directly — actually, the quest link
   is only needed when scope is "branch". Use `scope = "both"`.

**Test body:**
```python
from mcp_engine.tools import current_truth

result = await current_truth(
    {
        "query": "What transport protocol did we choose?",
        "session_id": "session-B-fresh-001",  # different from session A
        "scope": "both",
        "limit": 5,
    },
    db,
    config,
)

assert len(result["results"]) >= 1
top = result["results"][0]
assert "Streamable HTTP" in top["text_raw"] or "transport" in top["text_raw"].lower()
assert top["similarity"] > 0.5   # must be semantically found, not just highest by default
assert top["archived"] is False
```

---

### Test 2: `test_cross_session_archived_node_excluded`

**What it tests:** An archived node from session A does NOT appear in session B's
`current_truth` results even if it's semantically similar.

**Setup:** Same as Test 1 but set `archived = True` on the concept.

**Test body:**
```python
result = await current_truth(
    {
        "query": "What transport protocol did we choose?",
        "session_id": "session-B-fresh-002",
        "scope": "both",
        "limit": 5,
    },
    db,
    config,
)

# Archived node must be excluded
node_ids = [r["node_id"] for r in result["results"]]
assert "test-decision-001" not in node_ids
```

---

### Test 3: `test_cross_session_confidence_low_node_is_included_but_flagged`

**What it tests:** A `confidence_low = True` node from session A IS returned (sessions
shouldn't lose access to tentative knowledge) but the `confidence_low` flag is preserved
in the result.

**Setup:** Same as Test 1 but set `confidence_low = True`, `pathway_strength = 0.3`.

**Test body:**
```python
result = await current_truth(
    {
        "query": "What transport protocol did we choose?",
        "session_id": "session-B-fresh-003",
        "scope": "both",
        "limit": 5,
    },
    db,
    config,
)

nodes = [r for r in result["results"] if "Streamable HTTP" in r.get("text_raw", "")]
assert len(nodes) >= 1
assert nodes[0]["confidence_low"] is True
```

---

### Test 4: `test_auto_recall_scope_is_both` (source-inspection test)

**What it tests:** The `before_agent_start` hook in `index.ts` uses `scope: "both"` — not
`"branch"` — when calling `current_truth`. A fresh session has no `WORKING_ON` edge, so
branch scope would return 0 results. This ensures the recall actually fires globally.

**Implementation:** Source inspection (no live TS needed).

```python
def test_auto_recall_scope_is_both():
    from pathlib import Path
    src = Path("extensions/sidequests-brain/src/index.ts").read_text()
    
    # Find the before_agent_start handler block
    before_agent_idx = src.index('OPENCLAW_EVENT_CONTRACT.preAgentEvent')
    # Get the next usage (the api.on call)
    api_on_idx = src.index('api.on(OPENCLAW_EVENT_CONTRACT.preAgentEvent')
    handler_block = src[api_on_idx:api_on_idx + 600]
    
    # Must use scope: "both" so fresh sessions get global results
    assert '"both"' in handler_block, (
        "before_agent_start auto-recall must use scope: 'both' — "
        "fresh sessions have no WORKING_ON edge and branch scope returns 0 results"
    )
```

---

## KuzuClient + Schema Setup Pattern

Use the following helper (add as a module-level fixture in the test file):

```python
import pytest
import tempfile
import os

@pytest.fixture
def db_with_schema(tmp_path):
    """Real Kùzu DB in a temp dir with schema initialized."""
    from mcp_engine.graph.kuzu_client import KuzuClient
    from mcp_engine.schema import init_schema
    
    db_path = str(tmp_path / "test.db")
    db = KuzuClient(db_path)
    init_schema(db)
    yield db
    db.close()
```

Use `db_with_schema` fixture in Tests 1–3. For embedding, call:
```python
from mcp_engine.graph.embeddings import embed
vector = embed("We decided to use Streamable HTTP for MCP transport")
```
The vector must be inserted as a list of floats matching the FLOAT[384] schema.

Config fixture:
```python
config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
```

---

## Write approach for Concept node insertion

Use `db.execute_write()` directly — not the tools layer — to set up ground truth:
```python
db.execute_write(
    """
    CREATE (c:Concept {
        concept_id: 'test-decision-001',
        text_raw: 'We decided to use Streamable HTTP for MCP transport',
        embedding: $emb,
        embedding_model: 'sentence-transformers/all-MiniLM-L6-v2',
        embedding_dim: 384,
        gist_class: 'gist:PlannedEvent',
        schema_org_type: 'schema:Action',
        confidence: 0.90,
        confidence_low: false,
        pathway_strength: 0.85,
        archived: false,
        created_at: timestamp('2026-01-01T00:00:00.000')
    })
    """,
    {"emb": vector}
)
```

HNSW index must exist before vector_search works. `init_schema` creates it.
But in Kùzu, the HNSW index only covers nodes that existed at index creation time
when calling `CREATE VECTOR INDEX`. Nodes inserted AFTER index creation are picked up
automatically in Kùzu 0.11.3's HNSW. Confirm this assumption holds — if it doesn't,
use a `MockVectorSearchDB` approach instead (see `test_retrieval.py`).

**Fallback (if HNSW doesn't auto-index new nodes):** Use the `MockVectorSearchDB`
pattern from `test_retrieval.py`. Calculate the similarity score manually using
cosine similarity between the query embedding and the node embedding, and inject it
as the score in the mock return. This is the safe fallback.

Use the mock approach as primary implementation — it's faster and doesn't depend
on Kùzu HNSW index behavior details.

---

## Implementation Notes for Gemini

- Import `current_truth` from `mcp_engine.tools` directly, same as `test_retrieval.py`
- The `db` parameter to `current_truth` must implement `vector_search(table, index, vec, limit)` and `execute(query, params)` — use the MockVectorSearchDB + a minimal mock for `execute` that returns empty  `Session → WORKING_ON` lookups (since session-B is fresh, no WORKING_ON link exists):
  ```python
  class MockDB(MockVectorSearchDB):
      def execute(self, query, params=None):
          return MockResult([])  # No session/quest links for fresh session
  ```
  Where `MockResult` has `has_next()` → False.

- **Do not** try to mock the embedding call — call `embed()` for real to get a 384-dim vector. This will download the model on first run (adds ~30s to CI). Add a module-level skip guard:
  ```python
  try:
      from mcp_engine.graph.embeddings import embed as _embed_check
      _embed_check("test")
      EMBEDDINGS_AVAILABLE = True
  except Exception:
      EMBEDDINGS_AVAILABLE = False
  ```
  Then mark Tests 1–3 with: `@pytest.mark.skipif(not EMBEDDINGS_AVAILABLE, reason="embeddings not available")`

- Test 4 (`test_auto_recall_scope_is_both`) is a pure source inspection — no embedding needed, always runs.

---

## Acceptance Criteria

- [ ] `pytest tests/test_cross_session_recall.py -q` → all tests pass (or skip with embeddings unavailable)
- [ ] `test_auto_recall_scope_is_both` always passes regardless of embeddings availability
- [ ] Tests do not require a running Brain Daemon or OpenClaw TUI
- [ ] No new production code changes (this is a test-only card)
- [ ] The fixture uses `tmp_path` (no leftover DB files after test run)

---

## What B29 Does NOT Fix

- Agent defaulting to markdown memory files instead of `current_truth` — that's B17 (system prompt layer)
- Live cross-session recall in OpenClaw sessions — that's the live validation at the end of B29 (manual)
- Loop processing pipeline (M3) — the test uses manually seeded Concept nodes, not Loop-processed Messages

---

## Gemini Delegation Command

```bash
cd /Users/djshelton/Desktop/GitProjects/sidequests-brain && gemini -p "Read B-29-cross-session-recall-test.md and implement exactly as specified. Read tests/test_retrieval.py for the MockVectorSearchDB pattern. Read mcp_engine/tools.py lines 209-380 for the current_truth signature. Implement only the new test file tests/test_cross_session_recall.py — no production code changes. Follow the mock approach for DB (do not rely on real Kùzu HNSW index). Run pytest tests/test_cross_session_recall.py after writing." --yolo 2>&1
```
