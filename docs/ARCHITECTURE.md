# Side Quests — Architecture Specification

> **Canonical architecture reference for all agents and contributors.**
> This is the single source of truth for the system design, schema, Loop steps, tools, and IP claims.
> Agent-specific workflow files (CLAUDE.md, GEMINI.md, etc.) reference this document — do not duplicate architecture content there.

## Required Companion References

- Tool catalog (keep in sync with tool schemas/handlers): [docs/tool-catalog.md](docs/tool-catalog.md)
- Backlog card authoring and execution rules: [backlog/BacklogRules.md](backlog/BacklogRules.md)
- Backlog planning/tracking status source: [backlog/masterBacklogTracker.md](backlog/masterBacklogTracker.md)

## Project Mission

**Side Quests — Phase 0: Standalone Brain Daemon** — Build a standalone local AI memory system backed by a Gated Consolidation Loop and a Graph-Native Kùzu database. The system exposes MCP STDIO adapters for Claude Code and Codex. OpenClaw integration is deferred to a later phase.

The core invention is the **Gated Consolidation Loop** — an active cognitive processing engine modeled on human biomimetic heuristics (Kahneman System 1/2, Representativeness, Availability) that transforms passive AI memory into a self-correcting, auditable knowledge graph structured around a Main Quest / Side Quest paradigm.

## Technology Stack

- **Language:** Python
- **Database:** Kùzu (`kuzu==0.11.3` — pin this exact version; kuzu-db was archived October 2025, last stable release. Watch **RyuGraph** fork for future migration path.) — embedded graph + vector store. `kuzu_client.py` is an abstraction layer to simplify migration if needed. Never spin up external DB servers. No Neo4j, Postgres, ChromaDB, Pinecone, or LanceDB.
- **NER / Zoning:** `spaCy` (local, zero LLM cost for concept extraction)
- **Embeddings:** `sentence-transformers` (local, lightweight)
- **Ontologies:** gist (Semantic Arts) for upper-level classification → schema.org sub-graphs for domain-specific attributes
- **LLM:** Configurable via `sidequests.toml` — Ollama (default/local) or cloud providers (OpenAI, Anthropic, Google) as opt-in
- **Memory Control Panel:** FastAPI web app bound strictly to `127.0.0.1` (no external access)
- **MCP Transport:** stdio only — no listening TCP/HTTP ports; Unix domain sockets for IPC between adapters and the Brain Daemon

## LLM Provider Configuration (`sidequests.toml`)

```toml
[llm]
provider = "ollama"           # ollama | openai | anthropic | google
model = "llama3.1:8b"
base_url = "http://localhost:11434"   # ollama only
# api_key loaded from env var for cloud providers

[embeddings]
model = "sentence-transformers/all-MiniLM-L6-v2"   # produces 384-dim vectors — matches FLOAT[384] schema
# WARNING: changing this model requires full re-embedding of all nodes in the graph.
# Run: sidequests reembed --confirm before switching models.

[ingestion]
max_ingest_chars = 4000   # passive ingestion only (conversational turns). Truncates at last sentence boundary.
# Long document ingestion uses the Open Brain pipeline (M6) which does proper semantic chunking.

[quest]
auto_complete_days = 30   # suggest Quest completion after N days of inactivity (0 = disabled)

[pruning]
# Decay rate applied per day of inactivity per node type.
# Values 0–1; lower = faster decay. Power user setting — defaults work for most users.
decay_rate.global_constraint  = 0.999   # half-strength in ~2 years
decay_rate.global_preference  = 0.999
decay_rate.decision           = 0.995   # half-strength in ~140 days
decay_rate.constraint         = 0.995
decay_rate.requirement        = 0.990   # half-strength in ~70 days
decay_rate.action_item        = 0.980   # half-strength in ~35 days
decay_rate.message            = 0.970   # half-strength in ~23 days
decay_rate.document_extract   = 0.970

# Archive when pathway_strength falls below this value
archive_threshold = 0.10

# Resurrect an archived node when a new message matches above this similarity
resurrection_threshold = 0.85   # same as System 1 confidence threshold

# Background sweep interval in seconds (handles pruning + confidence re-scoring)
sweep_interval_seconds = 300    # every 5 minutes
```

All LLM calls use an OpenAI-SDK-compatible interface so Ollama and cloud providers share the same code path (only `base_url` and `api_key` differ). Ollama is recommended for real-time Loop steps (Steps 2 + 6) due to latency. Cloud providers are acceptable for document ingestion (Open Brain) where latency is less critical.

## Security Constraints (Non-Negotiable)

- STDIO transport mandatory; no TCP/HTTP listening ports
- All file read/write strictly confined to the project directory — paths must be canonicalized via `realpath()`
- Block `..` escapes and symlink traversal; only allowlisted extensions (`.db`, `.log`) may be written
- Memory Control Panel web server binds to `127.0.0.1` only, never `0.0.0.0`

## IP Protection

**Keep this repository private until a provisional patent is filed.** These documents establish prior art dated March 2026, but public disclosure (GitHub, blog, conference talk, demo) before filing forfeits patent rights in most jurisdictions. Core IP claims requiring protection before any publication:
- Gated Consolidation Loop (9-step biomimetic pipeline)
- Shape-First Principle (ontological grounding before semantic work, applied at every pipeline level)
- Kahneman System 1/2 hybrid classifier (Step 2)
- Cocktail Party Effect selective attention gate (Step 4)
- gist → schema.org routing table (stored as graph edges, not code)
- **Context Window as Working Memory Model (IP Claim)** — modeling each LLM session as a tracked working memory buffer with load/unload semantics
- **Smart Deduplication via Load Tracking (IP Claim)** — demoting (not excluding) already-loaded graph nodes in retrieval results
- **Session Handoff Intelligence (IP Claim)** — proactive knowledge transfer between context windows using load history from prior sessions
- **Bloat Detection via Token Estimation (IP Claim)** — monitoring context window utilization and surfacing efficiency warnings
- Hebbian promotion to Long-Term Potentiation (CO_OCCURS_WITH → named edge)
- **Valence-Weighted Graph Retrieval (IP Claim)** — retrieval ranking incorporates historical outcome signals from Plan nodes, not just frequency and recency
- **Amygdala Reflex at Plan Registration (IP Claim)** — preemptive warning system that fires before execution, not after failure
- **Graph-Native Behavioral Reinforcement (IP Claim)** — outcome learning without a separate RL training loop; valence propagates through existing graph edges

