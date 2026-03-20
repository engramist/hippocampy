# B17 + B18 Architecture Design

## Deliverables for This Session

1. Save this architecture doc as `B17-B18-architecture.md` in repo root
2. Add B17 and B18 to `backlog.md` under appropriate priority
3. Update memory with session context for follow-up B-plan writing
4. **NOT doing:** Detailed Gemini-ready B-plan files — those come in a follow-up session

---

# B17 — Semantic Quest Routing ("The Hippocampus")

## Context

MainQuest identification currently requires a git repo (`compute_quest_id(repo_root)` → deterministic hash). This works for CLI-in-a-repo but breaks for desktop apps (Claude Desktop, ChatGPT) with multiple threads/projects and non-dev users without git. The fix: a single "Hippocampus" routing mechanism that determines which MainQuest a session belongs to based on **semantic content**, where git context is just one high-confidence signal — not a separate code path.

This is modeled on the human hippocampus: sensory input → associative search → binding to existing memory network, with prediction error / reconsolidation when the binding is wrong.

---

## Architecture: The Hippocampus Router

### Signal Model

Every routing decision consumes a signal vector:

| Signal | Source | Weight | When Available |
|--------|--------|--------|----------------|
| `git_repo_root` | Adapter env | 0.95 | CLI in git repos |
| `content_embedding` | First N message embeddings | Variable (S1/S2) | After 1+ messages |
| `explicit_quest_id` | User calls `set_quest` | 1.0 (override) | Explicit declaration |
| `workspace_path` | CWD without git | 0.70 | CLI outside git |
| `entity_overlap` | Entities matching existing quest concepts | +0.15 boost | After NER (Step 1) |

### Two-Phase Routing (System 1 / System 2)

**On first `notify_turn` for a new session:**

**System 1 (Fast, No LLM):**
1. If `git_repo_root` present → compute legacy hash → check if MainQuest with that ID exists → if yes, bind with confidence 0.95
2. Embed first message → Python-side cosine similarity against all active MainQuest `purpose_embedding` vectors (small cardinality, no HNSW needed)
3. If workspace_path matches an existing `Workspace` node → boost that quest +0.15
4. Thresholds:
   - Best match > 0.85 → auto-bind (System 1 accepted)
   - 0.60–0.85 → escalate to System 2
   - < 0.60 → create new MainQuest (UUID)

**System 2 (LLM Disambiguation):**
1. Top 3 candidates from System 1
2. LLM prompt includes: message content, each candidate's purpose + top 3 recent artifacts
3. LLM returns `{quest_id, confidence, rationale}` or `{new_quest: true}`
4. Bind with `routing_confidence_low = true` if LLM confidence < 0.85

### Progressive Consolidation (Hippocampus → Neocortex)

| State | Meaning | How Reached |
|-------|---------|-------------|
| `tentative` | Initial routing, accumulating evidence | Default for S1 gray-zone and S2 bindings |
| `consolidated` | 3+ confirming signals, routing_strength >= 0.85 | Auto-promoted |
| `locked` | User explicitly confirmed or git-matched | `set_quest` or git match |

**Confirming signals** (strengthen tentative binding):
- Message content similarity to quest purpose > 0.70 (+0.10, up to 5 messages)
- Artifact created linking to existing quest concepts (+0.15)
- User references a known entity from the quest by name (+0.20)
- Git context later becomes available and matches (+0.30)

**Disconfirming signals** (prediction error):
- Message similarity to quest purpose < 0.30 for 3+ consecutive messages
- User explicitly says "this is about X" or "new project"

### Prediction Error / Reconsolidation

1. Detach session from current quest (remove `WORKING_ON` edge)
2. Create `REROUTED_FROM` edge (audit trail)
3. Re-run router with full accumulated session context
4. Weaken false association (Long-Term Depression on purpose embedding)

---

## Schema Changes

