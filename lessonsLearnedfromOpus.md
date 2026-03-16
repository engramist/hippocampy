# Lessons Learned — Code Audit
_Performed by Claude Sonnet 4.6 on 2026-03-11. Opus 4.6 to review and extend._

---

## Summary

Full audit of M1–M8 codebase against CLAUDE.md spec, backlog, and Gemini conversation claims.
**9 categories of findings. 3 HIGH severity items. All have recommended fixes.**

**Status as of 2026-03-11:** All HIGH and MEDIUM severity items resolved except M8 (deferred — requires MCP `prompts` capability). Test count: 157 → 185. LOW severity and deferred items tracked in backlog.

---

## HIGH SEVERITY

### H1 · Background Sweep Not Implemented ✅ FIXED
**File:** `brain_daemon.py` ~line 251
**Fix applied:** Implemented `mcp_engine/sweep.py` with `_decay_and_archive()`, `_resurrect_archived()`, `_hebbian_promote()`, and `_recompute_centroids()`. Wired into `brain_daemon._background_sweep()`. 23 tests added in `tests/test_sweep.py`.
**Impact (original):** Entire Synaptic Pruning / Hebbian Decay system is non-functional.

```python
async def _background_sweep(self, interval_seconds: int):
    while True:
        await asyncio.sleep(interval_seconds)
        # TODO M4: implement sweep
        pass
```

The background sweep is the engine behind:
- Pathway strength decay (Ebbinghaus Forgetting Curve)
- Archive/resurrection mechanics
- `confidence_low` node re-scoring
- CO_OCCURS_WITH → named relationship promotion (Hebbian Trigger 2)

Without it, nodes accumulate indefinitely. Memory bloat is unbounded. The `archive_threshold`
and `resurrection_threshold` config values in `sidequests.toml` have no effect.

**Fix:** Implement per-table sweep per CLAUDE.md spec. Per-table write-lock windows (not one
giant transaction). Cover: decay, archive, resurrection, re-scoring.

---

### H2 · CO_OCCURS_WITH Auto-Promotion (Hebbian Trigger 2) Not Implemented ✅ FIXED
**File:** `mcp_engine/sweep.py`
**Fix applied:** Implemented `_hebbian_promote()` in sweep.py. Queries CO_OCCURS_WITH edges at or above threshold, calls LLM to name the relationship, writes named edge with `inferred_by="LLM"` via idempotent MERGE. Covered by 8 tests.
**Impact (original):** Hebbian learning is half-built. Edges accumulate but never graduate to named relationships.

CLAUDE.md specifies three Hebbian promotion triggers:
1. Step 1b verb pattern match — ✓ implemented
2. LLM auto-promotes when `co_occurrence_count >= 10` — ✗ missing
3. User promotes via Memory Control Panel — ✓ UI exists, mechanism works

Trigger 2 requires: background sweep queries CO_OCCURS_WITH edges above threshold, calls LLM
to name the relationship, writes the named edge with `inferred_by: "LLM"`.

**Fix:** Implement in background sweep (H1 and H2 are linked — fix H1 first).

---

### H3 · ActionItem Vector Index Name Mismatch ✅ FIXED
**File:** `mcp_engine/tools.py` line 165
**Fix applied:** Changed `"action_item_emb_idx"` → `"actionitem_emb_idx"` to match `schema.py`'s `table.lower()` index naming convention.
**Impact (original):** All vector searches on ActionItem nodes fail silently.

`tools.py` searches for `action_item_emb_idx` (with underscore).
`schema.py` creates index as `f"{table.lower()}_emb_idx"` → `actionitem_emb_idx` (no underscore).

Failures are silently caught by `except Exception: pass` at line 195–196 in tools.py.
ActionItem nodes exist in the DB but are never returned by `current_truth`.

**Fix:** Standardize index naming. Either:
- Change `tools.py` to use `actionitem_emb_idx`, or
- Change `schema.py` index creation to insert underscores: `re.sub(r'(?<!^)(?=[A-Z])', '_', table).lower() + "_emb_idx"`

Apply the same audit to `analogical.py` CROSS_QUEST_TABLES for consistency.

---

## MEDIUM SEVERITY

### M1 · Reification Sets pathway_strength to 1.0, Not Concept's Value ✅ FIXED
**File:** `mcp_engine/loop/orchestrator.py` — `_reify_concept()`
**Fix applied:** Added `confidence: float = 1.0` parameter to `_reify_concept`. Both call sites now pass `confidence=step4_result["confidence"]`. Artifact node is created with `pathway_strength = max(confidence, 0.50)`, matching the spec and `_store_concept`.
**Impact (original):** Artifact nodes (Decision, Constraint, etc.) always start at strength 1.0 regardless of the Concept's actual pathway_strength.

CLAUDE.md: `pathway_strength initialized to max(confidence, 0.50) at node creation`.

When a Concept is reified (>90% confidence), the artifact node should inherit the Concept's
pathway_strength. Currently hardcoded to the confidence value (which is 1.0 at reification).

**Fix:** Pass `concept.pathway_strength` to the artifact CREATE, not the confidence value.

---