## Architecture

### Deployment Model

```
Brain Daemon (Python, standalone)
  ├── Kùzu embedded DB (graph + vector)
  ├── Gated Consolidation Loop (9 steps: 1, 1b, 2, 3, 3b, 4, 5, 6, 7)
  ├── Unix domain socket IPC server
  └── Memory Control Panel (FastAPI, 127.0.0.1 only)

Per-Assistant Adapters (two-part: hook config + MCP server)
  ├── adapters/claude_code/adapter.py       # Phase 0 — hook config + MCP server
  ├── adapters/claude_desktop/adapter.py   # M8
  ├── adapters/codex/adapter.py            # M8
  ├── adapters/chatgpt_desktop/adapter.py  # M8
  └── adapters/gemini_cli/adapter.py       # M8

Passive ingestion per adapter type:

  Claude Code (Phase 0):
    User turns   → UserPromptSubmit hook (shell script → Brain socket, zero LLM involvement)
    Asst turns   → notify_turn MCP tool call (LLM as courier, Brain decides what to remember)

  All M8 adapters (Claude Desktop, ChatGPT Desktop, Codex, Gemini CLI):
    User turns   → notify_turn MCP tool call  (hooks unavailable for GUI/other CLIs)
    Asst turns   → notify_turn MCP tool call

  Never forwarded: tool call results, adapter-injected system messages.
  All ingestion is fire-and-forget — zero added latency to the LLM session.
```

**MainQuest ID** is generated deterministically as a hash of `repo_root_path + git_branch` so all local assistants auto-align to the same project context.

### Kùzu Implementation Notes

- **Pinned version:** `kuzu==0.11.3` — archived project, do not upgrade without testing against RyuGraph migration path
- **Portability:** All Kùzu-specific syntax (DDL, projected graphs, `QUERY_VECTOR_INDEX`, `kuzu.Database`) lives exclusively in `kuzu_client.py`. Loop steps, tools, and the daemon never import `kuzu` directly. Migration to Neo4j or another provider = rewrite `kuzu_client.py` only. The data model (nodes, relationships, properties) is standard property graph — fully portable.
- **Concurrency model:** Brain Daemon holds the sole `READ_WRITE` connection; a single `asyncio.Lock` wraps all write operations. MCP adapters open Kùzu with `read_only=True` for any direct reads — no write contention possible.
- **Embedding type:** HNSW vector indexes require a fixed-dimension type — declare as `FLOAT[384]` (not `FLOAT[]`). One HNSW index created per node table at M1 schema init.
- **Filtered vector search:** Use projected graphs to prefilter before HNSW search (not postfilter): `CALL project_graph('active_decisions', 'Decision', {'Decision': 'n.archived = false AND n.confidence_low = false'})` — restricts the index scan to active nodes only.
- **Multi-table search:** No unified cross-table HNSW index exists. `current_truth` uses `UNION ALL` across per-table index calls in a single Cypher query, then sorts by score and applies `LIMIT`.
- **Relationship table typing:** Named semantic relationships defined as `FROM Concept TO Concept` only. `REIFIED_AS` uses Kùzu's multi-FROM/TO syntax: `CREATE REL TABLE REIFIED_AS (FROM Concept TO Decision, FROM Concept TO Constraint, FROM Concept TO Requirement, FROM Concept TO ActionItem)`.

### Module Structure

```
sidequests-brain/
├── sidequests.toml
├── brain_daemon.py
├── mcp_engine/
│   ├── schema.py                # Kùzu schema init
│   ├── hippocampus.py           # Semantic Quest Routing (B17)
│   ├── working_memory.py        # Context Window Awareness (B18)
│   ├── loop/
│   │   ├── step1_ner.py         # spaCy NER / Zoning
│   │   ├── step1b_relations.py  # Relation extraction: universal verb patterns (syntax-level, no LLM)
│   │   ├── step2_gist.py        # gist hybrid classifier (System 1/2)
│   │   ├── step3_schema_org.py  # schema.org sub-graph routing + mapping table
│   │   ├── step3b_relations.py  # Relation extraction: Ollama with gist+schema.org type context
│   │   ├── step4_pattern.py     # Representativeness heuristic + confidence gating
│   │   ├── step5_retrieval.py   # Dual-scope retrieval (Availability heuristic)
│   │   ├── step6_arbitration.py # Constrained contradiction arbitration
│   │   ├── step7_pathway.py     # Pathway update + DEPRECATED_BY + MergeEvent
│   │   ├── step7_5_lesson.py    # Lesson extraction (post-pathway)
│   │   └── anomaly_detection.py # Out-of-Band Behavioral Integrity Monitoring (B12)
│   ├── llm/
│   │   ├── provider.py          # OpenAI-SDK-compatible abstraction
│   │   └── providers/           # ollama.py, openai.py, anthropic.py, google.py
│   ├── graph/
│   │   ├── kuzu_client.py       # Kùzu connection + Cypher execution
│   │   └── embeddings.py        # sentence-transformers wrapper
│   └── tools/
│       ├── __init__.py          # MCP tools: notify_turn, current_truth, etc.
│       └── explore_graph.py     # Directed multi-hop graph traversal
├── adapters/
│   ├── claude_code/adapter.py        # Phase 0
│   ├── claude_desktop/adapter.py     # M8
│   ├── codex/adapter.py              # M8
│   ├── chatgpt_desktop/adapter.py    # M8
│   └── gemini_cli/adapter.py         # M8
├── web/
│   ├── server.py                # FastAPI, 127.0.0.1 only
│   └── static/                  # Graph UI, soft-lock UI, merge rollback
├── benchmarks/
│   └── arc3/                    # ARC-AGI-3 A/B harness
│       ├── harness.py           # Baseline vs SideQuests-augmented runner
│       ├── adapter.py           # Episode normalization bridge
│       └── state_serializer.py  # State-to-text serialization
└── tests/
```

