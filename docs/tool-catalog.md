# SideQuests Brain — Tool Catalog

> **Version:** March 29, 2026 | **Source of truth:** `mcp_engine/tool_schemas.py` + `mcp_engine/tools/__init__.py`
> 
> This catalog documents every tool available in SideQuests Brain, both active (callable by agents)
> and passive (internal processing). Use this for: integration testing, agent training, adapter validation.

---

## Quick Reference: All 26 MCP Tools

| # | Tool Name | Category | Called By | Blocking? | Requires LLM? |
|---|-----------|----------|-----------|-----------|----------------|
| 1 | `notify_turn` | Passive Ingestion | Agent (every turn) | No (fire-and-forget) | No (queues for Loop) |
| 2 | `current_truth` | Retrieval | Agent (before answering) | Yes (returns results) | No |
| 3 | `explore_graph` | Retrieval | Agent (follow-up) | Yes | No |
| 4 | `recall_relevant_lessons` | Retrieval | Agent | Yes | No |
| 5 | `recall_plans` | Retrieval | Agent (before planning) | Yes | No |
| 6 | `analogical_search` | Retrieval | Agent | Yes | No |
| 7 | `branch_quest` | Quest Management | Agent (offer first) | Yes | No |
| 8 | `complete_quest` | Quest Management | Agent | Yes | Yes (lesson synthesis) |
| 9 | `set_quest` | Quest Management | Agent | Yes | No |
| 10 | `diff_since` | Quest Management | Agent | Yes | No |
| 11 | `get_open_loops` | Quest Management | Agent | Yes | No |
| 12 | `register_plan` | Active Planning | Agent (before executing) | Yes | No |
| 13 | `report_outcome` | Active Planning | Agent (after executing) | Yes | No (may trigger lesson) |
| 14 | `upsert_lesson` | Lesson System | Agent | Yes | No |
| 15 | `context_status` | Monitoring | Agent | Yes | No |
| 16 | `get_anomalies` | Monitoring | Agent | Yes | No |
| 17 | `ingest_document` | Ingestion | Agent | Yes | Yes (Loop processing) |
| 18 | `get_openclaw_prompt` | Infrastructure | OpenClaw plugin | Yes | No |
| 19 | `register_task_graph` | Execution DAG | Agent | Yes | No |
| 20 | `get_ready_tasks` | Execution DAG | Agent | Yes | No |
| 21 | `advance_task` | Execution DAG | Agent | Yes | No |
| 22 | `fail_task` | Execution DAG | Agent | Yes | No |
| 23 | `get_task_graph` | Execution DAG | Agent | Yes | No |
| 24 | `get_disambiguation_queue` | Curation | Human UI / Agent | Yes (human review) | No |
| 25 | `resolve_disambiguation` | Curation | Human UI / Agent | Yes (human resolution) | No |
| 26 | `reload_domain_dictionary` | Ingestion | Human UI / Agent | No (non-blocking) | No |
| 27 | `publish_mechanic_summary` | ARC World-Model | ARC Agent | No (fire-and-forget) | No |
| 28 | `recall_mechanic_priors` | ARC World-Model | ARC Agent | Yes | No |

---

## Passive Processing (Not Directly Callable — Internal)

These processes run inside the Brain Daemon without explicit tool calls.

| # | Process | Trigger | Purpose |
|---|---------|---------|---------|
| P1 | **Gated Consolidation Loop** | Every `notify_turn` call | 9-step NER → classify → store pipeline |
| P2 | **Background Sweep: Decay** | Every 300s (configurable) | Apply Ebbinghaus decay to pathway_strength |
| P3 | **Background Sweep: Resurrection** | Every 300s | Un-archive nodes matching active graph |
| P4 | **Background Sweep: Re-scoring** | Every 300s | Update confidence_low nodes |
| P5 | **Background Sweep: Hebbian Promotion** | Every 300s | Promote CO_OCCURS_WITH → named edges |
| P6 | **Background Sweep: Centroid Update** | Every 300s | Recompute gist class centroids |
| P7 | **Passive Plan Detection (B68)** | During notify_turn | Detect numbered/bulleted plans in messages |
| P8 | **Retrospective Plan Inference (B68)** | During sweep | Infer plans from consecutive PlannedEvent messages |
| P9 | **Outcome Signal Detection (B69)** | During notify_turn Step 4 | Detect success/failure language |
| P10 | **Hippocampus Routing (B17)** | During notify_turn | Route session to correct MainQuest |
| P11 | **Working Memory Tracking (B18)** | During current_truth | Track LOADED edges, token estimates |
| P12 | **Anomaly Detection (B12)** | During Loop Step 4 | Flag content contradicting GlobalConstraints |