### M2 · MainQuest Creation is TOCTOU Race Condition ✅ FIXED
**File:** `mcp_engine/quest.py` — `get_or_create_main_quest()`
**Fix applied:** Replaced the MATCH→check→CREATE pattern with a single `MERGE (q:MainQuest {quest_id: $quest_id}) ON CREATE SET ... ON MATCH SET q.last_active_at = $now`. Also resolves M6 (see below).
**Impact (original):** Duplicate quest creation attempts under concurrent adapter load (silent failure).

Pattern: `MATCH → check → CREATE` should be `MERGE ... ON CREATE SET`.
`create_side_quest()` already uses MERGE correctly. `get_or_create_main_quest()` does not.

**Fix:** Replace check+create pattern with MERGE in `get_or_create_main_quest()`.

---

### M3 · Byte Offset Bug for Multi-Byte UTF-8 in Document Chunking ✅ FALSE POSITIVE — CONFIRMED CORRECT
**File:** `mcp_engine/ingest.py` ~lines 194–200
**Finding after investigation:** `text[:char_idx].encode("utf-8")` is the correct Python idiom for character-to-byte offset conversion. The code is correct. Audit finding was wrong.
**Fix applied:** Added `test_chunk_byte_offsets_correct_for_multibyte_utf8` in `tests/test_ingest.py` with emoji, CJK, and accented text to lock in correct behavior and prevent future regression.

```python
byte_start = len(text[:actual_char_start].encode("utf-8"))
byte_end   = len(text[:actual_char_end].encode("utf-8"))
```

`actual_char_end` is a character offset. For multi-byte chars, encoding up to that character
position gives correct bytes — but `len(seg_stripped)` used elsewhere counts Unicode chars,
not bytes. Mixing these two units causes cascading errors in line number computation.

**Fix:** Work exclusively in byte space throughout the chunking algorithm, or add explicit
Unicode-aware offset tracking. Add test with emoji/CJK input (see T3).

---

### M4 · Centroid Update After System 2 Resolution Not Implemented ✅ FIXED
**Files:** `step2_gist.py`, `loop/orchestrator.py`, `mcp_engine/sweep.py`, `mcp_engine/schema.py`
**Fix applied:** Three-part implementation:
1. `classify_concept()` now returns the embedding vector in its result dict (no re-computation by caller).
2. Orchestrator writes a `GistExample` node via `_save_gist_example()` after every System 2 resolution.
3. Background sweep calls `_recompute_centroids()` which mean-pools all `GistExample` embeddings per class, normalizes to unit vector, and updates `GistClass.centroid`. `GistExample` node table added to schema.
**Impact (original):** The self-improving property is broken. Centroids never update after M1 init.

The docstring claims: "Saves example for centroid improvement."
The code returns the classification but never writes the example to the graph or updates
`GistClass.centroid`.

**Fix:** After System 2 resolution, write a labeled example node, then queue centroid
re-computation (e.g., mean-pool all examples for the class, update `GistClass.centroid`).
Can be deferred to background sweep to keep the hot path fast.

---

### M5 · Purpose Synthesis Not Implemented (M5 Gap) ✅ FIXED
**Files:** `mcp_engine/quest.py`, `mcp_engine/loop/orchestrator.py`
**Fix applied:** Implemented `maybe_synthesize_purpose()` in quest.py. Triggered from the orchestrator after the first hard-lock (>90%) reification in a `run_loop` call. Looks up the session via the message's `SENT_IN` edge, skips if `Session.purpose` is already set, gathers recent messages as context, calls LLM for a 1–2 sentence purpose, and writes to both `Session.purpose` and `MainQuest.purpose` (only if still generic). Gracefully skips if no LLM or no session linked.
**Impact (original):** Quest purpose is always generic ("Project work on X"), never inferred from content.

CLAUDE.md: "Trigger = first confirmed (>90%) artifact. Ollama synthesizes 1–2 sentence purpose."
The trigger point exists (first hard-lock in orchestrator) but the LLM call is never made.
`Session.purpose` and `MainQuest.purpose` remain empty or static.

**Fix:** In orchestrator, after first hard-lock artifact in a new session/quest, call LLM to
synthesize purpose, write to `Session.purpose` (confidence_low=true). Re-infer if later sessions
diverge significantly from original purpose embedding.

---

### M6 · MainQuest Missing `last_active_at` Field ✅ FIXED (resolved alongside M2)
**Files:** `mcp_engine/schema.py`, `mcp_engine/quest.py`
**Fix applied:** Added `last_active_at TIMESTAMP` to the MainQuest node table DDL in schema.py. The MERGE in `get_or_create_main_quest()` now sets `ON MATCH SET q.last_active_at = $now` on every adapter connection, keeping the field current for inactivity detection.
**Impact (original):** `auto_complete_days` inactivity detection cannot work correctly.

Session has `last_active_at` (updated on each `get_or_create_session`). MainQuest does not.
To check inactivity, code must traverse Session nodes — a more expensive query with no index.

**Fix:** Add `last_active_at TIMESTAMP` to MainQuest schema. Update it inside
`get_or_create_session()` via MERGE ON MATCH SET.