### MainQuest — New Properties
```
git_repo_root       STRING     -- nullable, populated for git-anchored quests
purpose_embedding   FLOAT[384] -- dedicated routing embedding, updated as purpose evolves
                               -- NOT HNSW indexed (Python-side search, small cardinality)
routing_method      STRING     -- "git" | "semantic_s1" | "semantic_s2" | "explicit"
```

### Session — New Properties
```
routing_state       STRING     -- "tentative" | "consolidated" | "locked"
routing_confidence  DOUBLE     -- 0.0–1.0, strength of quest binding
routing_method      STRING     -- how this session was routed
content_embedding   FLOAT[384] -- running mean of message embeddings (for re-routing)
```

### New Relationship
```
REROUTED_FROM (FROM Session TO MainQuest)
  rerouted_at TIMESTAMP
  reason STRING
```

### quest_id Format Change
- Existing git-anchored quests: keep deterministic hash IDs (backward compatible)
- New semantically-routed quests: UUID (`str(uuid.uuid4())[:32]`)
- Migration: first time a CLI adapter connects post-upgrade, populate `git_repo_root` on existing quest

---

## New Module: `mcp_engine/hippocampus.py`

```python
async def route_session(db, session_id, content, embedding_model,
                        git_repo_root="", workspace_path="",
                        llm_client=None, config={}) -> RoutingResult:
    """Main entry point. Returns (quest_id, confidence, method, is_new_quest)."""

def _system1_git_match(db, git_repo_root) -> Optional[str]:
    """Check legacy hash match for git-anchored quests."""

def _system1_semantic_match(db, content_embedding, active_quests) -> list[tuple[str, float]]:
    """Cosine similarity against active quest purpose_embeddings."""

async def _system2_disambiguate(llm_client, candidates, content) -> tuple[str, float]:
    """LLM picks the right quest or says 'new'."""

async def create_new_quest(db, content, embedding_model, git_repo_root="") -> str:
    """Create MainQuest with UUID. Returns quest_id."""

async def update_routing_strength(db, session_id, message_embedding,
                                   quest_purpose_embedding) -> float:
    """Called per message. Returns new routing_confidence. Promotes tentative→consolidated."""

async def reconsolidate(db, session_id, new_content, embedding_model,
                        llm_client=None) -> RoutingResult:
    """Re-route after prediction error."""
```

---

## Code Changes

### `mcp_engine/tools.py` — `notify_turn()`
- Remove `if repo_root:` branch
- All sessions go through `hippocampus.route_session()` on first message
- Subsequent messages call `hippocampus.update_routing_strength()`
- Routing is async — `notify_turn` still returns `{"status": "queued"}` immediately

### `mcp_engine/tools.py` — `current_truth()`
- Remove `compute_quest_id(repo_root, git_branch)` fallback
- Resolve quest via `Session -[WORKING_ON]-> MainQuest` traversal
- Falls back to global scope if session has no quest binding yet

### `mcp_engine/tools.py` — New tool: `set_quest`
- Explicit user override to bind session to a named quest
- Creates new quest if name doesn't match existing
- Sets `routing_state = "locked"`, `routing_confidence = 1.0`

### `mcp_engine/quest.py`
- `compute_quest_id()` marked as legacy (kept for backward compat)
- New: `get_active_quests_with_embeddings(db)` — returns active MainQuests + purpose_embeddings
- `get_or_create_main_quest()` supports both legacy hash path and new UUID path

### All Adapters
- `_inject_git_context()` → `_inject_context()` — sends whatever signals are available
- Git context optional, not required
- `set_quest` added to MCP tool lists

### `mcp_engine/schema.py`
- Add new columns to MainQuest and Session DDL
- Add `REROUTED_FROM` relationship
- Migration script for existing databases

---

## Edge Cases

| Case | Resolution |
|------|-----------|
| **Cold start** (no quests) | First message creates new MainQuest with UUID |
| **Two similar quests** | System 2 disambiguates using artifact context; tentative bind to most recent if still ambiguous |
| **Purpose drift** | Re-embed purpose when content diverges > 0.40 from current embedding |
| **"New project"** | User calls `set_quest` or LLM detects via System 2 |
| **Multi-adapter convergence** | Git signal matches existing quest; semantic signal also matches via purpose embedding |
| **Backward compat** | Legacy hash IDs preserved; git_repo_root populated on first post-upgrade use |