---

## Active Tool Details

### 1. `notify_turn` — Passive Ingestion

**Purpose:** Forward each conversation turn to the Brain for background memory processing.

**When to call:** After EVERY assistant response. Never skip.

**Input:**
```json
{
  "role": "user" | "assistant",
  "content": "The full text of the turn",
  "session_id": "uuid"
}
```

**Output:** `{ "status": "queued" }` — always immediate.

**What happens internally:**
1. Message node created and linked to Session
2. Hippocampus routes session to correct MainQuest (B17)
3. Content queued for Gated Consolidation Loop (Steps 1–7)
4. Passive plan detection scans for numbered/bulleted steps (B68)
5. Outcome signal detection scans for success/failure language (B69)

**Integration test cases:**
- T1: Empty content returns `{ "status": "skipped" }`
- T2: Valid turn returns `{ "status": "queued" }` in <50ms
- T3: Role must be "user" or "assistant"
- T4: Missing session_id returns error
- T5: Content >4000 chars is truncated at sentence boundary

---

### 2. `current_truth` — Retrieval

**Purpose:** Retrieve relevant memory before answering architecture or past-decision questions.

**When to call:** Before answering any question about past decisions, constraints, or architecture.

**Input:**
```json
{
  "query": "What database did we choose?",
  "session_id": "uuid",
  "scope": "branch" | "global" | "both",
  "limit": 10,
  "include_rationale": false
}
```

**Output:** Array of ranked results with `node_id`, `text_raw`, `type`, `confidence`, `pathway_strength`, `similarity`, `rank`.

**Ranking formula:** `(similarity × 0.5) + (strength_norm × 0.3) + (recency × 0.2) × (1 + outcome_boost)`

**Integration test cases:**
- T1: Empty query returns error
- T2: Missing session_id returns error
- T3: scope="branch" only returns current quest artifacts
- T4: scope="global" returns GlobalConstraint/GlobalPreference
- T5: Results are sorted by rank descending
- T6: confidence_low results are included but flagged
- T7: Archived nodes are excluded
- T8: Already-loaded nodes (LOADED edge) are demoted via dedup factor
- T9: include_rationale=true includes 1-hop ESTABLISHED_IN message context

---

### 3. `explore_graph` — Graph Traversal

**Purpose:** Directed multi-hop traversal from a seed node following relationships.

**When to call:** After `current_truth` returns a node_id you want to explore further.

**Input:**
```json
{
  "start_node_id": "uuid",
  "session_id": "uuid",
  "depth": 3,
  "strategy": "dfs" | "bfs",
  "edge_types": ["REQUIRES", "ENABLES"],
  "direction": "outgoing" | "incoming" | "both",
  "context_window": 0
}
```

**Output:** Graph traversal results with nodes and edges discovered.

**Integration test cases:**
- T1: Invalid start_node_id returns error
- T2: depth > 5 clamped to 5
- T3: Unknown edge_types in `edge_types` array filtered with warning
- T4: MAX_NODES=1000 limit respected
- T5: No infinite loops on cyclic graphs
- T6: context_window is clamped to 0..3 and returned in response metadata

---

### 4. `recall_relevant_lessons` — Lesson Retrieval

**Purpose:** Retrieve domain-specific lessons or best practices.

**When to call:** When starting work in a known domain, to avoid repeating past mistakes.

**Input:**
```json
{
  "query": "common pitfalls with async Python",
  "domain": "python",
  "limit": 5
}
```

**Output:** Array of Lesson nodes ranked by similarity.

**Integration test cases:**
- T1: Domain filter restricts results to matching domain
- T2: No domain filter returns all lessons
- T3: Results include lesson_type field

---

### 5. `recall_plans` — Historical Plan Retrieval

**Purpose:** Find similar past plans and their outcomes before formulating a new strategy.

**When to call:** Before calling `register_plan`, to learn from past attempts.

**Input:**
```json
{
  "goal_query": "migrate database schema",
  "session_id": "uuid",
  "min_valence": 0.0,
  "limit": 5
}
```