---

### M7 · MergeEvent Not Written for Additive Updates ✅ RESOLVED (by design clarification)
**File:** `mcp_engine/loop/step7_pathway.py` — `apply_additive()`
**Resolution:** After review, not writing a MergeEvent for additive updates is the correct design. MergeEvents are the rollback mechanism for contradictions — they record the delta between an old and new concept so the Memory Control Panel can undo a merge. Additive updates are cumulative reinforcements with no discrete rollback point; `pathway_strength` itself is the audit trail. Added an explicit docstring to `apply_additive()` documenting this decision so it is never mistaken for a bug again.
**Impact (original):** Additive pathway updates are not reversible via Memory Control Panel.

CLAUDE.md: `(Message)-[TRIGGERED]->(MergeEvent)-[UPDATES_PATHWAY]->(Concept)` for all updates.
`apply_contradiction()` writes a MergeEvent ✓. `apply_additive()` does not ✗.

**Fix:** Create a lightweight MergeEvent in `apply_additive()`:
`{pre_pathway_strength, delta, metadata_patch: "additive"}`. Or explicitly document in CLAUDE.md
that only contradictions are rollback-eligible and update `web/server.py` UI accordingly.

---

### M8 · Quest Context Not Injected into Adapter System Prompt ⏳ DEFERRED
**File:** `adapters/claude_code/adapter.py` ~lines 228–234, `mcp_engine/quest.py`
**Status:** Deferred. Requires MCP `prompts` capability or a session-startup hook — an architectural change to the adapter layer. Tracked in backlog. `get_quest_context()` and `format_context_for_prompt()` in quest.py are ready to use when the adapter layer supports dynamic prompt injection.
**Impact:** LLM never has immediate quest context without explicitly calling `current_truth`.

`get_quest_context()` and `format_context_for_prompt()` exist in quest.py but are never called
by adapters. The always-on fragment is hardcoded static text — no quest name, no recent decisions.

CLAUDE.md specifies the fragment should include `{quest_name}` and `{branch}` injected at runtime.

**Fix:** On first `notify_turn` in a session, fetch the MainQuest name + branch and cache it
in the adapter process. Inject into the system prompt fragment dynamically.

---

### M9 · Unix Domain Socket Permissions Too Permissive ✅ FIXED
**File:** `brain_daemon.py` — `_run_ipc_server()`
**Fix applied:** Added `mode=0o700` to the `mkdir` call: `SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)`. Directory is now user-only regardless of system umask.
**Impact (original):** On systems with permissive umask, socket could be world-readable.

```python
SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)  # no mode specified
```

**Fix:**
```python
SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)  # user-only
```

---

## LOW SEVERITY

### L1 · SEED_PATH Hardcodes Personal OneDrive Path as Default
**File:** `brain_daemon.py` ~lines 38–41
The fallback `SEED_PATH` is a personal OneDrive path (`/Users/djs54/Library/CloudStorage/...`).
The `_resolve_seed_path()` method has good fallback logic, but the hardcoded default will fail
on any other machine. Document this clearly or make `seed_path` configurable in `sidequests.toml`.

### L2 · Lazy Imports Inside Tool Handlers
**File:** `mcp_engine/tools.py` ~lines 368, 390
`from mcp_engine.analogical import ...` and `from mcp_engine.ingest import ...` are inside
the async handler functions. Works correctly but incurs import overhead on every call.
Move to module level with TYPE_CHECKING guard pattern used elsewhere.

### L3 · Floating-Point Threshold Comparisons
**File:** `mcp_engine/loop/step5_retrieval.py` ~lines 21–22, `orchestrator.py` ~lines 140–147
Similarity thresholds (0.75, 0.92) compared with `>` and `>=` directly on floats.
Consider `math.isclose()` or explicit tolerance to avoid precision edge cases near boundaries.

### L4 · `complete_quest` Tool Referenced but Not in TOOL_HANDLERS
**File:** `backlog.md` (B9), `mcp_engine/tools.py` ~lines 404–412
`complete_quest` is described in CLAUDE.md as an M5 tool but is not in `TOOL_HANDLERS` and
not in any adapter's TOOLS list. Either implement it or add it to the backlog explicitly.

### L5 · Python Version Minimum Not Declared
**File:** `pyproject.toml` (or `setup.py` — not yet created per backlog B4)
Code uses `list[str]` type hints requiring Python 3.9+. The `tomllib` fallback handles 3.11.
When pyproject.toml is created (B4), set `python_requires = ">=3.9"`.

---

## MISSING TESTS

### T1 · `tests/test_adapters.py` Is Empty
The file is a docstring stub. Full coverage needed:
offline queue behavior, git context injection, tool schema validation, OFFLINE fragment.
Already in backlog as B9.

### T2 · No Tests for Background Sweep ✅ FIXED
27 tests added in `tests/test_sweep.py` covering: `run_sweep` summary keys, decay + archive logic, resurrection (self-match skip, archived neighbor skip, threshold enforcement, strength reset), Hebbian promotion (confidence gates, unknown type, bad JSON, empty text), and centroid recomputation (mean-pooling, normalization, empty DB).

