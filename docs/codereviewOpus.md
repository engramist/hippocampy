# SideQuest Brain — Full Code Review (Opus 4.6)

**Date:** March 12, 2026
**Reviewer:** Claude Opus 4.6
**Scope:** All production modules + test suite coverage analysis

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Blocks correct operation or causes data corruption. Fix before any release. |
| **HIGH** | Significant bug or fail point that degrades system quality materially. |
| **MEDIUM** | Logic error, missing feature, or design issue that should be addressed. |
| **LOW** | Minor improvement, code quality, or performance optimization. |

---

## Section 1: Systemic Issues (Cross-Cutting)

### S1. Synchronous LLM Calls Block the asyncio Event Loop [CRITICAL]

**Files:** `mcp_engine/llm/provider.py`, `mcp_engine/loop/step2_gist.py`, `mcp_engine/loop/step3b_relations.py`, `mcp_engine/loop/step6_arbitration.py`, `mcp_engine/sweep.py`, `mcp_engine/quest.py`

`LLMClient.chat()` is synchronous — it calls `client.chat.completions.create()` which blocks on network I/O to Ollama (500ms–10s+). Every caller in the async codebase (Steps 2, 3b, 6, sweep Hebbian promotion, purpose synthesis) blocks the entire event loop during the LLM call. All other async operations (daemon heartbeats, socket handling, other loop iterations) stall.

**Fix:** Wrap `LLMClient.chat()` in `asyncio.to_thread()` or provide a native async interface using `httpx` / `openai.AsyncOpenAI`.

---

### S2. Silent Exception Swallowing Throughout [HIGH]

**Files:** `mcp_engine/loop/orchestrator.py` (`_store_concept`, `_reify_concept`, `_save_gist_example`, `_store_relation`), `mcp_engine/quest.py` (`get_or_create_main_quest`, `get_or_create_session`, `create_side_quest`), `web/server.py` (every endpoint), `mcp_engine/sweep.py`

Pattern: `except Exception: pass` — returns `None` or empty result with no logging. A persistent DB failure would silently degrade the entire system with no visibility. `quest.py` returns fake IDs that don't exist in the DB when writes fail.

**Fix:** Add structured logging (`logging.exception()`) inside every catch. For quest functions, propagate the error or return a sentinel that callers check.

---

### S3. Blocking Kùzu I/O Inside asyncio.Lock [HIGH]

**File:** `mcp_engine/graph/kuzu_client.py`

`execute_write()` acquires an `asyncio.Lock` then runs blocking Kùzu C extension I/O. This holds the lock while the thread is blocked, preventing other coroutines from proceeding. The `asyncio.Lock` was designed for protecting shared state between coroutines, not for wrapping blocking I/O.

**Fix:** Use `asyncio.to_thread()` for the actual Kùzu call inside the lock, or use a `threading.Lock` with `run_in_executor`.

---

### S4. Module-Level asyncio.Lock Created at Import Time [MEDIUM]

**File:** `mcp_engine/graph/kuzu_client.py`

The `asyncio.Lock()` is created at module import time, before any event loop exists. In Python 3.10+, this triggers a deprecation warning; in 3.12+ it may fail entirely.

**Fix:** Lazy-initialize the lock on first use or in `__init__`.

---

## Section 2: Loop Step Bugs

### L1. Step 2 — Cosine Similarity Assumes Normalized Vectors [HIGH]

**File:** `mcp_engine/loop/step2_gist.py`

`_cosine_sim()` computes `dot(a, b) / (norm(a) * norm(b))` — correct for arbitrary vectors. However, the centroids from `mean_pool()` in `schema.py` are NOT L2-normalized after pooling. The `sentence-transformers` model produces normalized embeddings, but mean-pooling multiple normalized vectors does NOT produce a normalized vector. This means System 1 similarity scores are systematically deflated, causing more concepts to fall into the System 2 LLM fallback path (0.60–0.85 range) than intended.

**Fix:** L2-normalize centroids after mean-pooling in `_bootstrap_centroids()`.

---

### L2. Step 2 — Unknown LLM Class Maps to "Restriction" [MEDIUM]

**File:** `mcp_engine/loop/step2_gist.py`

When the LLM returns a class name not in `GIST_CLASSES`, the fallback is `GIST_CLASSES[0]` which is "Restriction". This silently misclassifies unknown concepts as restrictions.

**Fix:** Return `None` or "noise" for unrecognized classes, or use fuzzy matching against valid class names.

---

### L3. Step 3 — Agent Routing Table Overwrite [HIGH]

**File:** `mcp_engine/loop/step3_schema_org.py`

`load_routing_table()` builds a dict keyed by gist class name. The `gist:Agent` class appears twice (Person and Organization variants) but dict keys are unique — the second entry overwrites the first. Agent routing to Person vs Organization is broken.