---

## Graph Architecture Notes

1. **Purpose embedding NOT HNSW-indexed** — intentional. Active MainQuests will typically number < 50. Python-side cosine similarity is faster than Kùzu index overhead for this cardinality. Avoids the Kùzu 0.11.3 limitation where HNSW-indexed columns cannot be updated in-place.

2. **Routing metadata on Session node, not WORKING_ON edge** — Kùzu 0.11.3 cannot ALTER REL TABLE to add properties. Storing `routing_state`, `routing_confidence`, `routing_method` on the Session node avoids this.

3. **REROUTED_FROM as audit trail** — preserves the full routing history as graph edges. `(Session)-[REROUTED_FROM]->(OldQuest)` alongside `(Session)-[WORKING_ON]->(NewQuest)` gives complete provenance.

4. **Entity overlap signal leverages existing graph** — Step 1 NER extracts entities → check if they have CO_OCCURS_WITH edges to entities in existing quests. This is a 1-hop traversal, not a full search.

---

## IP Claims (New)

1. **Semantic Quest Routing** — context-based routing of conversations to knowledge subgraphs without filesystem anchors
2. **Hippocampus Mechanism** — two-phase (System 1/2) session-to-quest binding with progressive consolidation
3. **Prediction Error Reconsolidation** — automatic re-routing with Long-Term Depression on false associations
4. **Multi-Signal Routing Fusion** — combining git context, semantic similarity, entity overlap, and workspace path into a unified routing confidence score

---

## Implementation Sequence

1. Schema migration (new properties on MainQuest, Session; REROUTED_FROM rel)
2. `mcp_engine/hippocampus.py` — core routing logic (System 1 first, then System 2)
3. Refactor `mcp_engine/quest.py` — legacy compat + UUID path + `get_active_quests_with_embeddings()`
4. Wire `notify_turn` and `current_truth` through hippocampus
5. Add `set_quest` tool to tools.py + all adapter tool lists
6. Update adapters: `_inject_git_context` → `_inject_context`
7. Tests: `tests/test_hippocampus.py` + update `tests/test_quest.py`
8. CLAUDE.md update with new architecture docs

## Verification

- **Unit tests**: System 1 git match, System 1 semantic match, System 2 disambiguation, consolidation state transitions, reconsolidation
- **Integration test**: notify_turn without git context → quest created → second session about same topic → routed to same quest
- **Backward compat test**: existing git-anchored quest still resolves correctly post-migration
- **Multi-adapter test**: Claude Code (git) and Claude Desktop (no git) converge on same quest
- **Prediction error test**: session bound to wrong quest → user corrects → REROUTED_FROM edge created → re-bound correctly

---
---

# B18 — Context Window Awareness ("Working Memory")

## Context

The Brain knows sessions exist but not **what's loaded in each LLM's context window**. This means `current_truth` can re-inject the same facts repeatedly, the Brain can't detect context bloat, and session handoffs lose track of what the LLM already knows. B18 models each Session as a working memory buffer — tracking what's been loaded, estimating token usage, and enabling smart deduplication.

Designed alongside B17 (Hippocampus) — B17 decides *which quest* a session belongs to; B18 tracks *what that session currently knows*.

---

## The Biological Parallel

| Brain Structure | SideQuests Equivalent | Role |
|----------------|----------------------|------|
| **Prefrontal cortex** (working memory) | LLM context window / Session | Holds currently active information |
| **Hippocampus** (routing/binding) | B17 Hippocampus Router | Decides where new info goes |
| **Neocortex** (long-term storage) | Kùzu graph | Permanent knowledge store |
| **Sensory input** | `notify_turn` messages | Raw incoming information |
| **Recall** | `current_truth` responses | Loading from long-term → working memory |

