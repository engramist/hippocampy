# B-Notebook-Update — Inventor's Notebook Revision for PPA Filing

## Overview

Update the Inventor's Notebook (`InvertorsDocs/SideQuests-InventorsNotebook.md`) to reflect the actual built system as of March 20, 2026. The notebook is the primary document handed to a patent attorney for PPA filing. It must be accurate, internally consistent, and include reduction-to-practice evidence.

**Output:** An updated `InvertorsDocs/SideQuests-InventorsNotebook.md` that is PPA-ready.

## Files to Read First

| File | Why |
|------|-----|
| `InvertorsDocs/SideQuests-InventorsNotebook.md` | Current markdown notebook — the base to update |
| `CLAUDE.md` | Full technical spec — source of truth for architecture |
| `mcp_engine/tool_schemas.py` | Canonical tool names and descriptions |
| `mcp_engine/hippocampus.py` | B17 implementation — verify claims match code |
| `mcp_engine/working_memory.py` | B18 implementation — verify claims match code |
| `mcp_engine/schema.py` | Actual graph schema — verify data structures match |
| `mcp_engine/tools.py` | Tool handler implementations — verify tool surface |
| `web/server.py` | SSE endpoint — verify B3 architecture |
| `plugin/.claude-plugin/plugin.json` | Cowork plugin — new distribution mechanism |
| `backlog.md` | Current state of milestones |
| `tests/` directory | Count tests for reduction-to-practice evidence |

## Changes Required

### 1. Fix Stale Tool Names

**Search and replace throughout the entire document:**

| Old | New | Context |
|-----|-----|---------|
| `ingest_message` | `notify_turn` | Tool was renamed; Section 5.5.E and anywhere else |
| `upsert_artifacts` | Remove | This tool doesn't exist in the implementation |
| `apply_merge` | Remove | This tool doesn't exist in the implementation |

**Verify the tool surface matches `mcp_engine/tool_schemas.py`:**

The correct tool list (11 tools) is:
- `notify_turn` — forward turns to Brain
- `current_truth` — retrieve relevant memory
- `branch_quest` — create side quest
- `diff_since` — changes since prior session
- `get_open_loops` — unresolved tentative nodes
- `analogical_search` — cross-quest pattern search
- `ingest_document` — feed documents to Brain
- `explore_graph` — directed graph traversal
- `complete_quest` — mark quest as done
- `set_quest` — explicitly bind session to quest (B17)
- `context_status` — context window health (B18)

Update Section 5.5.E ("Shared Tool Surface") to list all 11 tools with accurate descriptions.

### 2. Add Journal Entry for Today's Session

Add a new journal entry at the top of the Journal of Updates section:

```markdown
March 20, 2026 (Implementation): Completed full implementation of B17 (Semantic Quest Routing / Hippocampus), B18 (Working Memory Awareness), B3 (ChatGPT Desktop SSE Endpoint), and B2 (Cowork Plugin for Claude Desktop). All features implemented and tested — 474 tests passing across the full test suite, zero failures. Extracted canonical tool schemas into shared module (mcp_engine/tool_schemas.py) to prevent tool list drift across 4 stdio adapters + SSE endpoint. Created Claude Desktop / Cowork plugin with 4 skills (memory-awareness, recall, quest-management, status) following Anthropic's knowledge-work-plugins format.
```

### 3. Update Section 5.5.C — Add Hippocampus Implementation Details

The current notebook describes the Hippocampus as a concept. Update to reflect it's now implemented code. Add after the existing Hippocampus description:

```markdown
**Implementation Status (March 20, 2026):** Fully implemented in `mcp_engine/hippocampus.py`. Key functions:
- `route_session()` — main entry point, returns (quest_id, confidence, method, is_new_quest)
- `_system1_git_match()` — legacy hash match for backward compatibility
- `_system1_semantic_match()` — Python-side cosine similarity against active quest purpose_embeddings
- `_system2_disambiguate()` — LLM picks the right quest or creates new
- `update_routing_strength()` — per-message progressive consolidation
- `reconsolidate()` — prediction error re-routing with REROUTED_FROM audit trail

Constants: S1_AUTO_BIND_THRESHOLD = 0.85, S1_ESCALATION_THRESHOLD = 0.60, CONSOLIDATION_THRESHOLD = 0.85.
Tested: 7 test classes in tests/test_hippocampus.py covering git match, semantic match, routing, consolidation, reconsolidation, set_quest, and backward compatibility.
```

### 4. Update Section 5.2.C — Add Working Memory Implementation Details

Add after the existing Working Memory description:

```markdown
**Implementation Status (March 20, 2026):** Fully implemented in `mcp_engine/working_memory.py`. Key functions:
- `track_loaded()` — creates LOADED edges when current_truth returns results
- `deduplicate_results()` — applies 0.3x demotion factor to already-loaded nodes
- `estimate_tokens()` — heuristic: len(text) // 3 chars per token
- `get_session_token_state()` — returns utilization, loaded count, bloat warning
- `check_context_health()` — fires warning at 75% utilization
- `get_handoff_context()` — retrieves top 5 LOADED nodes from prior session

Constants: BLOAT_WARNING_THRESHOLD = 0.75, DEDUP_DEMOTION_FACTOR = 0.3, DEFAULT_TOKEN_LIMIT = 128000, CHARS_PER_TOKEN = 3.
Tested: 7 test classes in tests/test_working_memory.py covering token estimation, load tracking, deduplication, context health, session handoff, token state, and context_status tool.
```

### 5. Update Section 5.4.A — Schema Accuracy

Verify the schema description matches `mcp_engine/schema.py`. Specifically:

**MainQuest** — add new fields:
- `git_repo_root STRING` — nullable, populated for git-anchored quests
- `purpose_embedding FLOAT[384]` — dedicated routing embedding
- `routing_method STRING` — "git" | "semantic_s1" | "semantic_s2" | "explicit"

**Session** — add new fields:
- `routing_state STRING` — "tentative" | "consolidated" | "locked"
- `routing_confidence DOUBLE` — 0.0–1.0
- `routing_method STRING` — how this session was routed
- `content_embedding FLOAT[384]` — running mean of message embeddings
- `token_estimate INT64`, `token_limit INT64`, `loaded_node_count INT32`, `last_injection_at TIMESTAMP`

**New relationships:**
- `REROUTED_FROM` (FROM Session TO MainQuest) — audit trail for prediction error
- `LOADED` (FROM Session TO multiple artifact types) — working memory tracking

### 6. Update Section 8 — Reduction to Practice

Replace the planned milestone descriptions with actual implementation evidence:

```markdown
## 8. Reduction to Practice

### Implementation Status (as of March 20, 2026)

All 8 core milestones (M1–M8) are fully implemented and tested. Post-M8 features B17, B18, B3, and B2 are also complete.

**Test Evidence:**
- 474 automated tests passing (0 failures, 18 skipped)
- Test categories: adapter integration (145), analogical reasoning (30), hippocampus routing (28), working memory (22), web/SSE endpoints (39), plugin structure (26), quest lifecycle, tools, schema
- All tests run in under 7 seconds on commodity hardware

**Implementation Evidence by Milestone:**
- M1 (Schema + Config): Kùzu schema with 15+ node types, 20+ relationship types, HNSW vector indexes. Centroid bootstrap from 105 gist seed examples.
- M2 (Passive Ingestion): Claude Code UserPromptSubmit hook + notify_turn MCP tool. current_truth with vector retrieval.
- M3 (Loop Steps 1–4): spaCy NER, gist System 1/2 classification, schema.org routing, Step 3b Ollama relation extraction, Step 4 pattern matching + selective attention.
- M4 (Loop Steps 5–7): Dual-scope retrieval, contradiction arbitration, pathway update + MergeEvent + synaptic pruning.
- M5 (Quest Lifecycle): Git-anchored MainQuest, manual SideQuest branching, RAG read flow, purpose capture.
- M6 (Open Brain): Document + DocumentExtract pipeline with semantic chunking.
- M7 (Memory Control Panel): FastAPI web app with graph visualization, soft-lock UI, merge rollback, Constraint Ledger export.
- M8 (Multi-Agent + Analogical): Claude Desktop, Codex, Gemini CLI adapters. Cross-quest analogical reasoning with vector search across 5 artifact tables.

**Post-M8 Features:**
- B13: One-command installer (`sidequests install`) with LLM provider choice, venv management, adapter registration, launchd daemon setup.
- B17 (Hippocampus): Semantic Quest Routing with System 1/2 routing, progressive consolidation, prediction error reconsolidation. Module: `mcp_engine/hippocampus.py`.
- B18 (Working Memory): Context window awareness with LOADED edge tracking, smart deduplication, token estimation, bloat detection, session handoff. Module: `mcp_engine/working_memory.py`.
- B3 (SSE Transport): MCP-over-SSE endpoint for ChatGPT Desktop and any HTTP-capable MCP client. Shared tool schemas extracted to `mcp_engine/tool_schemas.py`.
- B2 (Cowork Plugin): Claude Desktop / Cowork plugin following Anthropic's knowledge-work-plugins format. 4 skills, SSE-based MCP connection.

**Adapter Coverage (5 clients):**
- Claude Code (stdio adapter)
- Claude Desktop (Cowork plugin + stdio adapter)
- Codex (stdio adapter)
- Gemini CLI (stdio adapter)
- ChatGPT Desktop (SSE endpoint)
```

### 7. Add Claim #14 — Cowork Plugin as Distribution

Add to Section 5.7 (Novelty & Non-Obviousness):

```markdown
14. Declarative Knowledge Plugin Architecture: Packaging an autonomous memory engine as a file-based plugin (JSON manifest + markdown skills) that teaches an LLM when and how to use structured memory tools, without requiring code execution or build steps — enabling non-technical users to install persistent AI memory via a drag-and-drop interface.
```

### 8. Add Witness Signature Blocks

Add at the bottom of the document:

```markdown
---

## Witness Attestation

I have reviewed this Inventor's Notebook and confirm that the entries accurately describe the invention as explained to me by the inventor.

**Witness 1:**
Name: ___________________________
Signature: ___________________________
Date: ___________________________

**Witness 2:**
Name: ___________________________
Signature: ___________________________
Date: ___________________________

**Inventor:**
Name: Don J. Shelton
Signature: ___________________________
Date: ___________________________
```

### 9. Minor Cleanup

- Remove any references to `upsert_artifacts` or `apply_merge` tools (don't exist)
- Ensure all 13 existing claims in Section 5.7 are accurate to implemented code
- Verify the Prior Art section (Section 7) doesn't accidentally describe our own features as competitor features
- Check that security claims (Section 5.5.F) accurately scope to "conversation-layer only"

## Verification

1. All tool names in the document match `mcp_engine/tool_schemas.py` exactly
2. All schema descriptions match `mcp_engine/schema.py`
3. All claim descriptions match implemented code (hippocampus.py, working_memory.py, tools.py)
4. Journal entries are in reverse chronological order
5. Reduction-to-practice section cites actual test counts and module paths
6. No references to `ingest_message`, `upsert_artifacts`, or `apply_merge`
7. Witness signature blocks are present
8. Section 5.7 has 14 claims (13 existing + 1 new)