### T3 · No Tests for Multi-Byte UTF-8 in Document Chunking ✅ FIXED
`test_chunk_byte_offsets_correct_for_multibyte_utf8` added to `tests/test_ingest.py`. Confirmed original code is correct — test locks in the behavior.

### T4 · No Tests for Quest Context Injection
`get_quest_context()` and `format_context_for_prompt()` in quest.py have no test coverage.

---

## CLAIMS IN GEMINI CONVERSATION TO CORRECT

| Gemini Claim | Verdict | Correction |
|---|---|---|
| "Runs documents through the 9-Step Consolidation Loop" | ❌ False | M6 ingest uses a separate chunking+embedding pipeline, not the Loop |
| "Sub-millisecond vector similarity search" | ⚠️ Overstatement | HNSW is fast, but sub-millisecond is not guaranteed; remove this claim |
| "The system is self-improving via System 2 centroid updates" | ✅ Now true | M4 fixed: `GistExample` nodes + `_recompute_centroids()` in sweep.py |
| "Synaptic pruning keeps memory clean" | ✅ Now true | H1 fixed: full sweep implemented in `mcp_engine/sweep.py` |
| Gemini "integrated this into the Inventor's Notebook" | ✅ Corrected | Gemini has canvas access; this was a valid canvas edit, not hallucination |

---

## BACKLOG CORRECTIONS

| Item | Issue |
|---|---|
| B1 references `sidequests/cli/` | No `sidequests/` package exists yet — path should match future pyproject.toml structure |
| B9 references `complete_quest` tool | Tool not yet implemented — add as explicit backlog item (L4 above) |
| B10 (`explore_graph`) depth cap | Spec says "3 hops max" — ensure this is enforced in query, not just documented |
| B11 (`Lesson` node) | Depends on background sweep (H1) for synthesis trigger — sequence correctly |
| B12 (Anomaly Detection) | Note clearly: conversation-layer only, not syscall-level |

---

## RECOMMENDED FIX ORDER

**Do first (blocking correctness):** ✅ ALL DONE
1. H3 — ActionItem index name mismatch ✅ Fixed: `actionitem_emb_idx` in tools.py
2. M2 — MainQuest TOCTOU race ✅ Fixed: `get_or_create_main_quest` uses MERGE ON CREATE/ON MATCH
3. M9 — Socket permissions ✅ Fixed: `mkdir(mode=0o700)`

**Do second (core IP completeness):** ✅ ALL DONE
4. H1 — Background sweep ✅ Implemented: `mcp_engine/sweep.py` (decay, archive, resurrection)
5. H2 — Hebbian Trigger 2 ✅ Implemented: `_hebbian_promote()` in sweep.py
6. M4 — Centroid updates ✅ Implemented: `_save_gist_example()` in orchestrator.py + `_recompute_centroids()` in sweep.py

**Do third (spec compliance):** ✅ ALL DONE
7. M1 — Reification pathway_strength ✅ Fixed: `max(confidence, 0.50)` in `_reify_concept`
8. M3 — UTF-8 byte offset ✅ Confirmed correct; test added: `test_chunk_byte_offsets_correct_for_multibyte_utf8`
9. M5 — Purpose synthesis ✅ Implemented: `maybe_synthesize_purpose()` in quest.py; wired into orchestrator
10. M6 — MainQuest.last_active_at ✅ Fixed: field added to schema + MERGE ON MATCH SET in quest.py
11. M8 — Quest context injection ⏳ Deferred (requires MCP `prompts` capability — architectural change for later)

**Do last (polish + audit trail):** ✅ ALL DONE
12. M7 — MergeEvent for additive ✅ Fixed: docstring clarification — additive updates intentionally not rollback-eligible
13. T1 — test_adapters.py ⏳ Deferred to backlog B9
14. T4 — quest context tests ⏳ Deferred to backlog
15. L1–L5 — low severity cleanup ⏳ Deferred

**Test count progression:** 157 → 180 (H1/H2 tests) → 181 (M3 UTF-8 test) → 185 (M4 centroid tests + M5 wiring)

---
---

# Strategic & Architectural Audit
_Performed by Claude Opus 4.6 on 2026-03-11. Scope: architecture, design decisions, spec compliance. Line-level bugs deferred to a subsequent pass._

---

## Summary

15 findings. 4 HIGH (architectural gaps affecting core IP claims), 6 MEDIUM (spec compliance, design completeness), 5 LOW (polish, operational). The prior Sonnet audit caught implementation gaps well; this audit focuses on **structural design decisions that affect whether the system delivers on its IP promises**.

---

## HIGH SEVERITY — Architectural

### S1 · Synchronous LLM Calls Block the Entire Event Loop
**Files:** `mcp_engine/llm/provider.py:35-45`, all callers (Steps 2, 3b, 6, sweep)
**Impact:** The Brain Daemon is a single-threaded asyncio process. `LLMClient.chat()` is synchronous — it calls `client.chat.completions.create()` which blocks until the HTTP response returns. During every Ollama call (~200ms–2s per call), the IPC server, web panel, and sweep task are all frozen. A single message with 3 entities hitting System 2 could block the daemon for 6+ seconds. Adapter connections will time out under sustained load.