The LLM's context window IS working memory. B18 gives the Brain visibility into what's currently "in mind" for each active session — enabling efficient memory management rather than blind injection.

---

## Session as Context Window

Every Session node maps 1:1 to an LLM context window:

| LLM | New context window = | Session ID source |
|-----|---------------------|-------------------|
| Claude Code | New CLI invocation | Auto-generated per invocation |
| Claude Desktop | New conversation thread | Thread ID |
| ChatGPT Desktop | New conversation | Conversation ID |
| Codex | New task | Task ID |
| Gemini CLI | New invocation | Auto-generated |

Detection is already built — a new `session_id` in `notify_turn` = new context window. B18 enriches what we track about each session.

---

## Schema Changes

### Session — New Properties (additive to B17)
```
token_estimate      INT64      -- estimated total tokens in context window
token_limit         INT64      -- model's context window size (from LLMProvider)
loaded_node_count   INT32      -- number of graph nodes currently in working memory
last_injection_at   TIMESTAMP  -- when current_truth last returned results
```

### New Relationship: LOADED
```
CREATE REL TABLE IF NOT EXISTS LOADED (
    FROM Session TO Concept,
    FROM Session TO Decision,
    FROM Session TO Constraint,
    FROM Session TO Requirement,
    FROM Session TO ActionItem,
    FROM Session TO GlobalConstraint,
    FROM Session TO GlobalPreference,
    injected_at TIMESTAMP,
    token_estimate INT32,
    source STRING              -- "current_truth" | "system_prompt" | "onboarding"
)
```

Each `LOADED` edge = "this graph node's content is currently in this LLM's context window."

---

## Core Mechanisms

### 1. Load Tracking (on `current_truth` response)

When `current_truth` returns results, create `LOADED` edges for each returned node:

```python
async def track_loaded(db, session_id, results, source="current_truth"):
    """Record which nodes were injected into the context window."""
    for r in results:
        await db.execute_write("""
            MATCH (s:Session {session_id: $sid}), (n {node_id: $nid})
            MERGE (s)-[l:LOADED]->(n)
            ON CREATE SET l.injected_at = timestamp($now),
                          l.token_estimate = $tokens,
                          l.source = $source
            ON MATCH SET  l.injected_at = timestamp($now)
        """, {...})
    # Update session token estimate
    await _update_token_estimate(db, session_id, results)
```

### 2. Smart Deduplication (in `current_truth`)

Before returning results, check what's already loaded:

```python
async def current_truth_deduplicated(params, db, config):
    """current_truth with working memory awareness."""
    results = await current_truth(params, db, config)  # existing logic

    already_loaded = await get_loaded_node_ids(db, session_id)

    # Don't exclude loaded nodes — demote them in ranking
    for r in results:
        if r["node_id"] in already_loaded:
            r["already_in_context"] = True
            r["relevance_score"] *= 0.3  # heavily demote, don't hide

    # Re-sort by adjusted relevance
    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return results
```

**Why demote, not exclude:** The LLM might need a refresher on a loaded fact if the conversation has moved on. But fresh information should rank higher than re-injections.

### 3. Token Estimation

Simple heuristic — no tokenizer dependency:

```python
def estimate_tokens(text: str) -> int:
    """~4 chars per token for English, conservative."""
    return len(text) // 3  # slightly conservative to avoid undercount

async def get_session_token_state(db, session_id) -> dict:
    """Returns current token usage vs. limit."""
    return {
        "estimated_tokens": session.token_estimate,
        "token_limit": session.token_limit,
        "utilization": session.token_estimate / session.token_limit,
        "loaded_nodes": session.loaded_node_count,
    }
```

### 4. Bloat Detection

When token utilization exceeds a threshold, surface a warning:

```python
BLOAT_WARNING_THRESHOLD = 0.75  # 75% of context window used

async def check_context_health(db, session_id) -> Optional[str]:
    """Returns warning message if context is getting bloated."""
    state = await get_session_token_state(db, session_id)
    if state["utilization"] > BLOAT_WARNING_THRESHOLD:
        return (f"Context window is {state['utilization']:.0%} full "
                f"({state['estimated_tokens']}/{state['token_limit']} tokens). "
                f"Consider starting a fresh conversation.")
    return None
```