## Gated Consolidation Loop (9 Steps — Write Flow)

**Step 1 — Zoning / NER:** spaCy extracts raw concepts (people, objects, places, actions, quantities). Zero LLM cost.

**Step 1b — Relation Extraction: Fast Path (Universal Verb Patterns):**
Extracts syntactic relations using universal verb pattern matching. Runs on every message — zero LLM cost, no extra dependencies.

spaCy dep parser identifies nsubj→verb→dobj triples. The verb lemma is matched against a universal pattern dict — only verbs where syntax alone is sufficient signal, regardless of domain:

| Verb lemmas | → Named Type |
|-------------|-------------|
| require / need / depend / necessitate | `REQUIRES` |
| enable / allow / support / facilitate / permit | `ENABLES` |
| replace / supersede / deprecate / override | `REPLACES` |
| contradict / conflict / violate / negate / undermine | `CONTRADICTS` |
| contain / include (+ "is part of" dep pattern) | `PART_OF` |

Domain-agnostic: works equally for software, writing, research, business, personal projects. These verbs mean the same thing in any domain.

Types that require entity type context (CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO) are deferred to Step 3b, which has full gist + schema.org context. Edges confirmed here are written to Kùzu immediately.

**Step 2 — gist Rapid Classification (Kahneman System 1 / System 2):**
Maps each concept to a gist ontological class using a hybrid dual-process approach:
- System 1 (fast): Embedding cosine similarity vs. pre-labeled gist class centroids. If similarity > 0.85 → accept instantly.
- System 2 (deliberate): If 0.60–0.85 → escalate to local LLM call for disambiguation.
- Early exit: If < 0.60 → noise, vector-log only, no further processing.
- Messages resolved by System 2 are saved as labeled examples → centroids improve over time.

**Step 3 — schema.org Sub-graph Routing:** gist class routes to the relevant schema.org property subset only (not the full vocabulary). This gives the precise semantic "shape" for the next step. Routing table is core IP — stored as graph edges `(GistClass)-[ROUTES_TO]->(SchemaOrgType)`, seeded at M1 schema init.

| gist Class | schema.org Type | Properties Injected as Step 3 Context |
|------------|----------------|---------------------------------------|
| `gist:Restriction` | `schema:Demand` | `eligibleCustomerType`, `availability`, `validFrom`, `validThrough`, `businessFunction`, `description` |
| `gist:PlannedEvent` | `schema:Action` | `agent`, `object`, `target`, `actionStatus`, `startTime`, `endTime`, `result`, `instrument` |
| `gist:PhysicalThing` | `schema:Product` | `name`, `identifier`, `description`, `version`, `inLanguage`, `isAccessoryOrSparePartFor` |
| `gist:Magnitude` | `schema:QuantitativeValue` | `value`, `unitCode`, `unitText`, `minValue`, `maxValue`, `valueReference` |
| `gist:Category` | `schema:DefinedTerm` | `name`, `description`, `termCode`, `inDefinedTermSet`, `sameAs` |
| `gist:Agent` (person) | `schema:Person` | `name`, `jobTitle`, `description`, `email`, `knowsAbout` |
| `gist:Agent` (org/system) | `schema:Organization` | `name`, `description`, `member`, `parentOrganization`, `contactPoint` |
| `gist:Event` | `schema:Event` | `name`, `startDate`, `endDate`, `eventStatus`, `location`, `organizer`, `description` |

**Agent disambiguation:** `gist:Agent` routes to two `SchemaOrgType` nodes. The spaCy entity label from Step 1 determines which: `PERSON` → `schema:Person`, `ORG` → `schema:Organization`. No extra LLM cost — uses Step 1 output already available.

**Step 3b — Relation Extraction: Semantic Path (Ollama with Type Context):**
Runs AFTER Step 3 — so it has full ontological context for each entity. The **Shape-First Principle (Named IP Claim)** governs the entire pipeline: *classify the ontological type before doing semantic work at any level.* Applied twice: (1) gist→schema.org routing (Steps 2→3) before pattern matching (Step 4); (2) type context injected into relation extraction (Step 3b) before Ollama reasons about the relationship. Knowing the shape narrows the semantic search space at every level.

The Ollama prompt includes each entity with its gist class and schema.org type:
> "Entity A: Kùzu (gist:PhysicalThing / schema:Product). Entity B: ChromaDB (gist:PhysicalThing / schema:Product). Sentence: 'We chose Kùzu over ChromaDB.' What is the relationship?"

Forced output schema: `{ head, relation_type, tail, confidence }` — must choose from the 9 named types or return null (never forced).

Triggered when: >1 entity in the message AND Step 1b found no relation.

Handles all types Step 1b cannot extract from syntax alone:

| Type | Why Ollama needed |
|------|------------------|
| `CHOSEN_OVER` | Requires understanding decision context |
| `IMPLEMENTS` | Requires type context (what kind of thing implements what) |
| `EXTENDS` | Domain-dependent — "builds on" means different things per domain |
| `ALTERNATIVE_TO` | Requires situational context (option vs. decision) |

Also refines any Step 1b edge that has low confidence from ambiguous syntax. Results written to Kùzu alongside CO_OCCURS_WITH edges.

**Step 4 — Heuristic Pattern Matching + Selective Attention (Representativeness Heuristic + Cocktail Party Effect):** With ontological context known, classify into artifact type. The confidence gate IS the selective attention filter — most conversation noise passes through unrecorded; only meaningful signal fires:
- < 60% → noise, vector-log only, no structural node created (filtered out — cocktail party background)
- 60–90% → store with `confidence_low` flag, low `pathway_strength`, eligible for re-scoring (low attention)
- > 90% → store with full confidence, proceed to Steps 5–7 (full attention fired)