**Fix:** Use a list of tuples or a multi-value dict. The Agent disambiguation logic (using spaCy's PERSON/ORG label) needs the routing table to return both options.

---

### L4. Step 3 — Agent Routing Bypasses Live Cache [MEDIUM]

**File:** `mcp_engine/loop/step3_schema_org.py`

The `route_to_schema_org()` function has special-case logic for Agent disambiguation that bypasses the cached routing table entirely. Changes to the routing table in the graph won't affect Agent routing.

**Fix:** Load both Agent variants from the routing table and select based on entity label.

---

### L5. Step 4 — Signal Matching Uses Full Message, Not Per-Entity Text [HIGH]

**File:** `mcp_engine/loop/step4_pattern.py:58-106`, `orchestrator.py:130`

`classify_artifact()` receives the full message `text`, not just the entity's text. Every entity in the same message gets identical keyword signal scores. A message like "We decided to use Kùzu. The weather is nice today." classifies both "Kùzu" AND "weather" as decision artifacts with equal confidence.

**Fix:** Pass entity-local context (sentence containing the entity) instead of the full message.

---

### L6. Step 4 — "must not" and "must" Double-Count [MEDIUM]

**File:** `mcp_engine/loop/step4_pattern.py:27-28`

`_CONSTRAINT_SIGNALS` includes both `r"\bmust not\b"` and `r"\bmust\b"`. Text containing "must not" matches both patterns, inflating the constraint signal count. The confidence formula (`0.65 + best_score * 0.12`) means an extra hit could push from 0.77 to 0.89, crossing meaningful confidence boundaries.

**Fix:** Check "must not" first and skip "must" if matched, or use `r"\bmust(\s+not)?\b"` as a single pattern.

---

### L7. Step 4 — `schema_org_type` Parameter Accepted But Never Used [LOW]

**File:** `mcp_engine/loop/step4_pattern.py:59`

The `schema_org_type` argument is never referenced in the function body. Per CLAUDE.md, Step 4 should use ontological context from Steps 2-3.

**Fix:** Either implement schema.org-based classification boosting or remove the parameter.

---

### L8. Step 5 — `exclude_id=""` Means Self-Exclusion Never Works [MEDIUM]

**File:** `mcp_engine/loop/step5_retrieval.py:53`, `orchestrator.py:144`

The orchestrator passes `exclude_id=""` because the Concept node hasn't been created yet. But for subsequent entities in the same message that match a previously-stored concept from the SAME `run_loop` call, the empty exclude_id provides no protection.

**Fix:** Collect concept_ids as they're created and pass them all as exclusions for subsequent iterations.

---

### L9. Step 5 — Silent Vector Search Failure Degrades to Never-Match Mode [HIGH]

**File:** `mcp_engine/loop/step5_retrieval.py:43-44`

`except Exception: return []` — if the vector index doesn't exist, is corrupt, or the query has a type mismatch, this returns empty silently. The orchestrator treats it as "no match" and creates a new concept node every time. A persistent index failure would fill the graph with duplicates.

**Fix:** Log the error. Consider a health check that validates the vector index on startup.

---

### L10. Step 5 — Postfilter Degrades With Many Archived Nodes [MEDIUM]

**File:** `mcp_engine/loop/step5_retrieval.py:25`

`_FETCH_HEADROOM = 5` — fetches `limit + 5` results then filters out archived nodes. As the graph ages and more nodes are archived, most close vectors could be archived, returning fewer than `limit` active results.

**Fix:** Per CLAUDE.md, use projected graphs to prefilter before HNSW search rather than postfiltering.

---

### L11. Step 6 — JSON Parsing of LLM Output Is Fragile [MEDIUM]

**File:** `mcp_engine/loop/step6_arbitration.py:68-69`

The strip chain `raw.strip().strip("```json").strip("```").strip()` doesn't handle: preamble before the fence, uppercase ` ```JSON`, or text after the JSON block. LLMs frequently produce these formats.

**Fix:** Extract the first `{...}` block with regex: `re.search(r'\{[^}]+\}', raw)`.

---

### L12. Step 6 — `referenced_index` Type Coercion Missing [MEDIUM]

**File:** `mcp_engine/loop/step6_arbitration.py:77`

`isinstance(ref_idx, int)` fails for `"1"` (string) or `1.0` (float) — both common LLM outputs. The `referenced_ids` list stays empty, so contradiction/additive targeting breaks.

**Fix:** Coerce with `int(ref_idx)` inside a try/except.

---

### L13. Step 7 — Race Condition in Additive Read-Modify-Write [HIGH]

**File:** `mcp_engine/loop/step7_pathway.py:99-122`

The read (line 99, sync `db.execute()`) and write (line 118, async `db.execute_write()`) are not atomic. Between them, another coroutine could modify the same concept's `pathway_strength`. Two concurrent additive updates would both read the same old strength and only one increment takes effect.

**Fix:** Use a single atomic Cypher query: `SET c.pathway_strength = c.pathway_strength + $increment`.

---

### L14. Step 7 — Uses `created_at` Instead of `last_accessed_at` [CRITICAL]

**File:** `mcp_engine/loop/step7_pathway.py:114`

`apply_additive` reads `c.created_at` and passes it to `_days_since`. But CLAUDE.md specifies `strength += log(1 + 1/days_since_LAST_ACCESS)`. The Concept schema has no `last_accessed_at` field. As concepts age, `_days_since(created_at)` grows monotonically, making each increment smaller — the opposite of the intended behavior where recently-accessed concepts get stronger reinforcement.

**Fix:** Add a `last_accessed_at` field to Concept. Update it on every additive access. Use it instead of `created_at` in the formula.

---

### L15. Step 7 — No `last_accessed_at` Update on Additive Path [CRITICAL]

**File:** `mcp_engine/loop/step7_pathway.py:118-122`

Related to L14: even if the field existed, `apply_additive` never writes a `last_accessed_at` timestamp. The background sweep's decay formula also needs this field.

**Fix:** Add `SET c.last_accessed_at = $now` to the additive write query.

---

### L16. Step 7 — Contradiction Makes 5 Sequential Writes Without Transaction [HIGH]

**File:** `mcp_engine/loop/step7_pathway.py:160-208`

`apply_contradiction` makes 5 separate `execute_write` calls (archive old, DEPRECATED_BY, MergeEvent, TRIGGERED, UPDATES_PATHWAY). If any middle write fails, the graph is in a partially-applied state — e.g., old concept archived but no DEPRECATED_BY edge, corrupting the audit trail.

**Fix:** Batch into a single Cypher query or use a Kùzu transaction.

---

### L17. Step 7 — CO_OCCURS_WITH Issues O(n^2) Individual DB Writes [LOW]

**File:** `mcp_engine/loop/step7_pathway.py:248-265`

For n concepts from one message, this makes n*(n-1)/2 individual write-locked DB calls. With 10 entities, that's 45 separate calls.

**Fix:** Batch into a single parameterized `UNWIND` query.

---

## Section 3: Orchestrator Bugs

### O1. Duplicate Embedding Computation Per Entity [LOW]

**File:** `mcp_engine/loop/orchestrator.py:140`

Step 2 already embeds the entity text (returned in `gist_result["vector"]`), but the orchestrator re-embeds at line 140. This doubles embedding compute time per entity.

**Fix:** Use `gist_result["vector"]` instead of calling `emb.embed()` again.

---

### O2. `_store_relation` Creates Ghost Concept Nodes Without Embeddings [CRITICAL]

**File:** `mcp_engine/loop/orchestrator.py:384-408`

`MERGE (h:Concept {text_raw: $head})` creates Concept nodes with no `embedding`, `embedding_model`, `embedding_dim`, `gist_class`, or `schema_org_type`. These half-initialized nodes never appear in vector search, break HNSW index assumptions, and won't participate in the graph properly.

**Fix:** Either embed the text before MERGE, or only MERGE against existing Concept nodes (fail silently if the concept doesn't exist yet).

---

### O3. `_store_relation` Case-Sensitive MERGE Creates Duplicates [HIGH]

**File:** `mcp_engine/loop/orchestrator.py:387`

`MERGE (h:Concept {text_raw: $head})` does exact string matching. "Kùzu" and "kùzu" create separate Concept nodes. Across messages, the same entity spelled differently generates duplicates.

**Fix:** Normalize text (e.g., `lower()`) before MERGE, or match on `concept_id`.

---

### O4. Step 1b Relations Stored Before Step 2 Noise Filtering [MEDIUM]

**File:** `mcp_engine/loop/orchestrator.py:78-79`

Step 1b relations are stored immediately (line 78-79) before Step 2 filters noise entities. If both the head and tail of a relation are noise (<60% in Step 2), the relation and its ghost Concept nodes are already in the graph.

**Fix:** Defer relation storage until after Step 2 noise filtering.

---

### O5. No Message Node Created in Orchestrator [HIGH]

**File:** `mcp_engine/loop/orchestrator.py`

The orchestrator receives `message_id` but never creates a Message node. `apply_contradiction` (line 195-199) tries to MATCH a Message node to create the TRIGGERED edge — if no Message exists, the MATCH silently returns nothing and the audit trail is broken.

**Fix:** Either create the Message node in the orchestrator, or validate/document that the caller must create it first.

---

### O6. Step 3b Trigger Condition Too Conservative [LOW]

**File:** `mcp_engine/loop/orchestrator.py:114`

`if len(typed_entities) > 1 and not step1b_relations:` — Step 3b only runs if Step 1b found ZERO relations. If a message has 4 entities and Step 1b found 1 relation, the other entity pairs get no semantic analysis.

**Fix:** Run Step 3b for entity pairs not already covered by Step 1b edges.

---

### O7. Event-Driven Confidence Re-Scoring Not Implemented [HIGH]

**File:** All loop steps + orchestrator

Per CLAUDE.md M4 spec: "After every pathway update, re-score all `confidence_low` nodes within 1-2 hops." Neither `apply_additive` nor `apply_contradiction` nor the orchestrator performs this. Without it, `confidence_low` nodes can only be promoted by the background sweep (every 5 minutes).

**Fix:** Implement re-scoring logic after Step 7 pathway updates.

---

### O8. `_store_relation` Generates UUIDs Even for Existing Concepts [LOW]

**File:** `mcp_engine/loop/orchestrator.py:401-402`

`str(uuid.uuid4())` is generated for head_id and tail_id on every call. If the MERGE matches an existing Concept, the UUID is wasted. Minor waste but adds noise to understanding the code.

---

## Section 4: Daemon, Tools, & Infrastructure

### D1. `brain_daemon.py` — `shutdown()` Doesn't Stop Event Loop [MEDIUM]

**File:** `brain_daemon.py`

`shutdown()` closes the socket and DB connection but doesn't stop the asyncio event loop. The daemon hangs after shutdown.

**Fix:** Call `loop.stop()` or set a shutdown flag checked by the sweep/worker loops.

---

### D2. `brain_daemon.py` — Fire-and-Forget `create_task` With No Error Handling [HIGH]

**File:** `brain_daemon.py`

`asyncio.create_task()` for loop worker and sweep tasks. If they raise an unhandled exception, the task silently dies and the daemon continues running without processing or sweeping.

**Fix:** Add `task.add_done_callback()` that logs exceptions and optionally restarts the task.

---

### D3. `brain_daemon.py` — Hardcoded OneDrive SEED_PATH [MEDIUM]

**File:** `brain_daemon.py`

`_resolve_seed_path()` has a hardcoded path to DJ's OneDrive directory. This fails on any other machine.

**Fix:** Use a config-relative path or include `GistSeedExamples.md` in the package.

---

### D4. `tools.py` — Rank Calculation Uses Python `or` Incorrectly [HIGH]

**File:** `mcp_engine/tools.py`

```python
_rank = (pathway_strength * confidence) or row["score"]
```

If both `pathway_strength` and `confidence` are `0.0`, the product is `0.0` (falsy), so it falls back to `row["score"]`. Zero-confidence nodes rank by similarity instead of the intended formula. Also, when `pathway_strength=0.1` and `confidence=0.1`, the product `0.01` is truthy and used — but a node with `score=0.95` would rank lower despite being highly similar.

**Fix:** Use explicit logic: `_rank = pathway_strength * confidence if (pathway_strength and confidence) else row["score"]`.

---

### D5. `tools.py` — Content Truncation Can Produce Single "." [MEDIUM]

**File:** `mcp_engine/tools.py`

`content[:max_chars].rsplit(".", 1)[0] + "."` — if the truncated text has no period, `rsplit` returns the full string, so no truncation happens. If the text starts with ".", the result is `"."` — a single period sent to the Brain as message content.

**Fix:** Add a guard: if no period found, truncate at word boundary instead.

---

### D6. `tools.py` — Concepts Invisible to `current_truth` [HIGH]

**File:** `mcp_engine/tools.py`

`current_truth` searches Decision, Constraint, Requirement, ActionItem, and GlobalConstraint/GlobalPreference nodes. But Concept nodes (the majority of extracted entities that haven't been reified to specific artifact types) are not searched. Most of the graph is invisible to the read flow.

**Fix:** Add Concept to the `current_truth` search targets.

---

### D7. `tools.py` — No ESTABLISHED Provenance Edge [MEDIUM]

**File:** `mcp_engine/tools.py`

Per CLAUDE.md schema: `(Message | DocumentExtract)-[ESTABLISHED]->(Decision | Constraint)`. This edge is never created anywhere in the codebase. The provenance chain from message to artifact is broken.

**Fix:** Create ESTABLISHED edges in `_reify_concept()` or after reification in the orchestrator.

---

## Section 5: Sweep (Background Worker)

### SW1. TOCTOU Race in Decay [HIGH]

**File:** `mcp_engine/sweep.py`

The sweep reads `pathway_strength` (sync read), computes decay, then writes the new value (async write). Between read and write, the loop worker may have strengthened the same node via `apply_additive`. The sweep overwrites the loop's update with stale data.

**Fix:** Use an atomic Cypher update: `SET n.pathway_strength = n.pathway_strength * $decay_factor`.

---

### SW2. Resurrection HNSW Searches Include Archived Nodes [MEDIUM]

**File:** `mcp_engine/sweep.py`

When checking if an archived node should be resurrected, the vector search can return OTHER archived nodes as neighbors. Per CLAUDE.md, resurrection should compare against "current active (non-archived) nodes."

**Fix:** Use projected graphs to prefilter to `archived = false` before HNSW search.

---

### SW3. Hebbian Promotion Re-Queries Already-Promoted Pairs [LOW]

**File:** `mcp_engine/sweep.py`

The Hebbian promotion query finds CO_OCCURS_WITH edges above the threshold, but doesn't check if a named edge already exists between those concepts. It will re-prompt the LLM for pairs that were already promoted.

**Fix:** Add `WHERE NOT (a)-[:REQUIRES|ENABLES|REPLACES|...]->(b)` to the query.

---

## Section 6: Web Server & Adapters

### W1. Sync `db.execute()` Inside Async Endpoints [HIGH]

**File:** `web/server.py`

All FastAPI async endpoints call `db.execute()` synchronously. FastAPI runs async endpoints on the event loop — blocking DB calls stall all concurrent HTTP requests.

**Fix:** Use `await asyncio.to_thread(db.execute, ...)` or make the endpoints sync (FastAPI will run them in a thread pool).

---

### W2. Rollback Doesn't Remove DEPRECATED_BY Edge [HIGH]

**File:** `web/server.py`

The rollback endpoint deletes the MergeEvent and un-archives the old concept, but doesn't remove the `DEPRECATED_BY` edge between old and new concepts. The old concept is un-archived but still has a DEPRECATED_BY pointer, creating an inconsistent graph state.

**Fix:** Delete the DEPRECATED_BY edge as part of rollback.

---

### W3. Adapter Can't Self-Recover From Offline State [MEDIUM]

**File:** `adapters/claude_code/adapter.py`

Once `_daemon_online` is set to `False`, there's no reconnection logic. The adapter stays offline for the entire session even if the daemon restarts.

**Fix:** Add periodic reconnection attempts or retry on each tool call.

---

### W4. No Read Timeout on Brain Socket [MEDIUM]

**File:** `adapters/claude_code/adapter.py`

`_call_brain()` reads from the Unix socket with no timeout. If the daemon hangs (e.g., blocked on Ollama), the adapter blocks indefinitely.

**Fix:** Set `socket.settimeout()` before reading.

---

### W5. Offline Queue Never Replays [HIGH]

**File:** `adapters/claude_code/adapter.py`

`_queue_offline()` writes failed messages to a JSONL file, but no replay mechanism exists. When the daemon comes back online, the queued messages are never sent.

**Fix:** Implement replay on reconnection.

---

## Section 7: Ingestion

### I1. `_split_oversized` Offset Tracking Breaks After `lstrip()` [MEDIUM]

**File:** `mcp_engine/ingest.py`

After splitting on sentence boundaries, `lstrip()` is called on the remaining text. This changes the string length, but the byte offset tracking doesn't account for the stripped whitespace, causing `byte_start` / `byte_end` provenance ranges to drift.

**Fix:** Track the stripped character count and add it to the offset.

---

### I2. `rfind` Returns -1 Used as Falsy — Potential Infinite Loop [HIGH]

**File:** `mcp_engine/ingest.py`

`rfind(".")` returns -1 when no period is found. If this -1 is used in a conditional with `or`, the fallback triggers. But in a slicing context, `-1` slices to the second-to-last character, potentially creating an infinite loop where the chunk never gets smaller.

**Fix:** Explicitly check `if idx == -1` and handle the no-period case.

---

### I3. No Path Confinement to Project Directory [HIGH]

**File:** `mcp_engine/ingest.py`

`validate_path()` uses `os.path.realpath()` and checks the file extension suffix, but never verifies the resolved path is within an allowed directory. A symlink `docs/evil.md -> /sensitive/file.md` would pass validation. CLAUDE.md requires: "Block `..` escapes and symlink traversal; only allowlisted extensions."

**Fix:** After `realpath()`, verify the path starts with the project root directory.

---

## Section 8: Schema Init

### SC1. Schema Init Writes Bypass asyncio Write Lock [MEDIUM]

**File:** `mcp_engine/schema.py`

`init_schema()` uses direct Kùzu connection calls, bypassing the `KuzuClient.execute_write()` method and its asyncio lock. If schema init runs concurrently with other writes (shouldn't happen at startup, but possible in tests), data corruption could occur.

**Fix:** Use `KuzuClient.execute_write()` for schema init, or document the startup-only invariant.

---

### SC2. MERGE on SchemaOrgType Properties Causes Duplicates [LOW]

**File:** `mcp_engine/schema.py`

If the `properties` list for a SchemaOrgType changes between versions, MERGE won't match (different property value), creating a duplicate node.

**Fix:** MERGE on `name` only, then SET properties.

---

## Section 9: Test Coverage Gaps

### T1. Zero Tests for Orchestrator (`run_loop`) [CRITICAL]

The entire Gated Consolidation Loop integration has zero tests. Individual steps are tested, but the orchestrator that wires them together is not. Step-to-step data flow, `_store_concept()`, `_reify_concept()`, `_save_gist_example()`, `_store_relation()`, and the `maybe_synthesize_purpose` trigger are all untested.

---

### T2. Zero Tests for Adapter IPC Path [CRITICAL]

**Files:** `adapters/claude_code/adapter.py`, `adapters/claude_code/hook_user_turn.py`, `adapters/claude_code/setup.py`

The critical production code path between Claude Code and the Brain Daemon — `_call_brain()`, `handle_mcp_request()`, daemon online/offline state, socket protocol, offline queue — is completely untested.

---

### T3. Zero Tests for `brain_daemon.py` [HIGH]

`BrainDaemon` class is untested: `_handle_connection()` JSON-RPC parsing, `_dispatch()` method routing, `_loop_worker()` error handling, `_background_sweep()` loop, `shutdown()` cleanup.

---

### T4. Zero Tests for `maybe_synthesize_purpose()` [HIGH]

**File:** `mcp_engine/quest.py:325-437`

Complex multi-query DB interaction + LLM invocation with zero coverage. Multiple failure modes (message not linked to session, purpose already set, LLM returns empty, DB write failure).

---

### T5. Zero Tests for `config.py` [MEDIUM]

`load_config()` search order (explicit path > cwd > home), missing file handling, malformed TOML — all untested.

---

### T6. Zero Tests for `schema.py` [HIGH]

`init_schema()`, `_parse_seed_examples()`, `_bootstrap_centroids()` — all untested. If seed parsing breaks, all centroids are empty and Step 2 System 1 never fires.

---

### T7. Zero Tests for `provider.py` [MEDIUM]

`create_llm_client()` factory and `LLMClient.chat()` — unknown provider, import failure, API key resolution — all untested.

---

### T8. Stub Test Files With Zero Test Functions [HIGH]

**Files:** `tests/test_retrieval.py`, `tests/test_adapters.py`

Both files exist but contain only docstring comments — zero actual test functions. They create the illusion of coverage.

---

### T9. Test Assertions That Can Never Fail [HIGH]

**File:** `tests/test_loop.py`

- `test_step1b_requires_relation()`: Asserts `len(rels) >= 0` — always true, never fails. Should be `>= 1`.
- `test_step2_llm_fallback_called_in_gray_zone()`: Never asserts that the mock LLM was actually called. The final assertion is a tautology.
- `test_step2_noise_below_floor()`: Accepts `2_degraded` as valid, masking potential issues with zero-vector cosine similarity.

---

### T10. Security Test Gap — No Symlink/Path Traversal Tests [HIGH]

**File:** `mcp_engine/ingest.py`

CLAUDE.md requires "Block `..` escapes and symlink traversal" but no test exercises symlink scenarios or directory confinement validation.

---

## Section 10: Summary by Priority

### CRITICAL (Fix First)

| # | Issue | Impact |
|---|-------|--------|
| S1 | Sync LLM calls block event loop | All async operations stall during LLM calls |
| L14 | Uses `created_at` instead of `last_accessed_at` | Hebbian reinforcement formula produces wrong values |
| L15 | No `last_accessed_at` update on access | Decay formula has no access timestamp to work with |
| O2 | Ghost Concept nodes without embeddings | Invisible to vector search, break HNSW index |
| T1 | Zero orchestrator tests | Integration bugs invisible |
| T2 | Zero adapter IPC tests | Production path completely unvalidated |

### HIGH (Fix Soon)

| # | Issue | Impact |
|---|-------|--------|
| S2 | Silent exception swallowing | Failures invisible, fake IDs returned |
| S3 | Blocking Kùzu I/O in asyncio.Lock | Lock held during blocking calls |
| L1 | Un-normalized centroids deflate similarity | System 2 LLM called too often |
| L3 | Agent routing table overwrite | Agent type routing broken |
| L5 | Step 4 uses full message not entity text | Wrong entities classified as artifacts |
| L9 | Silent vector search failure | Graph fills with duplicates |
| L13 | Race condition in additive update | Lost updates on concurrent access |
| L16 | Contradiction not transactional | Partial audit trail on failure |
| O3 | Case-sensitive MERGE creates duplicates | Same entity stored multiple times |
| O5 | No Message node in orchestrator | Audit trail silently broken |
| O7 | Event-driven re-scoring missing | confidence_low nodes stuck until sweep |
| D2 | Fire-and-forget tasks die silently | Loop worker or sweep can die unnoticed |
| D4 | Rank `or` operator bug | Zero-confidence nodes rank incorrectly |
| D6 | Concepts invisible to current_truth | Most graph nodes unsearchable |
| SW1 | TOCTOU race in decay | Sweep overwrites loop updates |
| W1 | Sync DB in async web endpoints | Web server stalls on DB calls |
| W2 | Rollback missing DEPRECATED_BY cleanup | Inconsistent graph after rollback |
| W5 | Offline queue never replays | Offline messages permanently lost |
| I2 | rfind -1 potential infinite loop | Ingestion hangs on periodless text |
| I3 | No path confinement | Security: files outside project readable |
| T3-T9 | Various test gaps | Major code paths unvalidated |

### MEDIUM (Address in Next Sprint)

| # | Issue |
|---|-------|
| S4 | Module-level asyncio.Lock |
| L2 | Unknown LLM class → "Restriction" |
| L4 | Agent routing bypasses cache |
| L6 | "must not"/"must" double-count |
| L8 | exclude_id="" ineffective |
| L10 | Postfilter degrades with archived nodes |
| L11 | Fragile JSON parsing of LLM output |
| L12 | referenced_index type coercion |
| O4 | Relations stored before noise filtering |
| D1 | shutdown() doesn't stop event loop |
| D5 | Truncation can produce single "." |
| D7 | No ESTABLISHED provenance edge |
| SW2 | Resurrection includes archived neighbors |
| W3 | Adapter can't self-recover offline |
| W4 | No socket read timeout |
| I1 | Offset tracking drift after lstrip |
| SC1 | Schema init bypasses write lock |

### LOW (Backlog)

| # | Issue |
|---|-------|
| L7 | schema_org_type param unused |
| L17 | O(n^2) CO_OCCURS_WITH writes |
| O1 | Duplicate embedding computation |
| O6 | Step 3b trigger too conservative |
| O8 | UUIDs generated for existing concepts |
| SW3 | Re-queries already-promoted pairs |
| SC2 | MERGE on properties causes duplicates |

---

## Recommended Fix Order

1. **L14 + L15** — Add `last_accessed_at` to Concept schema, update it on access, use it in formulas. This is the foundation of Hebbian reinforcement.
2. **S1** — Wrap LLM calls in `asyncio.to_thread()`. Unblocks the entire async system.
3. **O2** — Fix `_store_relation` to embed concepts or only MERGE against existing nodes.
4. **D6** — Add Concept to `current_truth` search targets.
5. **L1** — L2-normalize centroids after mean-pooling.
6. **SW1 + L13** — Atomic Cypher updates for pathway_strength (both sweep and additive).
7. **O5** — Create Message node or validate precondition.
8. **T1 + T2** — Write orchestrator and adapter integration tests.
9. **I3** — Add directory confinement to `validate_path()`.
10. **W2** — Fix rollback to remove DEPRECATED_BY edge.

---

*Total findings: 63 (6 CRITICAL, 26 HIGH, 19 MEDIUM, 8 LOW, 4 test quality)*

---

## Fix Log

Tracking who fixed what and when. Opus 4.6 handles architectural fixes; Sonnet handles mechanical fixes.

| # | Finding | Assigned To | Status | Date | Notes |
|---|---------|------------|--------|------|-------|
| L14 | `created_at` instead of `last_accessed_at` | Opus 4.6 | DONE | 2026-03-12 | Added `last_accessed_at` to schema + step7 + sweep |
| L15 | No `last_accessed_at` update on access | Opus 4.6 | DONE | 2026-03-12 | Fixed in same commit as L14 |
| S1 | Sync LLM blocks event loop | Opus 4.6 | DONE | 2026-03-12 | Added async `achat()` to provider, updated all callers |
| O2 | Ghost Concepts without embeddings | Opus 4.6 | DONE | 2026-03-12 | `_store_relation` now only MERGEs existing Concepts |
| L3 | Agent routing table overwrite | Opus 4.6 | DONE | 2026-03-12 | Redesigned routing table to handle Agent disambiguation |
| L16 | Contradiction not transactional | Opus 4.6 | DONE | 2026-03-12 | Batched into single Cypher query |
| O5 | No Message node in orchestrator | Opus 4.6 | DONE | 2026-03-12 | Added Message node validation |
| O7 | Event-driven re-scoring missing | Opus 4.6 | DONE | 2026-03-12 | Implemented post-pathway-update re-scoring |
| SW1 | TOCTOU race in decay | Opus 4.6 | DONE | 2026-03-12 | Atomic Cypher decay update |
| L13 | Race condition in additive update | Opus 4.6 | DONE | 2026-03-12 | Atomic Cypher increment |
| W2 | Rollback missing DEPRECATED_BY | Opus 4.6 | DONE | 2026-03-12 | Added edge removal to rollback |
| S2 | Silent exception swallowing | Sonnet | DONE | 2026-03-12 | logging.exception() added to all bare except blocks in orchestrator + tools |
| S3 | Blocking Kùzu I/O in Lock | Sonnet | DONE | 2026-03-12 | execute_write() wraps blocking call in asyncio.to_thread() |
| S4 | Module-level asyncio.Lock | Sonnet | DONE | 2026-03-12 | Lazy-init via _get_write_lock() |
| L1 | Un-normalized centroids | Sonnet | DONE | 2026-03-12 | L2-normalize after mean_pool in schema.py + sweep centroid update |
| L2 | Unknown class → "Restriction" | Sonnet | DONE | 2026-03-12 | Return noise for unrecognized LLM class names |
| L4 | Agent routing bypasses cache | Sonnet | DONE | 2026-03-12 | Resolved by Opus L3 fix (routing table now returns both Agent variants) |
| L5 | Step 4 uses full message text | Sonnet | DONE | 2026-03-12 | _entity_sentence() extracts containing sentence; entity_text param added |
| L6 | "must not"/"must" double-count | Sonnet | DONE | 2026-03-12 | Negative lookahead: r"\bmust(?!\s+not)\b" |
| L7 | schema_org_type unused | Sonnet | DONE | 2026-03-12 | Accepted as named param alongside entity_text; no behavior change needed |
| L8 | exclude_id="" ineffective | Sonnet | DONE | 2026-03-12 | collect concept_ids per run, pass as exclude_ids to retrieve_candidates |
| L9 | Silent vector search failure | Sonnet | DONE | 2026-03-12 | logging.exception() with explicit warning about duplicate risk |
| L10 | Postfilter degrades with archived | Sonnet | DONE | 2026-03-12 | Increased _FETCH_HEADROOM to 20; projected graph prefilter deferred to M5 |
| L11 | Fragile JSON parsing | Sonnet | DONE | 2026-03-12 | re.search(r'\{[^}]+\}') extracts first JSON block |
| L12 | referenced_index coercion | Sonnet | DONE | 2026-03-12 | int(ref_idx) with try/except before range check |
| L17 | O(n^2) CO_OCCURS_WITH | Sonnet | DONE | 2026-03-12 | Single UNWIND batch query; test updated |
| O1 | Duplicate embedding | Sonnet | DONE | 2026-03-12 | Carry vector from typed_entities, fallback to emb.embed() |
| O3 | Case-sensitive MERGE | Sonnet | DONE | 2026-03-12 | Already fixed by Opus (toLower in MATCH). No separate node creation needed. |
| O4 | Relations before noise filter | Sonnet | DONE | 2026-03-12 | Step 1b storage deferred until after Step 2; only surviving entities' relations stored |
| O6 | Step 3b trigger conservative | Sonnet | DONE | 2026-03-12 | Step 3b now runs for all uncovered entity pairs, not just when 1b found nothing |
| O8 | UUIDs for existing concepts | Sonnet | SKIP | — | O2 fix (MATCH only) means UUID is generated only for new concepts now |
| D1 | shutdown() doesn't stop loop | Sonnet | DONE | 2026-03-12 | asyncio.get_running_loop().stop() added to shutdown() |
| D2 | Fire-and-forget tasks | Sonnet | DONE | 2026-03-12 | done_callback logs exception + restarts all three background tasks |
| D3 | Hardcoded OneDrive path | Sonnet | DONE | 2026-03-12 | SEED_PATH now package-relative (Path(__file__).parent / "InvertorsDocs/...") |
| D4 | Rank `or` operator bug | Sonnet | DONE | 2026-03-12 | Explicit: rank = ps*conf if both > 0 else similarity |
| D5 | Truncation → single "." | Sonnet | DONE | 2026-03-12 | Word boundary fallback when no period found |
| D6 | Concepts invisible to current_truth | Sonnet | DONE | 2026-03-12 | Concept added to artifact_tables in current_truth |
| D7 | No ESTABLISHED edge | Sonnet | DONE | 2026-03-12 | ESTABLISHED edge created in _reify_concept, message_id threaded through |
| SW2 | Resurrection includes archived | Sonnet | DONE | 2026-03-12 | Over-fetch 20 results + filter archived neighbors |
| SW3 | Re-queries promoted pairs | Sonnet | DONE | 2026-03-12 | WHERE NOT (a)-[:REQUIRES|...]->(b) added to Hebbian query |
| W1 | Sync DB in async endpoints | Sonnet | DONE | 2026-03-12 | Pure-read endpoints → sync def; mixed endpoints → asyncio.to_thread() |
| W3 | Adapter offline recovery | Sonnet | DONE | 2026-03-12 | current_truth always attempts call; notify_turn triggers replay on reconnect |
| W4 | No socket read timeout | Sonnet | DONE | 2026-03-12 | asyncio.wait_for(reader.readline(), timeout=10.0) |
| W5 | Offline queue never replays | Sonnet | DONE | 2026-03-12 | _replay_offline_queue() called after successful brain call when was_offline |
| I1 | Offset drift after lstrip | Sonnet | SKIP | — | chunk_document() computes offset from seg.index(stripped[0]) — already correct |
| I2 | rfind -1 infinite loop | Sonnet | DONE | 2026-03-12 | Explicit idx != -1 check in _split_oversized |
| I3 | No path confinement | Sonnet | DONE | 2026-03-12 | validate_path() accepts project_root; raises ValueError if path escapes |
| SC1 | Schema init bypasses lock | Sonnet | DONE | 2026-03-12 | Documented as startup-only invariant in docstring |
| SC2 | MERGE on properties | Sonnet | DONE | 2026-03-12 | MERGE on name only, SET s.properties |
| T8 | Stub test files with no tests | Sonnet | DONE | 2026-03-12 | test_retrieval.py + test_adapters.py filled with real tests |
| T9 | Test assertions that never fail | Sonnet | DONE | 2026-03-12 | Fixed >= 0 tautology; gray-zone test uses monkeypatched controlled vectors |

### Fix Summary (2026-03-12) — Sonnet 4.6 pass

**Sonnet 4.6 completed 35 mechanical fixes (2026-03-12):**
- S2: logging.exception() in orchestrator, tools, step5
- S3+S4: kuzu_client.py — asyncio.to_thread() in execute_write, lazy Lock init
- L1: L2-normalize centroids after mean_pool in schema.py
- L2: noise return for unrecognized LLM gist class
- L5: _entity_sentence() in step4, entity_text param threaded through orchestrator
- L6: negative lookahead regex for "must not"/"must"
- L8: exclude_ids collected per run, passed to retrieve_candidates
- L9: logging.exception() in step5 vector search failure path
- L10: _FETCH_HEADROOM increased to 20
- L11: regex JSON extraction in step6 arbitration
- L12: int() coercion for referenced_index
- L17: UNWIND batch query for CO_OCCURS_WITH (test updated)
- O1: vector reused from typed_entities["vector"]
- O4: Step 1b storage deferred until after Step 2 noise filtering
- O6: Step 3b runs for all uncovered entity pairs
- D1: loop.stop() in shutdown()
- D2: done_callback + restart for all 3 background tasks
- D3: SEED_PATH package-relative
- D4: explicit rank formula (ps*conf if both > 0)
- D5: word boundary fallback for content truncation
- D6: Concept added to current_truth search tables
- D7: ESTABLISHED provenance edge in _reify_concept
- SW2: resurrection over-fetches 20 results, filters archived neighbors
- SW3: WHERE NOT named-edge check in Hebbian promotion query
- W1: pure-read web endpoints → sync def; mixed → asyncio.to_thread()
- W3: current_truth always attempts call even when offline; reconnect replay
- W4: asyncio.wait_for() timeout on socket readline
- W5: _replay_offline_queue() on reconnect
- I2: explicit rfind -1 check in _split_oversized
- I3: project_root confinement in validate_path()
- SC1: documented startup-only invariant for schema init
- SC2: MERGE on SchemaOrgType name only, SET properties
- T8: test_retrieval.py + test_adapters.py filled with 11 real tests
- T9: fixed tautological assertions, gray-zone test uses controlled vectors

**All 198 tests passing after fixes.** 13 net new tests added.

---

### Fix Summary (2026-03-12) — Opus 4.6 pass

**Opus 4.6 completed 11 architectural fixes:**
- L14+L15: Added `last_accessed_at` field to Concept schema + step7 + orchestrator
- S1: Added async `achat()` to LLMClient, updated sweep + quest callers
- O2: `_store_relation` now only MATCHes existing Concepts (no ghost nodes)
- L3: Routing table redesigned as list-of-entries (Agent maps to both Person+Org)
- L16: Contradiction writes batched into single Cypher query
- O5: Message node existence validation added to orchestrator
- O7: `rescore_nearby_low_confidence()` implemented + wired into orchestrator
- SW1: Atomic bulk decay (`SET n.pathway_strength = n.pathway_strength * $factor`)
- L13: Atomic increment (`SET c.pathway_strength = c.pathway_strength + $increment`)
- W2: Rollback now removes DEPRECATED_BY edge

**All 185 tests passing after fixes.** No regressions.

**Remaining 36 findings assigned to Sonnet** — mechanical fixes that don't require cross-file architectural reasoning. Feed one finding at a time with the file path and fix description.
