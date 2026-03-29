# SideQuests Brain — Tool Catalog

> **Version:** March 29, 2026 | **Source of truth:** `mcp_engine/tool_schemas.py` + `mcp_engine/tools/__init__.py`
> 
> This catalog documents every tool available in SideQuests Brain, both active (callable by agents)
> and passive (internal processing). Use this for: integration testing, agent training, adapter validation.

---

## Quick Reference: All 19 MCP Tools

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
| 19 | *(reserved)* | — | — | — | — |

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
  "limit": 10
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
  "direction": "outgoing" | "incoming" | "both"
}
```

**Output:** Graph traversal results with nodes and edges discovered.

**Integration test cases:**
- T1: Invalid start_node_id returns error
- T2: depth > 5 clamped to 5
- T3: Unknown edge_types in `edge_types` array filtered with warning
- T4: MAX_NODES=1000 limit respected
- T5: No infinite loops on cyclic graphs

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
| context_status | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| upsert_lesson | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| recall_relevant_lessons | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| get_anomalies | ✅ | ✅ | ✅ | ✅ | ✅ | ✅* |
| get_openclaw_prompt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

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
| Session | session_id | ✅ (content_embedding) | ❌ |
| MergeEvent | event_id | ❌ | ❌ |
| GistClass | name | ✅ (centroid) | ❌ |
| SchemaOrgType | name | ❌ | ❌ |
| LLMProvider | provider_id | ❌ | ❌ |
| Workspace | workspace_id | ❌ | ❌ |