**Cocktail Party Effect (Named Biomimetic Principle — IP Claim):** The Brain is always listening passively (adapter forwards all user + assistant turns). The Loop's Step 4 confidence gate is the selective attention mechanism — like hearing your name cut through background noise at a party. Most conversation is background; specific patterns (decision language, constraint language, entity mentions, contradictions to existing knowledge) cause the Brain's "senses" to fire.

| Sense | Fires On |
|-------|---------|
| Decision sense | "we decided", "we chose", "we agreed", past-tense resolution language |
| Constraint sense | "never", "must", "always", "required", "forbidden", directive language |
| Plan sense | "we will", "next step", "plan to", future-tense action language |
| Entity sense | Known graph entity mentioned by name or near-match embedding |
| Contradiction sense | Step 5 retrieval finds 0.75–0.92 similarity to existing confirmed node |
| Anomaly / Security sense | Content contradicts a high-confidence GlobalConstraint (pathway_strength > 0.8) — flags potential prompt injection or goal hijacking |
| Success sense (B69) | "perfect", "great job", "approved", "all tests pass" — Dopamine signal |
| Failure sense (B69) | "that's wrong", "revert", "that broke", "start over" — Pain signal |

No human confirmation required. Uncertain nodes enter as tentative knowledge, re-scored continuously.

**Step 5 — Dual-Scope Retrieval (Availability Heuristic):** Check branch scope (same MainQuest + vector similarity) then global scope (GlobalConstraint/GlobalPreference nodes) for existing matches.

**Step 6 — Constrained Contradiction Arbitration:** Only runs in gray zone (0.75–0.92 similarity) or same artifact type match. LLM forced to `{classification, rationale_tokens, referenced_nodes}`. "Uncertain" → soft-lock.

**Step 7 — Pathway Update:**
- Additive: increment `pathway_strength` on access: `strength += 1 * log(1 + 1/days_since_last_access)`. No duplicate node created.
- Contradiction: create new node + `[DEPRECATED_BY]` edge from old to new. Old node preserved in audit trail, filtered from `current_truth`.
- After pathway update: trigger **event-driven confidence re-scoring** on nearby `confidence_low` nodes (within 1–2 hops).
- **CO_OCCURS_WITH write:** After Step 7 completes, write (or increment) `CO_OCCURS_WITH` edges between all concept pairs from the same message that cleared the noise floor (>60% confidence). Edge `strength` initialized to `min(confidence_A, confidence_B)` — capped at the weaker node. Background sweep updates `strength` as endpoint confidences change over time.

## Biomimetic Learning Principles

### Synaptic Pruning (Named Biomimetic Principle)

Modeled on neuroscience synaptic pruning ("use it or lose it") and the **Ebbinghaus Forgetting Curve** (memories decay exponentially unless actively recalled). Two complementary forces govern every artifact node:

| Force | Trigger | Formula |
|-------|---------|---------|
| Strengthening | On access (Step 7) | `strength += 1 * log(1 + 1/days_since_last_access)` |
| Decay | Background sweep | `strength *= decay_rate ^ days_since_last_access` |

`decay_rate` is configurable per node type in `sidequests.toml` (power user setting — sensible defaults provided). GlobalConstraints decay over years; raw Messages decay in weeks.

**Archive mechanic (never delete):**
- Node falls below `archive_threshold` (default 0.10) → `archived: true` flag set
- Archived nodes excluded from `current_truth` and active re-scoring
- Edges preserved but soft-archived alongside their weakest endpoint
- Audit trail fully preserved — visible in Memory Control Panel as history

**Resurrection:**
- Background sweep compares all archived nodes against all current **active** (non-archived) nodes in the graph
- If embedding similarity > `resurrection_threshold` (default 0.85 — same as System 1) → un-archived, strength reset to `resurrection_threshold` (not 1.0 — it was dormant, earns full strength back through access)
- Active nodes are higher-quality signal than raw messages — already confirmed, already embedded
- No time window parameter needed — the live graph IS the context
- Frequency controlled by existing `sweep_interval_seconds` — no separate resurrection interval in Phase 0

### Hebbian Learning — "Neurons That Fire Together Wire Together" (Named Biomimetic Principle)

Two distinct Hebbian mechanisms, both named IP claims:

*"Fire together"* — concepts that co-occur in the same message get a `CO_OCCURS_WITH` edge. The `count` increments on every co-occurrence. This is the **implicit signal layer** — always preserved, never deleted.

*"Wire together"* — when a concept recurs, `pathway_strength` increases (Step 7). When a new phrasing of a concept is encountered, a new `altLabel` node is wired to it. Both accumulate through use.

**CO_OCCURS_WITH → Named Relationship Promotion (Hebbian → Long-Term Potentiation)**

When an implicit `CO_OCCURS_WITH` edge is ready to be promoted to a named semantic relationship, a new named edge is created **alongside** the existing `CO_OCCURS_WITH` edge. Both exist permanently — the implicit layer is Hebbian evidence; the named layer is the explicit semantic conclusion.

Three promotion triggers in order of confidence:

1. **Loop extracts it explicitly** from a message — Step 1b (verb pattern match) or Step 3b (Ollama with type context). Named edge created with `inferred_by: "system"` (verb pattern) or `inferred_by: "LLM"` (Step 3b), high confidence (0.85+). Most reliable — grounded in what was actually said.

2. **LLM auto-promotes** when `co_occurrence_count` crosses a threshold (configurable, default 10). Step 6 arbitration asks the LLM to name the relationship. Named edge created with `inferred_by: "LLM"`, medium confidence (0.70–0.85). The `CO_OCCURS_WITH` count is the evidence presented to the LLM.