**Output:** Array of Plan nodes ranked by `similarity × |valence| × pathway_strength`, including step-level outcomes.

**Integration test cases:**
- T1: Returns plans sorted by composite rank
- T2: min_valence filters out low-outcome plans
- T3: Each plan includes steps with per-step valence
- T4: Abandoned plans included with negative valence

---

### `recall_procedures` — Procedure Retrieval (B194)

**Purpose:** Retrieve reusable, parameterized Procedure templates distilled from successful historical Plans. Filter by `archetype` or use a semantic `query` to find nearest procedures by embedding.

**When to call:** Before planning or when seeking a reusable strategy template for a new puzzle or task.

**Input:**
```json
{
  "archetype": "spatial-nav",
  "query": "navigate to player",
  "limit": 3
}
```

**Output:** Array of Procedure objects with `procedure_id`, `name`, `description`, `steps_json`, `success_count`, and `success_rate`.

**Integration test cases:**
- T1: `archetype` filter returns top procedures by success_rate
- T2: `query` performs vector search over `Procedure` embeddings
- T3: Procedures include provenance via `DISTILLED_FROM` edges
- T4: Newly created procedures appear in subsequent recall results

---

### 6. `analogical_search` — Cross-Quest Search

**Purpose:** Search across ALL historical quests for similar patterns.

**When to call:** When starting a new project that might benefit from past experience.

**Input:**
```json
{
  "query": "microservices vs monolith decision",
  "current_quest_id": "uuid",
  "limit": 5,
  "min_similarity": 0.70
}
```

**Output:** Cross-quest results excluding current quest.

**Integration test cases:**
- T1: current_quest_id results are excluded
- T2: min_similarity threshold respected
- T3: Completed quests are primary source

---

### 7. `branch_quest` — Create SideQuest

**Purpose:** Declare a tangent worth tracking separately from the main project.