This warning can be surfaced in the system prompt fragment (B14 Proactive Insight Surfacing) or as metadata on `current_truth` responses.

### 5. Session Handoff Intelligence

When a new session starts for the same quest, the Brain knows what was loaded in the PREVIOUS session:

```python
async def get_handoff_context(db, quest_id, new_session_id) -> list:
    """What does the new session need from the old one?"""
    # Find most recent prior session on this quest
    prev_session = await get_previous_session(db, quest_id, new_session_id)
    if not prev_session:
        return []

    # Get what was loaded in the old session, ranked by pathway_strength
    prev_loaded = await get_loaded_nodes(db, prev_session.session_id)

    # Return top N most important nodes from prior session
    # These are candidates for proactive injection into the new session
    return sorted(prev_loaded, key=lambda n: n["pathway_strength"], reverse=True)[:5]
```

---

## How B18 Connects to B17 (Hippocampus)

| B17 Signal | B18 Enhancement |
|------------|----------------|
| `content_embedding` (routing) | More accurate — B18 tracks all loaded content, not just messages |
| Consolidation strength | Loaded node count confirms quest match (many loaded nodes from quest X = strong binding) |
| Prediction error detection | Divergence between loaded nodes (from quest X) and new message content (about quest Y) |
| `current_truth` scoping | B18 prevents redundant injection, making branch-scoped results more efficient |

---

## New MCP Tool: `context_status`

```json
{
  "name": "context_status",
  "description": "Check the health of the current context window — token usage, loaded knowledge, and handoff suggestions.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "session_id": {"type": "string"}
    },
    "required": ["session_id"]
  }
}
```

Response:
```json
{
  "token_estimate": 45000,
  "token_limit": 128000,
  "utilization": 0.35,
  "loaded_nodes": 12,
  "bloat_warning": null,
  "handoff_available": true,
  "handoff_nodes": 5
}
```

---

## IP Claims (New)

5. **Context Window as Working Memory Model** — modeling each LLM session as a tracked working memory buffer with load/unload semantics
6. **Smart Deduplication via Load Tracking** — demoting (not excluding) already-loaded graph nodes in retrieval results
7. **Session Handoff Intelligence** — proactive knowledge transfer between context windows using load history from prior sessions
8. **Bloat Detection via Token Estimation** — monitoring context window utilization and surfacing efficiency warnings

---

## Implementation Sequence (B18)

1. Schema additions (Session properties + LOADED relationship)
2. Load tracking in `current_truth` response path
3. Smart deduplication in `current_truth` query path
4. Token estimation utility
5. Bloat detection + `context_status` tool
6. Session handoff logic
7. Tests: `tests/test_working_memory.py`

## Verification (B18)

- **Load tracking test**: `current_truth` returns 5 nodes → 5 LOADED edges created → second `current_truth` demotes those 5
- **Token estimation test**: session tracks cumulative tokens across messages and injections
- **Bloat detection test**: session at 80% utilization → warning surfaced
- **Handoff test**: new session on same quest → top 5 nodes from prior session returned as handoff candidates
- **Deduplication test**: same query twice in one session → second response ranks fresh nodes higher

---

## Dependency Map

```
B17 (Hippocampus)          B18 (Working Memory)
    │                           │
    ├── Schema changes ◄────────┤  (Session node shared, additive properties)
    ├── hippocampus.py          ├── working_memory.py
    ├── quest.py refactor       ├── current_truth dedup
    ├── notify_turn rewire ◄────┤  (notify_turn updates token estimates)
    ├── set_quest tool          ├── context_status tool
    └── Adapter changes ◄───────┘  (adapters send token_limit from LLMProvider)
```

Both B-plans modify `notify_turn`, `current_truth`, Session schema, and adapters — implement B17 first, then B18 layers on top.