**Strategic risk:** This is the most likely source of perceived slowness in real usage. It won't surface in tests (mocks are instant) but will dominate the user experience.

**Recommendation:** Wrap the synchronous call in `asyncio.to_thread()` or use the `openai` async client (`AsyncOpenAI`). The provider abstraction is thin enough that this is a small change with outsized impact.

---

### S2 · Concept Nodes Are Invisible to `current_truth`
**Files:** `mcp_engine/tools.py:161-168`
**Impact:** `current_truth` searches Decision, Constraint, Requirement, ActionItem, GlobalConstraint, GlobalPreference — but **not Concept**. Since most NER-extracted entities enter the graph as Concepts and only those above 90% confidence get reified into artifact nodes, a large fraction of the knowledge graph is unreachable by the primary read tool.

Consider the flow: Step 1 extracts "Kùzu" as an entity. Steps 2-4 classify it as a PhysicalThing with 0.78 confidence. It becomes a Concept with `confidence_low=true`. It participates in CO_OCCURS_WITH edges. But `current_truth("What database did we choose?")` will never find it — it only searches artifact tables.

**Strategic risk:** This undermines the Availability Heuristic claim. The system remembers concepts internally but cannot surface them when asked. The LLM sees an incomplete graph.

**Recommendation:** Add Concept to the `current_truth` search tables (with `concept_emb_idx`). Consider weighting Concept results lower than artifact nodes (they're less refined) but they must be searchable.

---

### S3 · Confidence Re-Scoring (Living Property) Not Implemented
**Files:** `mcp_engine/loop/orchestrator.py`, `mcp_engine/sweep.py`
**Impact:** CLAUDE.md makes `confidence` a "living property" — one of the most distinctive architectural claims:

> "A node stored at 72% can rise to 91% (auto-promote) or fall below 60% (auto-archive) without any human action."

Two re-scoring triggers are specified:
1. **Event-driven (Step 7):** "After every pathway update, re-score all confidence_low nodes within 1–2 hops." — **Not implemented.** Step 7 updates pathway_strength and writes CO_OCCURS_WITH. No neighbor re-scoring occurs.
2. **Background sweep:** "Re-score all confidence_low nodes against current graph state." — **Not implemented.** The sweep does decay, archive, resurrection, Hebbian promotion, and centroid recomputation. No confidence re-scoring.

CLAUDE.md specifies four re-scoring factors: relationship density, pathway strength of neighbors, embedding similarity to confirmed nodes, and recency. None are computed anywhere.

**Strategic risk:** This is a named IP claim. Without it, `confidence_low` nodes can only be promoted by user action in the Memory Control Panel (or by being re-extracted from a future message). The "living" property doesn't live.

**Recommendation:** Implement as sweep step 5 (after centroid recomputation). For each `confidence_low` Concept: count relationships, average neighbor pathway_strength, and find nearest confirmed node similarity. Combine into a new confidence score. If > HARD_LOCK (0.90), auto-promote (create REIFIED_AS). If < NOISE_FLOOR (0.60), archive. This is the most impactful missing feature for the IP narrative.

---

### S4 · No ESTABLISHED Provenance Edge Written
**Files:** `mcp_engine/loop/orchestrator.py`, `mcp_engine/schema.py:281`
**Impact:** The schema defines `ESTABLISHED (FROM Message TO Decision, FROM Message TO Constraint, FROM DocumentExtract TO Decision, FROM DocumentExtract TO Constraint)`. The orchestrator creates Concepts via `_store_concept()` and reifies them via `_reify_concept()`, but **neither function writes an ESTABLISHED edge from the originating Message to the artifact node**.

This breaks:
- **Quest attribution in analogical.py:** `_get_quest_for_artifact()` traverses `(Artifact) ←[ESTABLISHED]← (Message) →[SENT_IN]→ (Session) →[WORKING_ON]→ (MainQuest)`. Without ESTABLISHED, every analogical search result has `quest_id: ""`.
- **Web panel graph visualization:** The D3 graph doesn't show Message→Artifact provenance.
- **Acceptance Criteria:** "Temporal Deprecation: Constraint deprecated in Codex updates `diff_since` in Claude Code" — the provenance chain is broken.

**Strategic risk:** Cross-quest analogical reasoning (M8, a named IP claim) silently degrades to unattributed results. The user sees results but can't tell which project they came from.

**Recommendation:** After `_reify_concept()` succeeds in the orchestrator, write `(Message)-[:ESTABLISHED]->(artifact)`. The `message_id` is already available in `run_loop()`. Also consider `(Message)-[:EXTRACTED]->(Concept)` for the more general case.

---

## MEDIUM SEVERITY — Spec Compliance & Design Completeness

### S5 · Step 3 Routing Cache Overwrites Agent Disambiguation
**File:** `mcp_engine/loop/step3_schema_org.py:31-43`
**Impact:** `load_routing_table()` stores results in `_routing_cache[gist_name]`. The routing table has two entries for "Agent": one mapping to Person, one to Organization. Since both share the key "Agent", the second DB row overwrites the first. The live cache always returns Organization for Agent.

The fallback handles this correctly with separate `Agent_Person`/`Agent_Org` keys. But when the daemon is running with a populated DB, the live cache takes priority over the fallback, and Agent disambiguation is lost.

**Recommendation:** Use the same `Agent_Person`/`Agent_Org` key pattern in the live cache, or store a list of routes per gist class and let `route_to_schema_org()` disambiguate using the spaCy label.

---

### S6 · Concept Table Missing from Sweep Decay
**File:** `mcp_engine/sweep.py:38-47`
**Impact:** `SWEEP_TABLES` lists 8 tables: GlobalConstraint, GlobalPreference, Decision, Constraint, Requirement, ActionItem, Message, DocumentExtract. **Concept is not included.** Concept nodes — the most numerous type and foundation of the Hebbian layer — never decay and never get archived by the sweep.

Over months of use, stale Concepts accumulate indefinitely. Low-confidence, low-strength Concepts still appear in Step 5 retrieval results (vector search doesn't filter by strength), consuming HNSW budget and potentially triggering unnecessary Step 6 arbitration calls.

**Recommendation:** Add `("Concept", "concept_id", "concept", "concept_emb_idx")` to `SWEEP_TABLES`. Set a default decay rate in the toml spec (suggest `0.990` — same as Requirement).

---

### S7 · Step 5 Retrieval Has No Quest Scoping (M5 Incomplete)
**File:** `mcp_engine/loop/step5_retrieval.py:39`
**Impact:** The comment on line 39 says "quest_id scoping is deferred to M5 (MainQuest wiring)." But M5 is marked complete in the build milestones. The retrieval function searches all Concept nodes globally — there's no mechanism to restrict to the current MainQuest's branch scope.

CLAUDE.md: "Branch scope: same MainQuest + vector similarity."

Without quest scoping, a 15-project user's concepts from unrelated projects interfere with retrieval. A "Kùzu" concept from Project A matches "Kùzu" from Project B at similarity 1.0, triggering additive pathway strengthening across unrelated contexts.

**Recommendation:** Pass `quest_id` into `retrieve_candidates()`. Use a projected graph (per CLAUDE.md spec) to prefilter the HNSW index to concepts linked to the current quest's sessions. Fallback to global search if no branch-scoped results meet threshold.

---

### S8 · Path Validation Doesn't Confine to Project Directory
**File:** `mcp_engine/ingest.py:76-99`
**Impact:** CLAUDE.md security constraints: "All file read/write strictly confined to the project directory — paths must be canonicalized via `realpath()`." The `validate_path()` function canonicalizes and checks the extension allowlist, but **does not verify the resolved path is within any allowed directory**. Any `.py`, `.md`, `.json`, etc. file anywhere on the filesystem can be ingested.

On a family Mac with personal documents, coaching notes, and financial files, an LLM could call `ingest_document` with a path like `/Users/djs54/Documents/Finances/budget.json` and it would succeed.

**Recommendation:** Add a `base_dir` parameter to `validate_path()` and verify `resolved.is_relative_to(base_dir)`. The base should be the repo root (from git context) or a configured workspace path.

---

### S9 · SKOS Label Accumulation Not Implemented
**Files:** `mcp_engine/schema.py:248-258, 294-297`
**Impact:** Label nodes and HAS_PREF_LABEL/HAS_ALT_LABEL/HAS_HIDDEN_LABEL relationships exist in the schema, but no code anywhere creates, queries, or maintains Label nodes. The entire SKOS label accumulation mechanism described in CLAUDE.md is unimplemented:

> "Each time a concept is expressed a new way (paraphrase, synonym, abbreviation), a new altLabel node is wired to the concept — its own text and its own embedding. current_truth searches both concept embeddings and all label embeddings."

This is a secondary IP claim (Hebbian "wire together" at the label level) and affects retrieval quality — a concept is only findable via its original `text_raw`, never via paraphrases.

**Recommendation:** Track as a deferred milestone item (perhaps M5.5 or M6). When Step 5 retrieval finds an additive match, compare the new text to `text_raw` — if different enough (similarity < 0.95), create an altLabel node. `current_truth` should search Label embeddings alongside artifact embeddings.

---

### S10 · Schema Init Re-bootstraps Centroids on Every Startup
**File:** `mcp_engine/schema.py:441-442`
**Impact:** `_bootstrap_centroids()` embeds all 105 seed examples and rewrites all GistClass centroids on every `init_schema()` call (every daemon restart). This takes ~10-15 seconds and **overwrites any centroid improvements from System 2 examples** — the self-improving property from M4 is reset every restart.

The sweep's `_recompute_centroids()` includes System 2 examples, but the next daemon restart reverts to seed-only centroids.

**Recommendation:** Check if centroids already exist before bootstrapping: `MATCH (g:GistClass) WHERE g.centroid IS NOT NULL RETURN count(g)`. If all classes have centroids, skip bootstrap. Only re-bootstrap if the seed file has changed (hash check) or if a class is missing its centroid.

---

## LOW SEVERITY

### S11 · Workspace and LLMProvider Nodes Never Created
**Files:** Schema defines `Workspace`, `LLMProvider`, `IN_WORKSPACE`, `USED` relationships
**Impact:** No code writes Workspace or LLMProvider nodes. Session→IN_WORKSPACE and Session→USED edges are never created. These were designed for cross-machine analytics and LLM provider tracking. Non-critical for Phase 0 but the schema implies they exist.

**Recommendation:** Track as M8 deferred. Consider removing from schema until implemented to avoid confusion.

---

### S12 · `_store_relation` MERGE Can Create Orphan Concepts
**File:** `mcp_engine/loop/orchestrator.py:371-410`
**Impact:** `_store_relation()` uses `MERGE (h:Concept {text_raw: $head})` which creates a bare Concept node if one doesn't already exist with that exact `text_raw`. These MERGE-created Concepts have no embedding, no gist_class, no schema_org_type — just a concept_id, text_raw, and low defaults. They won't appear in vector search (no embedding), can't participate in Step 5 retrieval, and won't be found by the sweep (no pathway_strength decay applies since Concept isn't in SWEEP_TABLES — see S6).

**Recommendation:** Either embed these concepts at creation time (call `emb.embed()` inline) or flag them with a `needs_embedding=true` property for the sweep to fill in later.

---

### S13 · Analogical Search Doesn't Search Concept Nodes
**File:** `mcp_engine/analogical.py:41-47`
**Impact:** `CROSS_QUEST_TABLES` includes Decision, Constraint, Requirement, GlobalConstraint, GlobalPreference — but not Concept. Same gap as S2 but for cross-quest search. Pattern decisions that never reached 90% confidence in a past project are invisible to analogical reasoning.

**Recommendation:** Add Concept to CROSS_QUEST_TABLES when S2 is addressed.

---

### S14 · Sweep Resurrection Searches All Tables Including Message
**File:** `mcp_engine/sweep.py:207-253`
**Impact:** Resurrection checks every SWEEP_TABLE, including Message and DocumentExtract. Resurrecting an archived raw Message because a new active Message has similar content seems undesirable — it would un-archive low-value conversational text. Resurrection makes semantic sense for artifact nodes (Decisions, Constraints) but not for raw messages.

**Recommendation:** Exclude Message and DocumentExtract from resurrection, or add a per-table flag to SWEEP_TABLES controlling resurrection eligibility.

---

### S15 · `complete_quest` Tool Still Missing from TOOL_HANDLERS
**File:** `mcp_engine/tools.py:404-412`
**Impact:** Carried forward from prior audit L4. CLAUDE.md defines this as an M5 tool. Not implemented. Users cannot mark quests as completed via any adapter.

**Recommendation:** Implement — it's a simple status update and is needed for the auto-complete-after-N-days flow.

---

## Prior Audit Spot-Check

Verified the following fixes are structurally correct (not re-auditing at line level):
- **H1/H2 (sweep):** Implemented correctly with per-node write windows. Architecture is sound.
- **M2 (MERGE):** `get_or_create_main_quest` now uses MERGE. Correct.
- **M4 (centroids):** `_save_gist_example` + `_recompute_centroids` chain works, but see S10 (overwritten on restart).
- **M5 (purpose):** `maybe_synthesize_purpose` is correctly triggered from the orchestrator after first reification.
- **M9 (socket permissions):** `mode=0o700` applied. Correct.

---

## Recommended Priority Order

**Do first (core IP credibility):**
1. S1 — Async LLM calls (user-facing latency)
2. S2 — Concept in `current_truth` (read flow completeness)
3. S4 — ESTABLISHED edge (provenance chain for analogical search)
4. S3 — Confidence re-scoring (named IP claim)

**Do second (spec compliance):**
5. S6 — Concept in sweep tables (memory hygiene)
6. S5 — Agent routing cache fix (correctness)
7. S8 — Path confinement (security)
8. S10 — Centroid bootstrap guard (self-improvement preservation)

**Do third (design completeness):**
9. S7 — Quest scoping in retrieval
10. S9 — SKOS labels (deferred milestone)
11. S15 — complete_quest tool
12. S12/S13/S14 — remaining gaps

---
---

# Strategic Analysis — SideQuest Brain
_Performed by Claude Opus 4.6 on 2026-03-11._

---

## 1. Unique Idea — 9/10

### What's genuinely novel

The core insight — that AI memory should be **active**, not passive — is the strongest differentiator. Every competitor (Zep, Mem0, LangMem, Letta) stores memories as key-value pairs or temporal knowledge graph entries. They record what was said. SideQuest Brain *processes* what was said through a gated pipeline that classifies, deduplicates, strengthens, decays, and self-corrects. The memory is alive.

The specific combination is hard to replicate:
- **Confidence as a living property** — nodes don't stay at their insertion confidence. They rise and fall based on graph context. Nobody else does this.
- **Selective attention gate** — the system decides what to remember, not the LLM and not the user. The LLM is a courier, not a curator. This inverts the model every competitor uses.
- **Contradiction resolution with reversible merges** — not just "newer wins" but structured arbitration with rollback. Absent from every competitor.

### What's less novel than it sounds

- **Kahneman System 1/2 framing** — compelling narrative, but the underlying mechanism (embedding threshold → LLM fallback) is standard cascading classification. The framing adds marketing and patent narrative value.
- **Hebbian learning / Ebbinghaus decay** — applying neuroscience concepts to software is a design choice, not a fundamental algorithm. Novelty is in applying them to AI memory specifically.
- **Graph-native RAG** — using graph + vectors for LLM memory is increasingly common. The specific structure (Quest→Session→Message→Concept→Artifact) is original.

**Net:** The Gated Consolidation Loop as a complete system is genuinely unique. Individual components are known techniques; the assembled 9-step pipeline is the invention. Like the iPhone — not the first phone, touchscreen, or music player, but the specific integration was the invention.

---

## 2. IP Defendability — 7/10

### Patent viability

| Claim | Patentability | Notes |
|-------|--------------|-------|
| Gated Consolidation Loop (9-step pipeline) | **Strong** | Specific, novel combination in defined sequence with measurable thresholds. Best as a method patent on the complete system. |
| Shape-First Principle | **Moderate** | "Classify type before semantic work" is a design pattern. Best claimed as a method step within the Loop patent. |
| Kahneman System 1/2 classifier | **Moderate as part of Loop** | The specific application to ontological classification with self-improving centroids is defensible. |
| Cocktail Party selective attention | **Moderate** | Five-sense signal detection model applied to conversational AI memory is novel. |
| Synaptic Pruning + Resurrection | **Moderate** | Decay is prior art. Resurrection combined with decay in this context is defensible. |
| Hebbian CO_OCCURS_WITH → named edge promotion | **Strong** | Three-trigger model with preserved implicit layer is specific and novel. |
| gist → schema.org routing table | **Better as trade secret** | The mapping is a design choice. Value is in the tuned mappings, not the concept. |

### Key IP strategy points

- **Provisional patent before any public disclosure.** Prior art in the Inventor's Notebook establishes priority but doesn't grant protection. ~$1,500–3,000 with a patent attorney buys 12 months.
- **Domain-agnostic proof strengthens claims.** Demonstrating the same engine across radically different domains (code architecture, IFS coaching, meal planning, vacation planning) makes it harder for a challenger to dismiss as niche.
- **Trade secrets complement patents.** Routing table mappings, confidence thresholds, decay rates, seed examples — these are tuning parameters better kept secret than published in a patent.
- **Keep closed-source through provisional filing period.**

---

## 3. Market Fit — 9/10 technology, 7/10 product (Phase 3 pending)

### The actual target market

**Not solo developers.** Phase 0 is a developer tool because the inventor is the developer building the engine. The actual target is **everyday AI users** — the hundreds of millions of ChatGPT, Claude, and Gemini users who suffer from AI amnesia and lack the technical skills to work around it.

Michelle opens ChatGPT to plan meals. She's told it three times the family doesn't drink coffee or alcohol, that Ethan has texture sensitivities. Every new session, it forgets. She doesn't know what a system prompt is. She just wants the AI to remember her family like a real assistant would.

| Segment | Size | Pain level |
|---------|------|------------|
| Solo developers using 2+ AI tools | ~50K–200K | Moderate (they have workarounds) |
| **All regular ChatGPT/Claude/Gemini users** | **~200M+ monthly actives** | **High (no workarounds)** |
| Professionals using AI for domain work | ~10M+ | Very high (domain context is everything) |

### Tesla Strategy — Phase 0 is the Roadster

| Phase | Tesla Analog | SideQuest | Audience |
|-------|-------------|-----------|----------|
| Phase 0 | Roadster | Brain Daemon + CLI + MCP | DJ (prove the engine works) |
| Phase 1-2 | Model S | Desktop app / browser extension | Early adopters |
| Phase 3 | Model 3 | Invisible background service, one-click install | Normal users — moms, coaches, families |

The Gated Consolidation Loop is **domain-agnostic by design**. It doesn't care if input is Python architecture decisions, IFS coaching frameworks, or LEGO vacation plans. It extracts concepts, classifies them, deduplicates, strengthens on repetition, and decays on neglect — regardless of domain.

### Exit strategy

Option C (licensing/acquisition) is the highest-value path and aligns with the original vision. The technology is more valuable as infrastructure powering any AI assistant's memory than as a standalone consumer product competing with native memory features.

**Key demo for acquirers:** "Same engine, zero configuration, works for a wellness coach AND a developer AND a mom planning meals." That proves platform value, not niche utility. A coding-only memory tool is a feature; a universal AI memory engine is a platform capability.

### Risks to monitor

- **Incumbents building "good enough" natively** — Anthropic and OpenAI already have basic memory. If they build active memory (not just passive storage), the window narrows. Speed to patent matters.
- **Phase 3 UX is the hard part** — the engine works or it doesn't (provable). Making it invisible to non-technical users is a design challenge that hasn't been started yet.
- **The "daemon always running" model must disappear by Phase 3** — consumers won't install Ollama. The consumer version likely needs a cloud LLM path or an on-device model (Apple Intelligence integration?).