3. **User promotes via Memory Control Panel**. User sees a strong `CO_OCCURS_WITH` edge and explicitly names it. Named edge created with `inferred_by: "user"`, confidence 1.0 (trusted). User can also edit or demote existing named edges here.

### SKOS Label Accumulation (Hebbian "Wire Together" at Label Level)

Each time a concept is expressed a new way (paraphrase, synonym, abbreviation), a new `altLabel` node is wired to the concept — its own text and its own embedding. `current_truth` searches both concept embeddings and all label embeddings, so a concept becomes findable via any phrasing ever associated with it.

Labels also decay (Synaptic Pruning applies) — an `altLabel` never matched in retrieval weakens over time and can be archived.

### Valence & Outcome Learning — Pain/Pleasure Reflex (B66–B69)

The third learning axis alongside frequency (Hebbian) and time (Ebbinghaus). Agents learn from consequences via outcome-weighted Plans. See "Active Agent System" section below.

### Confidence Re-Scoring (Living Property)

`confidence` is a dynamic field on every artifact node — not set once at Step 4 but continuously updated as graph context changes. A node stored at 72% can rise to 91% (auto-promote) or fall below 60% (auto-archive) without any human action.

Two re-scoring triggers:
- **Event-driven (Step 7):** After every pathway update, re-score all `confidence_low` nodes within 1–2 hops. Fast, reactive, runs inside the Loop.
- **Background sweep (Brain Daemon idle task, every `sweep_interval_seconds`):** Single pass that handles three jobs:
  1. Re-score all `confidence_low` nodes against current graph state
  2. Apply time-decay to `pathway_strength` for all nodes (`strength *= decay_rate ^ days_since_last_access`)
  3. Archive nodes below `archive_threshold`; check archived nodes for resurrection against recent messages

Re-scoring factors:
- Relationship density (more connected = higher confidence)
- Pathway strength of neighboring nodes
- Embedding similarity to recently confirmed high-confidence nodes
- Recency of supporting messages

`current_truth` ranks results by `pathway_strength × confidence` — low-confidence nodes surface but rank lower naturally.

## Read Flow — Graph-Native RAG

1. Embed user prompt
2. Vector search Kùzu for similar nodes
3. Graph traversal (1–2 hops) from retrieved nodes
4. Rank results by `pathway_strength × confidence × (1 + outcome_boost)`
5. Inject structured context into assistant system prompt

`outcome_boost` (B69): ±0.3 max from valence history on related Plans. Zero for entities without Plan involvement.

## Active Agent System — Plan/Evaluate Loop (B66–B69)

Modern agentic workflows involve agents formulating multi-step plans before execution. The passive system (`notify_turn`) captures *what happened*; the active system captures *what was intended, what was tried, and whether it worked*.

### The Cognitive Loop

| Phase | Human Analog | SideQuests Implementation |
|-------|-------------|--------------------------|
| **Perceive** | Senses take in environment | `current_truth` + `explore_graph` |
| **Model** | Build mental model | Agent traverses graph, understands entity relationships |
| **Plan** | Formulate steps A→B | Agent calls `register_plan` |
| **Act** | Execute the plan | Agent calls external tools |
| **Evaluate** | Pain/Pleasure feedback | Agent calls `report_outcome` |

### Plan & PlanStep Nodes (B66)

**`Plan`** — agent's declared multi-step strategy:
- `plan_id`, `goal TEXT`, `strategy TEXT`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`
- `step_count INT64`, `valence DOUBLE` (-1.0 to +1.0, NULL until evaluated)
- `valence_source STRING` ("user_feedback" | "exit_code" | "test_result" | "system")
- `status STRING` ("active" | "completed" | "abandoned")
- `confidence`, `confidence_low`, `pathway_strength`, `archived`, `created_at`, `completed_at`

**`PlanStep`** — individual step within a plan:
- `step_id`, `step_number INT64`, `description TEXT`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`
- `expected_outcome TEXT`, `actual_outcome TEXT` (filled on completion)
- `valence DOUBLE` (-1.0 to +1.0, per-step outcome), `status STRING` ("pending" | "in_progress" | "succeeded" | "failed" | "skipped")
- `created_at`, `completed_at`

### Plan Relationships

```
(Plan)-[PLANNED_IN]->(Session)              # provenance
(Plan)-[TARGETS]->(MainQuest | SideQuest)   # quest linkage
(PlanStep)-[STEP_OF]->(Plan)                # membership
(PlanStep)-[NEXT_STEP]->(PlanStep)          # intentional causal ordering
(PlanStep)-[ACTS_ON]->(Concept)             # entity linkage
(Plan)-[PRODUCED_LESSON]->(Lesson)          # outcome learning
(PlanStep)-[OUTCOME_SIGNAL]->(Concept)      # valence propagation
```