**When to call:** Offer to the user (don't call unilaterally) when conversation shifts to a distinct tangent.

**Input:**
```json
{
  "name": "Investigate Kùzu alternative",
  "purpose": "Evaluate RyuGraph as migration target",
  "parent_quest_id": "uuid"
}
```

**Output:** `{ "side_quest_id": "uuid" }`

**Integration test cases:**
- T1: Returns valid side_quest_id
- T2: SideQuest linked to parent via BELONGS_TO edge
- T3: Missing parent_quest_id auto-links to current MainQuest

---

### 8. `complete_quest` — Mark Quest Finished

**Purpose:** Mark a quest as completed, triggering lesson synthesis.

**Input:**
```json
{
  "quest_id": "uuid"
}
```

**Output:** Completion confirmation + synthesized lessons.

**Integration test cases:**
- T1: Quest status set to "completed"
- T2: completed_at timestamp set
- T3: Completed quest excluded from branch-scope current_truth
- T4: Lesson synthesis triggered as background task

---

### 9. `set_quest` — Explicit Quest Override

**Purpose:** Bind the session to a named project/quest.

**Input:**
```json
{
  "session_id": "uuid",
  "quest_name": "SideQuests Brain",
  "quest_id": "uuid"
}
```

**Output:** Quest binding confirmation.

**Integration test cases:**
- T1: New quest created if name doesn't match existing
- T2: Existing quest bound if name matches
- T3: quest_id takes precedence over quest_name

---

### 10. `diff_since` — Delta Retrieval

**Purpose:** Return artifacts created since a given timestamp.

**Input:**
```json
{
  "since_iso": "2026-03-28T00:00:00Z",
  "limit": 20
}
```

**Output:** Decisions, constraints, requirements created after the timestamp.

**Integration test cases:**
- T1: Only returns artifacts after since_iso
- T2: Limit respected
- T3: Invalid ISO format returns error

---

### 11. `get_open_loops` — Confidence Review

**Purpose:** Surface uncertain knowledge items for human review.

**Input:**
```json
{
  "limit": 20
}
```

**Output:** confidence_low nodes awaiting confirmation.

**Integration test cases:**
- T1: Only returns confidence_low=true nodes
- T2: Archived nodes excluded
- T3: Ordered by pathway_strength descending

---

### `get_knowledge_gaps` — Knowledge Gap Detection (B193)

**Purpose:** Return active KnowledgeGap nodes identified by the background sweep. Useful for agents to proactively check domains or archetypes where lessons are missing or low-quality.

**Input:**
```json
{
  "limit": 10,
  "unresolved_only": true,
  "min_severity": 0.0
}
```

**Output:** Array of KnowledgeGap objects with `gap_id`, `domain`, `gap_type`, `description`, `severity`, `message_count`, and `lesson_count`.

**Integration test cases:**
- T1: unresolved_only=true returns only unresolved gaps
- T2: gaps sorted by severity desc
- T3: min_severity filters low-severity items
- T4: gaps auto-resolve when lessons are created and confidence rises

---

---

### 12. `register_plan` — Declare Strategy

**Purpose:** Declare a multi-step strategy before execution. Returns warnings from similar past plans.

**When to call:** When formulating a multi-step approach to a problem.

**Input:**
```json
{
  "goal": "Refactor authentication to use OAuth2",
  "steps": [
    "Add OAuth2 dependency",
    "Create auth middleware",
    "Migrate existing sessions",
    "Write integration tests"
  ],
  "session_id": "uuid",
  "strategy": "Incremental migration with feature flag"
}
```

**Output:**
```json
{
  "plan_id": "uuid",
  "step_count": 4,
  "warnings": ["Similar plan failed 2 weeks ago: ..."],
  "suggestions": ["Similar plan succeeded with: ..."]
}
```

**What happens internally:**
1. Plan node + PlanStep chain created
2. Steps linked by NEXT_STEP edges
3. Plan linked to Session (PLANNED_IN) and Quest (TARGETS)
4. Similarity search against past Plans → Amygdala Reflex warnings
5. Positive past plans returned as suggestions

**Integration test cases:**
- T1: Returns valid plan_id
- T2: step_count matches input steps length
- T3: Steps linked by NEXT_STEP edges in order
- T4: Plan linked to current session
- T5: Warning returned if similar past plan has valence < -0.5
- T6: Suggestion returned if similar past plan has valence > 0.5
- T7: Minimum 1 step required, maximum 20

---

### 13. `report_outcome` — Report Results

**Purpose:** Report step-level or plan-level outcome with valence scoring.

**When to call:** After key steps complete or when the overall plan finishes.

**Input:**
```json
{
  "plan_id": "uuid",
  "step_number": 2,
  "outcome": "Migration succeeded, all tests passing",
  "valence": 0.9,
  "session_id": "uuid",
  "valence_source": "test_result"
}
```

**Output:** Confirmation with updated plan/step status.

**What happens internally:**
1. PlanStep status updated (succeeded/failed based on valence sign)
2. OUTCOME_SIGNAL edges created to related Concepts
3. If |valence| > 0.7, automatic Lesson extraction triggered
4. If all steps reported, Plan status updated to "completed"
5. Negative valence propagates to ACTS_ON Concept nodes

**Integration test cases:**
- T1: Valid plan_id required
- T2: Valence must be -1.0 to +1.0
- T3: step_number optional (plan-level if omitted)
- T4: Lesson auto-generated when |valence| > 0.7
- T5: Plan auto-completed when all steps reported
- T6: Invalid plan_id returns error

---

### 14. `upsert_lesson` — Save Lesson

**Purpose:** Explicitly add or update a domain-specific lesson.

**Input:**
```json
{
  "text": "Always use parameterized Cypher queries — string interpolation enables injection",
  "domain": "kuzu",
  "lesson_type": "mistake",
  "session_id": "uuid"
}
```

**Output:** `{ "lesson_id": "uuid" }`

**Integration test cases:**
- T1: Returns valid lesson_id
- T2: lesson_type must be one of: mistake, edge-case, optimization, architecture-principle
- T3: Lesson linked to Session via LEARNED edge
- T4: Duplicate text returns existing lesson_id (idempotent)

---

### 15. `context_status` — Token Accounting

**Purpose:** Check context window health — token usage, loaded nodes, handoff suggestions.

**Input:**
```json
{
  "session_id": "uuid"
}
```

**Output:**
```json
{
  "token_estimate": 45000,
  "token_limit": 128000,
  "utilization_pct": 35.2,
  "loaded_node_count": 12,
  "bloat_warning": false,
  "handoff_suggestion": null
}
```

**Integration test cases:**
- T1: Valid session_id returns token stats
- T2: bloat_warning=true when utilization > 75%
- T3: handoff_suggestion populated when prior session exists

---

### 16. `get_anomalies` — Security Monitoring

**Purpose:** Retrieve flagged anomalies (potential prompt injections or constraint violations).

**Input:**
```json
{
  "scope": "branch",
  "limit": 20,
  "quest_id": "uuid"
}
```

**Output:** Array of anomaly records with type, confidence, and detected_at.

**Integration test cases:**
- T1: Returns ANOMALY_DETECTED edges
- T2: Scope filter works correctly
- T3: Empty result when no anomalies

---

### 17. `ingest_document` — File Ingestion

**Purpose:** Ingest a local file into the knowledge graph.

**Input:**
```json
{
  "file_path": "/absolute/path/to/document.md",
  "quest_id": "uuid"
}
```

**Output:** Ingestion summary with chunk count and status.

**Integration test cases:**
- T1: File must exist and be readable
- T2: Path confined to project root (no traversal)
- T3: Idempotent: re-ingestion skipped if content_hash unchanged
- T4: Supported extensions only (.md, .txt, .py, etc.)
- T5: Large files chunked at sentence boundaries

---

### 18. `get_openclaw_prompt` — OpenClaw Prompt

**Purpose:** Retrieve the OpenClaw plugin prompt for tool registration.

**Input:** `{}`

**Output:** Prompt text for OpenClaw tool descriptions.

**Integration test cases:**
- T1: Returns non-empty prompt string
- T2: Prompt includes all active tool names

---

### 19. `register_task_graph` — Declare Execution DAG

**Purpose:** Declare a first-class execution DAG (TaskGraph + TaskNodes) for parallel execution and dependency tracking.

**When to call:** When starting a complex, multi-task project where tasks have dependencies and can run in parallel.

**Input:**
```json
{
  "label": "ARC-AGI Solve Pipeline",
  "session_id": "uuid",
  "owner": "ARCOrchestrator",
  "tasks": [
    { "task_id": "t1", "label": "Identify shapes", "description": "Detect all objects in input grid" },
    { "task_id": "t2", "label": "Map roles", "depends_on": ["t1"] },
    { "task_id": "t3", "label": "Apply transform", "depends_on": ["t2"] }
  ]
}
```

**Output:** `{ "graph_id": "uuid", "ready_tasks": [...], "cycle_errors": [] }`

**What happens internally:**
1. TaskGraph and TaskNode nodes created
2. TASK_OF and DEPENDS_ON edges established
3. Cycle detection validates the DAG structure
4. Initial "ready" frontier (tasks with no dependencies) is returned

**Integration test cases:**
- T1: Validates DAG structure (rejects cycles)
- T2: Links all nodes correctly to the TaskGraph
- T3: Returns the correct initial topological frontier

---

### 20. `get_ready_tasks` — Query Topological Frontier

**Purpose:** Return all pending tasks whose upstream dependencies are all complete or skipped.

**When to call:** When looking for the next available tasks to execute in parallel.

**Input:**
```json
{
  "graph_id": "uuid"
}
```

**Output:** Array of ready TaskNodes.

---

### 21. `advance_task` — Update Task Status

**Purpose:** Transition a task to `active`, `complete`, or `skipped`.

**When to call:** When a task starts, finishes successfully, or is deemed unnecessary.

**Input:**
```json
{
  "graph_id": "uuid",
  "task_id": "t1",
  "status": "complete",
  "result": "Found 3 shapes: red square, blue line..."
}
```

**Output:** `{ "task_id": "t1", "new_status": "complete", "newly_unblocked": ["t2"] }`

---

### 22. `fail_task` — Report Task Failure

**Purpose:** Mark a task as failed and identify blocked dependents.

**When to call:** When a task fails and cannot be completed.

**Input:**
```json
{
  "graph_id": "uuid",
  "task_id": "t1",
  "reason": "Execution timed out"
}
```

**Output:** `{ "task_id": "t1", "status": "failed", "blocked_dependents": ["t2", "t3"] }`

---

### 23. `get_task_graph` — Audit Graph State

**Purpose:** Return full graph state (nodes + edges) for audit and coordination.

**When to call:** When needing a complete overview of the project's execution state.

**Input:**
```json
{
  "graph_id": "uuid"
}
```

**Output:** Complete TaskGraph structure with all nodes and their current statuses.

---

### 24. `get_disambiguation_queue` — Disambiguation Queue

**Purpose:** Retrieve pending DisambiguationEvent pairs created by the loop when
the arbitration step returned `uncertain`. Intended for human-in-the-loop
curation UIs.

**When to call:** Periodic UI poll or when an operator begins a curation
session; call before showing pair details to a human reviewer.

**Input:**
```json
{ "limit": 10 }
```

**Output:**
```json
{
  "pairs": [
    {
      "event_id": "uuid",
      "similarity": 0.87,
      "created_at": "2026-03-29T12:34:56Z",
      "concept_a": { "concept_id": "cA", "text_raw": "...", "alt_labels": [...] },
      "concept_b": { "concept_id": "cB", "text_raw": "...", "alt_labels": [...] },
      "shared_neighbors": [{"concept_id":"n1","text_raw":"..."}]
    }
  ],
  "total_pending": 1
}
```

**Integration test cases:**
- T1: No pending events returns empty `pairs` array
- T2: `limit` parameter respected
- T3: `concept_a`/`concept_b` include `alt_labels` array
- T4: Archived concepts are not returned in context

---

### 25. `resolve_disambiguation` — Resolve Disambiguation

**Purpose:** Apply a human resolution to a DisambiguationEvent: `merge`,
`separate`, or `skip`.

**When to call:** After a human inspects a pair and selects an action.

**Input:**
```json
{ "event_id": "uuid", "resolution": "merge" | "separate" | "skip" }
```

**Output:** `{ "result": "...", "resolution": "merge|separate|skip" }` or an error.

**Behavior notes:**
- `merge`: picks a canonical concept (older by created_at), creates an
  `Label` altLabel from the duplicate text, redirects common edges from the
  duplicate to the canonical concept, archives the duplicate, and boosts the
  canonical pathway_strength.
- `separate`: creates a `DISTINCT_FROM` edge between the two concepts and
  clears `confidence_low` on both so they no longer appear in open-loop lists.
- `skip`: leaves the event `pending` for later review.

**Integration test cases:**
- T1: Invalid `resolution` returns an error message
- T2: `merge` archives the duplicate and records an alt label
- T3: `separate` creates `DISTINCT_FROM` and clears `confidence_low`
- T4: `skip` leaves the event status unchanged

### 26. `reload_domain_dictionary` — Reload Domain Dictionary

**Purpose:** Load or refresh a workspace `domain_dictionary.yaml` into the knowledge graph,
adding new canonical `Concept` nodes and `Label` altLabels idempotently.

**When to call:** After adding or updating `.sidequests/domain_dictionary.yaml` in a workspace;
can be called from a UI button or via an adapter command.

**Input:**
```json
{ "workspace_root": "." }
```

**Output:**
```json
{ "status": "ok", "path": "/path/to/domain_dictionary.yaml", "concepts_created": 5, "concepts_skipped": 3, "alt_labels_added": 12, "total_entities": 8 }
```

**Behavior notes:**
- Idempotent: re-running does not duplicate existing `Concept` or `Label` nodes.
- Creates a `Concept` with `confidence=0.95` and a `Label` with `label_type` `preferred` for the canonical term.
- Adds `Label` nodes with `label_type` `alternative` for alt labels and wires them with `HAS_ALT_LABEL`.

**Integration test cases:**
- T1: Missing file returns an error with `searched` array
- T2: Valid file ingests expected counts and returns `status: ok`
- T3: Re-running with the same file does not increase `concepts_created`


### 27. `publish_mechanic_summary` — ARC Mechanic Memory (B226)

**Purpose:** Publish a learned ARC world-model mechanic summary to persistent graph memory.

**When to call:** After an ARC episode or key learning boundary where a reusable mechanic has been identified.

**Input:**
```json
{
  "summary": {
    "name": "Gravity Drop",
    "action_set_signature": "ACTION6",
    "confidence": 0.9,
    "hypotheses": [{"signature": "h1", "action_count": 1}],
    "effects": [{"signature": "e1", "effect_class": "motion"}],
    "failure_modes": [{"name": "blocked"}]
  },
  "async_dispatch": true
}
```

**Output:** `{ "ok": true, "mechanic_id": "mech-...", "status": "upserted" }`

**What happens internally:**
1. `ArcMechanic` node created/updated (MERGE by signature).
2. Action and effect patterns reified as `ArcActionPattern` and `ArcEffectPattern`.
3. Linked via `ARC_MECHANIC_HAS_ACTION_PATTERN` and `ARC_MECHANIC_CAUSES_EFFECT_PATTERN`.
4. Failure modes and recovery policies linked via `ARC_MECHANIC_FAILS_AS` and `ARC_FAILURE_RECOVERED_BY`.

### 28. `recall_mechanic_priors` — ARC Prior Retrieval (B227)

**Purpose:** Retrieve reusable ARC mechanic priors based on action/effect signature similarity.

**When to call:** Before beginning an ARC solve or when encountering a familiar action/effect pattern.

**Input:**
```json
{
  "signature": {
    "action_set": "ACTION6"
  },
  "limit": 5,
  "min_confidence": 0.5
}
```

**Output:** Array of ranked `ArcMechanic` objects with 1-hop expanded patterns and failure modes.


## Adapter Compatibility Matrix

| Tool | claude_code | claude_desktop | codex | chatgpt_desktop | gemini_cli | OpenClaw TS |
|------|:-----------:|:--------------:|:-----:|:---------------:|:----------:|:-----------:|
| notify_turn | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| current_truth | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| explore_graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| branch_quest | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| complete_quest | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| set_quest | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| diff_since | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| get_open_loops | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| analogical_search | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ingest_document | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| register_plan | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| report_outcome | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| recall_plans | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| register_task_graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| get_ready_tasks | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| advance_task | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| fail_task | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| get_task_graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| context_status | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| upsert_lesson | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| recall_relevant_lessons | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| get_anomalies | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| get_openclaw_prompt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| get_disambiguation_queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| resolve_disambiguation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| reload_domain_dictionary | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**✅ = Supported in adapter pass-through list**
**✅* = Registered in TypeScript but needs verification against TOOL_HANDLERS**

---

## Passive Sense Catalog (Step 4 Pattern Detection)

These "senses" fire during the Gated Consolidation Loop's Step 4 pattern matching.
They are not callable tools — they run automatically on every `notify_turn` content.

| Sense | Fires On | Signal Patterns | Confidence Range |
|-------|---------|----------------|-----------------|
| **Decision sense** | "we decided", "we chose", "we agreed", past-tense resolution | `decided|chose|agreed|resolved|concluded|selected|picked|settled` | 0.65–0.90 |
| **Constraint sense** | "never", "must", "always", "required", directive language | `must(?!\s+not)|never|always|required|forbidden|shall` | 0.65–0.90 |
| **Plan sense** (B68) | Numbered/bulleted sequences ≥3 items, future-tense action | `\b\d+[.)]\s|^[-*]\s.*\n[-*]\s|will\s|plan to|next step` | 0.70–0.85 |
| **Entity sense** | Known graph entity mentioned by name or near-match | Vector similarity > 0.75 to existing Concept | Variable |
| **Contradiction sense** | Step 5 retrieval finds 0.75–0.92 similarity to existing confirmed node | Triggered by retrieval, not pattern | 0.75–0.92 |
| **Anomaly sense** (B12) | Content contradicts high-confidence GlobalConstraint | pathway_strength > 0.8 on contradicted node | Variable |
| **Success sense** (B69) | "perfect", "great job", "approved", "all tests pass" | `perfect|great job|approved|excellent|pass(ed\|ing)?|succeeded` | Valence +0.8 |
| **Failure sense** (B69) | "that's wrong", "revert", "that broke", "start over" | `wrong|revert|broke|failed|start over|undo|rollback` | Valence -0.8 |

---

## Graph Relationship Types (Complete)

For `explore_graph` edge_types parameter and integration testing:

| Relationship | From → To | Created By | Purpose |
|---|---|---|---|
| `REQUIRES` | Concept → Concept | Step 1b / Step 3b | Dependency |
| `ENABLES` | Concept → Concept | Step 1b / Step 3b | Enablement |
| `REPLACES` | Concept → Concept | Step 1b / Step 3b | Supersession |
| `CONTRADICTS` | Concept → Concept | Step 1b / Step 3b | Conflict |
| `PART_OF` | Concept → Concept | Step 1b / Step 3b | Containment |
| `CHOSEN_OVER` | Concept → Concept | Step 3b | Decision preference |
| `IMPLEMENTS` | Concept → Concept | Step 3b | Implementation |
| `EXTENDS` | Concept → Concept | Step 3b | Extension |
| `ALTERNATIVE_TO` | Concept → Concept | Step 3b | Alternative option |
| `CO_OCCURS_WITH` | Concept → Concept | Step 7 | Hebbian co-occurrence |
| `REIFIED_AS` | Concept → Artifact | Step 4 | Type promotion |
| `DEPRECATED_BY` | Artifact → Artifact | Step 7 | Contradiction resolution |
| `BELONGS_TO` | SideQuest → MainQuest | branch_quest | Quest hierarchy |
| `DERIVED_FROM` | DocumentExtract → Document | ingest_document | Document provenance |
| `ESTABLISHED` | Message → Artifact | _reify_concept | Message provenance |
| `ESTABLISHED_IN` | Artifact → Session | _reify_concept | Session provenance |
| `HAS_PREF_LABEL` | Artifact → Label | Schema init | Canonical name |
| `HAS_ALT_LABEL` | Artifact → Label | Hebbian | Alternative name |
| `HAS_HIDDEN_LABEL` | Artifact → Label | System | Search-only name |
| `TRIGGERED` | Message → MergeEvent | Step 7 | Audit trail |
| `UPDATES_PATHWAY` | MergeEvent → Concept | Step 7 | Audit trail |
| `ROUTES_TO` | GistClass → SchemaOrgType | Schema init | Ontology routing |
| `SENT_IN` | Message → Session | notify_turn | Message provenance |
| `WORKING_ON` | Session → Quest | Hippocampus | Session binding |
| `USED` | Session → LLMProvider | Session init | Provider tracking |
| `IN_WORKSPACE` | Session → Workspace | Session init | Workspace binding |
| `LOADED` | Session → Artifact | current_truth | Working memory |
| `REROUTED_FROM` | Session → MainQuest | Hippocampus | Re-routing audit |
| `ANOMALY_DETECTED` | Artifact → GlobalConstraint | B12 detection | Security flag |
| `PRODUCED_LESSON` | MainQuest → Lesson | complete_quest | Lesson provenance |
| `PRODUCED_PLAN_LESSON` | Plan → Lesson | report_outcome | Plan lesson provenance |
| `LEARNED` | Session → Lesson | upsert_lesson | Session learning |
| `APPLIES_TO` | Lesson → Concept | Lesson system | Lesson applicability |
| `RELATED_TO` | Lesson → Lesson | Lesson system | Cross-lesson link |
| `CONTAINS_LESSON` | Message → Lesson | Lesson extraction | Message provenance |
| `PLANNED_IN` | Plan → Session | register_plan | Plan provenance |
| `TARGETS` | Plan → Quest | register_plan | Quest linkage |
| `STEP_OF` | PlanStep → Plan | register_plan | Step membership |
| `NEXT_STEP` | PlanStep → PlanStep | register_plan | Causal ordering |
| `ACTS_ON` | PlanStep → Concept | register_plan | Entity linkage |
| `OUTCOME_SIGNAL` | PlanStep → Concept | report_outcome | Valence propagation |
| `ANCHORED_TO` | MainQuest → Workspace | Schema init | Workspace binding |

---

## Node Types (Complete)

For integration testing node creation and validation:

| Node Table | ID Field | Has Embedding? | Has pathway_strength? |
|---|---|---|---|
| Concept | concept_id | ✅ FLOAT[384] | ✅ |
| Decision | decision_id | ✅ | ✅ |
| Constraint | constraint_id | ✅ | ✅ |
| Requirement | requirement_id | ✅ | ✅ |
| ActionItem | action_item_id | ✅ | ✅ |
| GlobalConstraint | global_constraint_id | ✅ | ✅ |
| GlobalPreference | global_preference_id | ✅ | ✅ |
| MainQuest | quest_id | ✅ | ✅ |
| SideQuest | quest_id | ✅ | ✅ |
| Message | message_id | ✅ | ✅ |
| DocumentExtract | extract_id | ✅ | ✅ |
| Document | document_id | ❌ | ❌ |
| Label | label_id | ✅ | ❌ |
| Lesson | lesson_id | ✅ | ✅ |
| Plan | plan_id | ✅ | ✅ |
| PlanStep | step_id | ✅ | ❌ |
| Session | session_id | ❌ | ❌ |
| MergeEvent | event_id | ❌ | ❌ |
| GistClass | name | ✅ (centroid) | ❌ |
| SchemaOrgType | name | ❌ | ❌ |
| LLMProvider | provider_id | ❌ | ❌ |
| Workspace | workspace_id | ❌ | ❌ |