`[NEXT_STEP]` captures declared causal dependency (step 3 depends on step 2's output). This is agent reasoning, not timestamp ordering. Bounded at 3-10 steps per plan — no supernode risk.

### Active Tools (B67)

- **`register_plan`** — Agent declares a multi-step strategy. Brain creates Plan + PlanStep chain, runs similarity search against past plans. Returns warnings (similar plans that failed) and suggestions (similar plans that succeeded). **This is the Amygdala Reflex — triggered at plan registration, before execution.**
- **`report_outcome`** — Agent reports step-level or plan-level results with valence. Auto-extracts Lesson when |valence| > 0.7. Propagates negative valence to `[ACTS_ON]` Concept nodes.
- **`recall_plans`** — Agent asks "what strategies worked for a similar goal?" Retrieval ranked by `similarity × |valence| × pathway_strength`.

### Passive Plan Detection (B68)

Three-layer fallback when agents don't actively declare plans:
1. **Step 4 Plan sense** — structural pattern detector for numbered/bulleted ordered sequences (3+ items)
2. **Retrospective inference** — background sweep spots consecutive PlannedEvent messages and infers plan structure
3. **Dedup guard** — passive plans never duplicate actively declared plans (embedding similarity > 0.90 check)

## Kùzu Graph Schema

The graph is a first-class citizen. Any entity with identity, relationships, or query value is a node — not a property on another node.

**Concept Node** — general-purpose entity extracted by Step 1 NER. All named relationships (`REQUIRES`, `ENABLES`, etc.) connect `Concept` nodes. Tools, people, products, events, quantities referenced in relationships land here and stay here. `pathway_strength` initialized to `max(confidence, 0.50)` at creation — strong nodes start strong, `confidence_low` nodes start at their confidence value and earn strength through access.

- `Concept` (`concept_id`, `text_raw`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `gist_class STRING`, `schema_org_type STRING`, `confidence FLOAT`, `confidence_low BOOLEAN`, `pathway_strength FLOAT`, `archived BOOLEAN`, `created_at TIMESTAMP`)

When Step 4 classifies a Concept at >90% confidence as a specific artifact type, a specific artifact node (Decision, Constraint, etc.) is created. The Concept is linked via `(Concept)-[REIFIED_AS]->(Decision | Constraint | ...)`. Named relationships between Concepts are preserved — the artifact node is an annotation on the concept, not a replacement.

**Core Artifact Nodes** (require `text_raw`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `confidence FLOAT`, `confidence_low BOOLEAN`):
- `MainQuest` (`status STRING` — active|completed|archived, `completed_at TIMESTAMP`, `purpose STRING` — inferred by Loop, editable), `SideQuest` (same status fields + `purpose STRING`), `Decision`, `Constraint`, `Requirement`, `ActionItem`
- `GlobalConstraint`, `GlobalPreference` (workspace-level, cross-quest deduplication)
- `Document` (`document_id`, `location_uri`, `content_hash`, `last_modified_at`, `mime_type`)
- `Message` / `DocumentExtract` (`byte_start`, `byte_end` or line ranges for provenance)
- `Lesson` (`lesson_id`, `text_raw`, `embedding`, `domain`, `lesson_type`, `confidence`, `confidence_low`, `pathway_strength`, `archived`, `created_at`)
- `Plan`, `PlanStep` — see Active Agent System section above

**Session & Infrastructure Nodes** (no embedding required):
- `Session` (`session_id`, `started_at`, `last_active_at`, `onboarded BOOLEAN`, `purpose STRING`, `routing_state STRING`, `routing_confidence FLOAT`, `routing_method STRING`, `token_estimate INT64`, `token_limit INT64`, `loaded_node_count INT32`, `last_injection_at TIMESTAMP`)

**Relationship Nodes:**
- `LOADED` (`injected_at TIMESTAMP`, `token_estimate INT32`, `source STRING`, `load_hits INT32`) — links `Session` to any artifact currently in its context window.
- `REROUTED_FROM` (`rerouted_at TIMESTAMP`, `reason STRING`) — links `Session` to its prior `MainQuest` after a re-routing event.

**LLMProvider Node:**
- `LLMProvider` (`provider_id`, `provider_name`, `model_name`, `is_local BOOLEAN`, `context_window INT64`)

**Ontology Nodes** (the gist → schema.org routing table lives in the graph, not in code):
- `GistClass` (`name` — e.g., Restriction, PlannedEvent, PhysicalThing, Magnitude, Category, Agent, Event; `centroid FLOAT[384]` — mean embedding of all seed + System 2 resolved examples for this class, computed at M1 init and updated on each System 2 resolution)
- `SchemaOrgType` (`name`, `properties STRING[]` — the relevant property subset for this type)

**Label Nodes** (SKOS-inspired — graph-native, each carries its own embedding):
- `Label` (`label_id`, `text`, `embedding FLOAT[384]`, `language STRING` default "en", `label_type STRING` — preferred|alternative|hidden, `confidence FLOAT`, `source STRING` — user|system|LLM, `created_at TIMESTAMP`)
- `prefLabel` — canonical name, one per language per concept
- `altLabel` — synonyms, paraphrases, abbreviations — accumulate through use (Hebbian "wire together")
- `hiddenLabel` — search-only terms not shown in UI (misspellings, deprecated names)
- Every Label carries its own embedding → `current_truth` searches concept embeddings AND all label embeddings

**Audit Nodes** (embeddings optional): `MergeEvent` (`pre_pathway_strength`, `delta_pathway_strength`, `alias_added[]`, `metadata_patch`)

### Relationships (Complete)

```
# Quest structure
(SideQuest)-[BELONGS_TO]->(MainQuest)
(MainQuest)-[ANCHORED_TO]->(Workspace)

# Document provenance
(DocumentExtract)-[DERIVED_FROM]->(Document)
(Message | DocumentExtract)-[ESTABLISHED]->(Decision | Constraint)

# Audit trail
(Decision)-[DEPRECATED_BY]->(Decision)
(Message)-[TRIGGERED]->(MergeEvent)
(MergeEvent)-[UPDATES_PATHWAY]->(Concept)

# Session provenance
(Session)-[USED]->(LLMProvider)
(Session)-[IN_WORKSPACE]->(Workspace)
(Session)-[WORKING_ON]->(MainQuest | SideQuest)
(Message)-[SENT_IN]->(Session)
(Decision | Constraint)-[ESTABLISHED_IN]->(Session)

# Ontology routing (graph-native routing table — core IP)
(GistClass)-[ROUTES_TO]->(SchemaOrgType)

# SKOS-inspired labels (graph-native, each with own embedding)
(ArtifactNode)-[HAS_PREF_LABEL]->(Label)    # one per language
(ArtifactNode)-[HAS_ALT_LABEL]->(Label)     # many, accumulate through use
(ArtifactNode)-[HAS_HIDDEN_LABEL]->(Label)  # search only, never displayed

# Concept promotion (when Step 4 classifies at >90%)
(Concept)-[REIFIED_AS]->(Decision | Constraint | Requirement | ActionItem)

# Hebbian implicit relationship layer (always preserved)
(Concept)-[CO_OCCURS_WITH {count INT, strength FLOAT}]->(Concept)

# Named semantic relationship layer (Concept→Concept; preserved through reification)
# inferred_by: "system" (Step 1b verb pattern) | "LLM" (Step 3b Ollama) | "user"
# Step 1b fast-path types:
(Concept)-[REQUIRES    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[ENABLES     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[REPLACES    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[CONTRADICTS {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[PART_OF     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
# Step 3b semantic-path types (require gist+schema.org type context):
(Concept)-[CHOSEN_OVER    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[IMPLEMENTS     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[EXTENDS        {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[ALTERNATIVE_TO {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)

# Working memory
(Session)-[LOADED {injected_at, token_estimate, source, load_hits}]->(ArtifactNode)
(Session)-[REROUTED_FROM {rerouted_at, reason}]->(MainQuest)

# Anomaly detection (B12)
(ArtifactNode)-[ANOMALY_DETECTED {type, confidence, detected_at}]->(GlobalConstraint | GlobalPreference)

# Lesson integration (B11)
(MainQuest)-[PRODUCED_LESSON]->(Lesson)
(Session)-[LEARNED]->(Lesson)
(Lesson)-[APPLIES_TO]->(Concept | Decision | Requirement)
(Lesson)-[RELATED_TO]->(Lesson)
(Message)-[CONTAINS_LESSON]->(Lesson)

# Active Agent System — Plans (B66–B69)
(Plan)-[PLANNED_IN]->(Session)
(Plan)-[TARGETS]->(MainQuest | SideQuest)
(PlanStep)-[STEP_OF]->(Plan)
(PlanStep)-[NEXT_STEP]->(PlanStep)
(PlanStep)-[ACTS_ON]->(Concept)
(Plan)-[PRODUCED_LESSON]->(Lesson)
(PlanStep)-[OUTCOME_SIGNAL {valence, plan_id, observed_at}]->(Concept)
```

## IPC Protocol (Adapter ↔ Brain Daemon)

**Protocol:** JSON-RPC 2.0 over Unix domain socket — the same wire format MCP itself uses. Adapters are transparent proxies: read JSON-RPC from LLM stdio, forward to Brain Daemon socket, return response. Zero translation layer.

**Implementation:** Python `asyncio` + built-in `json`. No external JSON-RPC library — minimal dependencies, maximum speed and control.

```
LLM → [stdio, JSON-RPC 2.0] → Adapter → [Unix socket, JSON-RPC 2.0] → Brain Daemon → Kùzu
```

## MCP Tool Surface

### Passive Ingestion Tools

**`notify_turn`** — called automatically by LLM after every turn (M2)
```json
{
  "name": "notify_turn",
  "description": "Forward this turn to the Brain for background processing. Call after every response — do not skip.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "role":       { "type": "string", "enum": ["user", "assistant"] },
      "content":    { "type": "string" },
      "session_id": { "type": "string" }
    },
    "required": ["role", "content", "session_id"]
  }
}
```
Response: `{ "status": "queued" }` — always immediate, never blocks.

### Retrieval Tools

**`current_truth`** — call before answering architecture or past-decision questions
```json
{
  "name": "current_truth",
  "inputSchema": {
    "properties": {
      "query":      { "type": "string" },
      "session_id": { "type": "string" },
      "scope":      { "type": "string", "enum": ["branch", "global", "both"], "default": "branch" },
      "limit":      { "type": "integer", "default": 10 }
    },
    "required": ["query", "session_id"]
  }
}
```

**`explore_graph`** — directed multi-hop traversal (B10)

**`recall_relevant_lessons`** — cross-quest analogical recall (B11)

**`recall_plans`** — retrieve past strategies by goal similarity (B67)

**`analogical_search`** — cross-quest search (M8)

### Quest Management Tools

**`branch_quest`** — create SideQuest (M5)

**`complete_quest`** — mark Quest finished (M5)

**`set_quest`** — explicit quest override

**`diff_since`** — delta retrieval since prior session (M5)

**`get_open_loops`** — retrieve `confidence_low` nodes (M5)

### Active Agent Tools (B67)

**`register_plan`** — declare multi-step strategy

**`report_outcome`** — report step/plan results with valence

### Lesson Tools (B11)

**`upsert_lesson`** — explicitly add or update a domain-specific lesson

**`recall_relevant_lessons`** — cross-quest analogical recall

### Monitoring Tools

**`context_status`** — token accounting (B18)

**`get_anomalies`** — security monitoring (B12)

**`ingest_document`** — Open Brain pipeline (M6)

**`get_openclaw_prompt`** — retrieve OpenClaw plugin prompt (B21)

## LLM Adapter Instruction Model

Two-layer instruction model. Every active-mode adapter injects both layers.

**Layer 1 — Always-On System Prompt Fragment** (~28 tokens, injected every session):

```
[SideQuest | Quest: {quest_name} | Branch: {branch}]
The Brain is capturing decisions and constraints automatically.
Before answering about past choices or architecture → current_truth
Exploring a tangent? → offer branch_quest
```

**Layer 2 — Onboarding Skill** (injected once per LLM + Quest combination):

```
SideQuest's Brain is always listening — it automatically captures decisions,
constraints, and plans from your conversation through selective attention.
You don't need to flag things manually.

One automatic duty:
- notify_turn: call after EVERY response, passing role="assistant" and
  your full response text. This is how the Brain sees your output.
  Never skip it. Response is always instant — it never blocks you.

Two things you control:
- current_truth: call before answering any architecture or past-decision
  question. The Brain's graph is more reliable than your context window
  for resolved choices.
- branch_quest: offer (don't call unilaterally) when the conversation
  shifts to a distinct tangent worth tracking separately.

Active planning tools (when executing multi-step work):
- register_plan: call when you formulate a multi-step approach.
  The Brain tracks your strategy and warns if a similar plan failed before.
- report_outcome: call after key steps or when your plan completes.
  Valence: -1.0 (total failure) to +1.0 (perfect success).
- recall_plans: call before planning to learn from past strategies.

If current_truth returns a confidence_low result, flag the uncertainty
to the user — don't present tentative memory as confirmed fact.
```

Tracked via `Session.onboarded BOOLEAN` on the `Session` node. First session for a given LLM+Quest pair → full onboarding prompt injected, `onboarded` set to `true`. All subsequent sessions → Layer 1 fragment only.

## Error / Degraded Mode

**Scenario A — Brain Daemon unreachable** (socket missing — crashed or never started):
- Adapter detects connection failure at startup
- Modifies injected fragment to: `[SideQuest OFFLINE — memory unavailable]`
- Returns graceful MCP error on `current_truth` calls (LLM session continues without memory)
- Queues failed passive ingestion messages to a local flat file; replays when daemon reconnects

**Scenario B — Ollama unreachable** (daemon up, LLM steps fail):
- Step 2 System 1 (embedding similarity) still runs — only LLM-dependent sub-steps degrade
- Step 2 System 2 unavailable → store concept as `confidence_low=true`, skip LLM call; background sweep retries when Ollama is back
- Step 6 arbitration unavailable → store both gray-zone candidates as `confidence_low=true`; background sweep arbitrates later
- No data loss in either failure mode

## Installation Story

```bash
pip install sidequests-brain        # or: pip install -e . from repo
sidequests setup                    # Claude Code (auto-detected)
sidequests setup --target claude-desktop
sidequests setup --target chatgpt-desktop
sidequests setup --target gemini-cli
sidequests setup --target codex
```

`sidequests setup` per target:
1. Detects Ollama or prompts for cloud provider + API key
2. Writes `sidequests.toml` (project root) or `~/.sidequests/config.toml` (global)
3. Registers MCP adapter in the standard config file for each target
4. Starts Brain Daemon + runs smoke test (Ollama ping + Kùzu schema init + `tools/list` round-trip)

## Quest Lifecycle (Phase 0)

- **MainQuest:** Auto-created from a deterministic hash of `git repo root path + current branch`. No user action required for dev projects.
- **SideQuest:** Manually declared by the user via the `branch_quest` MCP tool when they know they're exploring a tangent.
- **Completion:** `complete_quest` tool sets `status = "completed"` + `completed_at` timestamp. Completed quests are excluded from `current_truth` branch-scope results but are the primary source for M8 cross-quest analogical reasoning. Auto-suggest after `auto_complete_days` of inactivity (configurable, default 30).
- **Future goal:** Auto-detect SideQuest branching via topic divergence from MainQuest embedding.

**Purpose / Intent Capture:**
- Trigger: first confirmed (>90% confidence) artifact stored by the Loop in a new Quest or Session
- Ollama synthesizes a 1–2 sentence purpose from the early messages + first confirmed artifact
- Stored on `Session.purpose` (session scope — set once, not updated mid-session) and `MainQuest.purpose` / `SideQuest.purpose` (quest scope — set from first session)
- Initial confidence: `confidence_low=true` — inferred, not confirmed. Quest proceeds with or without user confirmation.

## Build Milestones

| Milestone | Description |
|-----------|-------------|
| M1 | Kùzu schema + `sidequests.toml` config + IPC daemon skeleton + LLM provider abstraction. Phase 0 = English only. **Centroid bootstrap:** embed all 105 `GistSeedExamples.md` sentences, mean-pool per class, store as `GistClass.centroid FLOAT[384]`. spaCy model: `en_core_web_md` (auto-downloaded by installer). |
| M2 | Passive ingestion: Claude Code `UserPromptSubmit` hook captures user turns; `notify_turn` MCP tool captures assistant turns. `current_truth` tool (basic vector retrieval). Claude Code adapter fully wired. Hook config written by `sidequests setup`. |
| M3 | Loop Steps 1–4 + Step 3b. Step 1b: verb pattern relation extraction (universal, no LLM). Steps 2–3: gist + schema.org routing. Step 3b: Ollama relation extraction with type context (CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO). Step 4: pattern matching + confidence gating + Cocktail Party selective attention. Named relationship types: 9 types + `[hebbian] co_occurrence_threshold = 10` in `sidequests.toml`. |
| M4 | Loop Steps 5–7 (dual-scope retrieval, contradiction arbitration, pathway update + MergeEvent) |
| M5 | Quest lifecycle (git-anchor MainQuest, manual SideQuest branching, RAG read flow) |
| M6 | Open Brain document ingestion (Document + DocumentExtract pipeline, semantic chunking) |
| M7 | Memory Control Panel (FastAPI, graph visualization, soft-lock UI, merge rollback, Constraint Ledger export) |
| M8 | Claude desktop, Codex, ChatGPT desktop, and Gemini CLI adapters + Cross-Quest Analogical Reasoning |

## Acceptance Criteria (Phase 0)

- **Multi-Agent State Share:** Decision made in Claude Code is immediately visible in Codex
- **Temporal Deprecation:** Constraint deprecated in Codex updates `diff_since` in Claude Code
- **Deterministic Rollback:** Deleting a `MergeEvent` instantly reverts `current_truth` for all connected assistants
- **Bridge Test:** Constraint from chat shows raw text in UI; paraphrased query retrieves it via embedding
- **Open Brain Test:** Ingesting a markdown doc creates `Document` + `DocumentExtract` nodes; constraint appears in `current_truth` with exact `location_uri` and line ranges
- **Cross-Project Analogical Test:** New MainQuest surfaces relevant `Decision`/`Constraint` from a distinct MainQuest completed months prior

## Memory Audit CLI (`sidequests review`)

The system operates fully autonomously — no human confirmation required for uncertain nodes. However, the audit tool exists for users who want visibility or want to manually correct the graph.

`sidequests review` queries the graph for `confidence_low` nodes and displays them with context. User can promote, demote, or edit — but is never required to. M7 (Memory Control Panel) replaces this CLI with a richer web UI reading the same graph data.
