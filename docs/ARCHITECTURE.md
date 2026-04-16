# Side Quests — Architecture Specification

> **Canonical architecture reference for all agents and contributors.**
> This is the single source of truth for the system design, schema, Loop steps, tools, and IP claims.
> Agent-specific workflow files (CLAUDE.md, GEMINI.md, etc.) reference this document — do not duplicate architecture content there.

## Required Companion References

- Ecosystem rules (layer boundaries and separation rules): [docs/ecosystem-rules.md](ecosystem-rules.md)
- Tool catalog (keep in sync with tool schemas/handlers): [docs/tool-catalog.md](tool-catalog.md)
- ARC harness ownership and orchestration constraints: [docs/arc-harness-rules.md](arc-harness-rules.md)
- Backlog card authoring and execution rules: [backlog/BacklogRules.md](../backlog/BacklogRules.md)
- Backlog planning/tracking status source: [backlog/masterBacklogTracker.md](../backlog/masterBacklogTracker.md)

## Project Mission

**Side Quests — Phase 0: Standalone Brain Daemon** — Build a standalone local AI memory system backed by a Gated Consolidation Loop and a Graph-Native Kùzu database. The system exposes MCP STDIO adapters for Claude Code and Codex. OpenClaw integration is deferred to a later phase.

The core invention is the **Gated Consolidation Loop** — an active cognitive processing engine modeled on human biomimetic heuristics (Kahneman System 1/2, Representativeness, Availability) that transforms passive AI memory into a self-correcting, auditable knowledge graph structured around a Main Quest / Side Quest paradigm.

## Context Strategy

SideQuests should **shrink decision context, not expand it**.

The operating philosophy is:
- keep only the minimum stable working context in the prompt
- use SideQuests retrieval to supply just-in-time decision support
- prefer compact summaries over raw dumps
- treat retrieval as a ranking/compression system, not a transcript loader
- gate retrieval behind concrete uncertainty triggers rather than always injecting memory

The immediate win is **small, purposeful context with fast, targeted retrieval**.

Longer-term backlog direction:
- move toward an active retrieval symbiosis where the agent begins with minimal working context and requests additional state only when a concrete decision requires it
- make passive SideQuests processes pattern-match likely-needed entities, neighborhoods, and paths ahead of demand so retrieval is effectively pre-warmed
- model this like biomimetic selective activation: passive sensory intake drives likely-memory activation before the explicit request arrives
- make the first sensory packet rich in stable ids, compact structural signatures, and observed-effect summaries so passive pattern matching has something useful to pre-activate against

This is not "zero context" in the literal sense. Every agent still needs a small stable operating frame:
- role and task
- tool/action constraints
- output contract
- safety boundaries

Everything else should earn its way into the prompt.

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
│   ├── schema.py                # Kùzu schema init (all node + relationship DDL)
│   ├── tool_schemas.py          # Canonical MCP tool schema definitions (single source of truth)
│   ├── hippocampus.py           # Semantic Quest Routing (B17)
│   ├── working_memory.py        # Context Window Awareness (B18)
│   ├── warm_frontier.py         # Passive graph pre-activation (B91) — bounded warm node frontier
│   ├── dictionary.py            # Domain dictionary pre-seed from YAML (B160)
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
│       ├── __init__.py          # MCP tool implementations: notify_turn, current_truth, etc.
│       ├── explore_graph.py     # Directed multi-hop graph traversal
│       └── task_graph.py        # DAG task graph helpers (B127/B128) — cycle detection, ready frontier
├── adapters/
│   ├── openclaw_gateway.py      # OpenClaw prompt construction (Layer 1 + Layer 2 model)
│   ├── claude_code/adapter.py        # Phase 0
│   ├── claude_desktop/adapter.py     # M8
│   ├── codex/adapter.py              # M8
│   ├── chatgpt_desktop/adapter.py    # M8
│   └── gemini_cli/adapter.py         # M8
├── web/
│   ├── server.py                # FastAPI, 127.0.0.1 only
│   └── static/                  # Graph UI, soft-lock UI, merge rollback
├── agents/
│   └── arc3/                    # ARC-AGI-3 solving agent
│       ├── orchestrator.py      # Perceive→hypothesize→solve→act pipeline + Phase routing (B156)
│       ├── solver.py            # SolveEngine + TransformationHypothesizer (B151)
│       ├── runner.py            # DurableARCRunner + multi-level game loop (B156/B157)
│       ├── hypothesis.py        # HypothesisManager, StateGraph, ActionFacts
│       ├── prompts.py           # Pattern, execution, navigation prompt templates (B153)
│       ├── grid_analysis.py     # GridDiffEngine, TransformationSignature (B150)
│       ├── entity_graph.py      # EntityGraphBuilder — graph exploration agent (B168)
│       ├── repl_verification.py # REPLVerificationLoop, HypothesisRefinementLoop (B152)
│       ├── repl_sandbox.py      # Python REPL sandbox (B123)
│       ├── supervisor.py        # PuzzleSupervisor — trajectory-aware meta-supervisor (B183)
│       ├── circuit_breaker.py   # CircuitBreakerLLMClient — retry/backoff/fail-fast (B184)
│       ├── failure_taxonomy.py  # FailureTaxonomy enum + classify_failure() (B185)
│       ├── cost_tracker.py      # CostTracker — per-puzzle token/USD budget enforcement (B180)
│       ├── scheduler.py         # PuzzleScheduler — difficulty ordering + health checks (B189)
│       ├── strategy_racer.py    # StrategyRacer — race N strategy variants concurrently (B187)
│       └── checkpoint.py        # CheckpointManager — atomic checkpoint for durable runs
├── benchmarks/
│   └── arc3/                    # ARC-AGI-3 A/B harness + evaluation infrastructure
│       ├── harness.py           # Baseline vs SideQuests-augmented runner
│       ├── adapter.py           # Episode normalization bridge (NoOp, Ledger, Local clients)
│       ├── state_serializer.py  # State-to-text serialization
│       ├── outcome_judge.py     # OutcomeJudge — LLM-as-Judge rubric scoring (B181)
│       ├── trajectory_eval.py   # TrajectoryEvaluator — offline trajectory quality scoring (B186)
│       └── regression_monitor.py # RegressionMonitor — rolling cross-run regression detection (B188)
└── tests/
```

## Optimization: Knowledge Pre-seeding (B108)

To reduce cold-start latency and avoid repeated LLM calls for stable protocol concepts (like the ARC-AGI-3 API contract), SideQuests supports **Knowledge Pre-seeding**.

- **Precomputed Artifacts**: Stable knowledge fragments can be ingested with pre-labeled entities and relations.
- **Loop Fast-Path**: When `precomputed` data is provided to `notify_turn`, the Gated Consolidation Loop bypasses Step 1 (NER), Step 2 (gist classification), and Step 3b (semantic relation extraction).
- **Local Re-embedding**: Entities are re-embedded locally during pre-seeded ingestion to ensure compatibility with the current `embeddings.model` configured in `sidequests.toml`.

This ensures that the ARC harness spends more time solving the puzzle and less time re-learning the same ARC protocol on every run.

## Directional Chunk Enforcement (B109)

**Note: This mechanism operates in Phase 2 only.** In execution mode (Phase 1 succeeded), chunks are not used — the agent paints cells deterministically. In fallback mode (Phase 1 failed), chunk enforcement is the primary guidance mechanism.

To ensure goal-directed behavior in Phase 2 fallback, the Solve Engine and Orchestrator collaborate to enforce planned sequences:
- **Chunk Registration**: Every generated `PlanChunk` is registered as a unique `Plan` in SideQuests.
- **Strict Enforcement**: The Orchestrator’s `_enforce_action_policy` prioritizes the active chunk’s `estimated_actions` over raw LLM suggestions.
- **Exploration-Intent Bypass (B213)**: Before the decay guard fires, `_enforce_action_policy` checks whether the LLM is choosing to explore. If `action_id in unexplored` or the rationale contains explicit exploration language ("haven’t tried", "new action", "unexplored", etc.), the decay guard is skipped and the LLM’s choice is honored. Exploration intent from the LLM is higher-authority than fatigue state from prior steps.
- **Execution Tracking**: The Solve Engine tracks `steps_executed` per chunk, and `DissonanceDetector` triggers replanning if a chunk stalls (zero progress) for too long. B154 reduces stall thresholds from 6→3 steps.

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

The same principle should guide retrieval and prompting:
- passive systems should continuously score which entities, paths, and neighborhoods are becoming more likely to matter
- active prompting should request only the top-ranked decision support, not bulk-load everything currently available
- retrieval speed should come from pre-activation and graph-native locality, not from stuffing larger context windows

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
- `Lesson` (`lesson_id`, `text_raw`, `embedding`, `domain`, `lesson_type`, `confidence`, `confidence_low`, `pathway_strength`, `archived`, `created_at`, `last_audited_at`, `stale_flagged`, `orphan_flagged`)
- `Plan`, `PlanStep` — see Active Agent System section above

**ARC Exploration Graph Nodes** (B168, ephemeral per-puzzle, no embedding):
- `GridEntity` (`entity_id`, `task_id`, `level`, `color_id`, `region_index`, `pixel_count`, `centroid_row/col`, `bbox_*`, `location_hint`, `aspect_ratio`, `compactness`, `is_background`, `is_mobile`, `is_interactive`, `inferred_role`, `role_confidence`, `last_updated_step`, `created_at`)
- `GridSnapshot` (`snapshot_id`, `task_id`, `level`, `step`, `grid_hash`, `rows`, `cols`, `n_entities`, `symmetry_axes`, `created_at`)
- `ActionEffect` (`effect_id`, `task_id`, `level`, `action_id`, `step`, `n_cells_changed`, `apparent_effect`, `direction_row/col`, `created_at`)

**ARC Persistence Nodes** (per-puzzle state promoted from in-memory to graph-native):
- `ActionFact` (B171) (`fact_id`, `task_id`, `level`, `action_id`, `fact_type`, `description`, `effect_description`, `consistency`, `confidence`, `value_status`, `evidence_count`, `observation_count`, `delta_row/col`, `n_cells_changed`, `created_at`, `last_updated`) — deterministic action facts extracted from repeated observations
- `VictoryCondition` (B172) (`condition_id`, `task_id`, `level`, `condition_type`, `description`, `target_color_id`, `confidence`, `source`, `evidence_steps`, `created_at`, `last_updated`) — inferred win conditions
- `ChunkExecution` (B174) (`execution_id`, `task_id`, `level`, `plan_id`, `chunk_family`, `description`, `status`, `steps_used`, `graduation_score`, `evidence_at_end`, `dissonance_triggered`, `outcome_summary`, `created_at`, `last_updated`) — chunk execution ledger
- `PuzzleCostSummary` (B180) (`summary_id`, `task_id`, `model`, `tokens_in/out`, `cost_usd`, `outcome`, `steps`, `created_at`) — FinOps cost tracking per puzzle

**Hypothesis & Exploration Nodes:**
- `Hypothesis` (B88) (`hypothesis_id`, `task_id`, `level`, `hypothesis_type`, `description`, `confidence`, `status`, `evidence_count`, `counter_evidence_count`, `created_at`, `last_updated`) — systematic hypothesis tracking for ARC exploration

**Metacognitive & Procedural Nodes:**
- `Procedure` (B194) (`procedure_id`, `name`, `domain`, `archetype`, `description`, `steps_json`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `success_count`, `application_count`, `success_rate`, `confidence`, `pathway_strength`, `archived`, `created_at`, `last_applied_at`) — reusable parameterized strategy templates distilled from successful Plans
- `KnowledgeGap` (B193) (`gap_id`, `domain`, `gap_type`, `description`, `severity`, `message_count`, `lesson_count`, `resolved`, `created_at`, `resolved_at`) — metacognitive gap tracking for proactive learning

**Entity Curation Nodes:**
- `DisambiguationEvent` (B158) (`event_id`, `concept_id_a`, `concept_id_b`, `similarity`, `status`, `resolved_at`, `resolved_by`, `created_at`) — gray-zone entity pairs awaiting human or system resolution

**Task Graph Nodes** (B127/B128 — first-class execution DAGs):
- `TaskGraph` (`graph_id`, `name`, `description`, `label`, `status`, `version`, `created_at`) — durable dependency-aware execution graph
- `TaskNode` (`task_id`, `name`, `description`, `status`, `input_data`, `output_data`, `error_msg`, `created_at`, `started_at`, `completed_at`) — individual task within a graph

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
(Message)-[FOLLOWED_BY {gap_seconds}]->(Message)                # temporal message chain
(Decision | Constraint)-[ESTABLISHED_IN]->(Session)
(Decision)-[DECISION_CHAIN {session_id, step_number}]->(Decision) # ordered decision sequences

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

# Entity disambiguation (B158)
(Concept)-[DISTINCT_FROM {created_at, source}]->(Concept)       # entities confirmed as distinct

# Working memory + warm frontier
(Session)-[LOADED {injected_at, token_estimate, source, load_hits}]->(ArtifactNode)
(Session)-[WARM_NODE {activation_score, activated_at}]->(ArtifactNode) # B91 pre-activation
(Session)-[REROUTED_FROM {rerouted_at, reason}]->(MainQuest)

# Anomaly detection (B12)
(ArtifactNode)-[ANOMALY_DETECTED {type, confidence, detected_at}]->(GlobalConstraint | GlobalPreference)

# Lesson integration (B11)
(MainQuest)-[PRODUCED_LESSON]->(Lesson)
(Session)-[LEARNED]->(Lesson)
(Lesson)-[APPLIES_TO]->(Concept | Decision | Requirement)
(Lesson)-[RELATED_TO]->(Lesson)
(Lesson)-[GENERALIZES_LESSON {synthesized_at, cluster_size}]->(Lesson) # lesson clustering
(Message)-[CONTAINS_LESSON]->(Lesson)

# Active Agent System — Plans (B66–B69)
(Plan)-[PLANNED_IN]->(Session)
(Plan)-[TARGETS]->(MainQuest | SideQuest)
(Plan)-[EXECUTED_AS {seq}]->(ChunkExecution)                    # chunk execution ledger (B174)
(PlanStep)-[STEP_OF]->(Plan)
(PlanStep)-[NEXT_STEP]->(PlanStep)
(PlanStep)-[ACTS_ON]->(Concept)
(Plan)-[PRODUCED_PLAN_LESSON]->(Lesson)
(PlanStep)-[OUTCOME_SIGNAL {valence, plan_id, observed_at}]->(Concept)

# Procedure & Knowledge Gap (B193/B194)
(Procedure)-[DISTILLED_FROM {synthesized_at}]->(Plan)           # procedure synthesized from plan
(Procedure)-[APPLIES_TO_ARCHETYPE]->(Concept)                   # domain/archetype linkage
(Plan)-[APPLIED_PROCEDURE {success, applied_at}]->(Procedure)   # plan used this procedure
(KnowledgeGap)-[IDENTIFIED_GAP_IN]->(MainQuest | Concept)       # gap detected in domain

# Hypothesis engine (B88)
(Hypothesis)-[HYPOTHESIZED_IN]->(Session)
(Concept)-[CONFIRMS {weight}]->(Hypothesis)
(Concept)-[CONTRADICTS {weight}]->(Hypothesis)
(Hypothesis)-[GENERALIZES]->(Hypothesis)
(Plan)-[PRODUCED_HYPOTHESIS]->(Hypothesis)
(ActionFact)-[SUPPORTS_HYPOTHESIS {weight}]->(Hypothesis)

# Task Graph (B127/B128)
(TaskNode)-[TASK_OF]->(TaskGraph)
(TaskNode)-[DEPENDS_ON]->(TaskNode)

# ARC Exploration Graph (B168)
(GridEntity)-[OBSERVED_IN {step}]->(GridSnapshot)
(GridEntity)-[ADJACENT_TO {min_distance, direction, step}]->(GridEntity)
(GridEntity)-[STRUCTURALLY_SIMILAR {similarity, color_shifted, step}]->(GridEntity)
(GridEntity)-[SAME_COLOR_AS]->(GridEntity)
(GridEntity)-[CONTAINS_ENTITY {step}]->(GridEntity)
(GridEntity)-[MOVED_BY {delta_row, delta_col}]->(ActionEffect)
(GridEntity)-[RESPONDS_TO {effect_type}]->(ActionEffect)
(GridEntity)-[BLOCKS {action_id, step}]->(GridEntity)
(GridEntity)-[CO_MOVES_WITH {step}]->(GridEntity)
(GridEntity)-[CORRELATES_WITH {step, mechanism}]->(GridEntity)
(GridEntity)-[CAUSES_CHANGE_IN {mechanism, confidence, step}]->(GridEntity)
(ActionFact)-[DERIVED_FROM_FACT {step}]->(ActionEffect)         # B171 fact provenance
(GridEntity)-[ENTITY_HYPOTHESIS {weight, step}]->(Hypothesis)

# Victory condition linkage (B172)
(VictoryCondition)-[INFERRED_FROM {weight}]->(Hypothesis)
(VictoryCondition)-[REQUIRES_ENTITY {requirement}]->(GridEntity)
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

**`current_truth`** — call before answering architecture or past-decision questions (includes optional `include_rationale` for 1-hop ESTABLISHED_IN message context)

**`explore_graph`** — directed multi-hop traversal with configurable depth, strategy (DFS/BFS), edge types, direction, and context window (B10)

**`recall_relevant_lessons`** — cross-quest analogical recall (B11)

**`recall_plans`** — retrieve past strategies by goal similarity (B67)

**`analogical_search`** — cross-quest search (M8)

**`reconstruct_timeline`** — reconstruct temporal sequence of messages and decisions for a topic (B192)

**`recall_procedures`** — retrieve reusable Procedure templates by archetype or semantic query, ranked by success rate (B194)

**`get_knowledge_gaps`** — return active KnowledgeGap nodes for proactive metacognitive review (B193)

### Quest Management Tools

**`branch_quest`** — create SideQuest (M5)

**`complete_quest`** — mark Quest finished (M5)

**`set_quest`** — explicit quest override

**`diff_since`** — delta retrieval since prior session (M5)

**`get_open_loops`** — retrieve `confidence_low` nodes (M5)

### Active Agent Tools (B67)

**`register_plan`** — declare multi-step strategy

**`report_outcome`** — report step/plan results with valence

### Task Graph Tools (B127/B128)

**`register_task_graph`** — declare a first-class execution DAG (TaskGraph + TaskNodes) with dependency edges and cycle detection

**`get_ready_tasks`** — return the topological frontier: all pending tasks whose upstream dependencies are complete

**`advance_task`** — transition a task to active/complete/skipped; returns newly unblocked tasks

**`fail_task`** — mark a task as failed; returns blocked dependents

**`get_task_graph`** — return full graph state (nodes + edges) for audit

### Lesson Tools (B11)

**`upsert_lesson`** — explicitly add or update a domain-specific lesson

**`recall_relevant_lessons`** — cross-quest analogical recall

### Entity Curation Tools (B158)

**`get_disambiguation_queue`** — get pending gray-zone entity pairs for human review

**`resolve_disambiguation`** — resolve a disambiguation pair: merge, separate, or skip

### Domain Dictionary Tools (B160)

**`reload_domain_dictionary`** — reload domain dictionary from `.sidequests/domain_dictionary.yaml`; adds new entities and altLabels without duplicating

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

### OpenClaw Gateway (`adapters/openclaw_gateway.py`)

The OpenClaw gateway constructs system prompts for OpenClaw plugin sessions using the same two-layer model. It auto-detects git context (repo root + branch) for MainQuest alignment and provides memory-aware tool aliases (`memory_recall`, `memory_store`, `memory_search_analogies`, `memory_status`) that map to the underlying MCP tools.

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

## ARC-AGI-3 Benchmark Agent

The ARC-AGI-3 agent is the first proof-of-concept for SideQuests augmenting a real benchmark.
It consumes SideQuests through the existing MCP tool surface. B168 adds ARC-specific graph schema (GridEntity, GridSnapshot, ActionEffect nodes + 12 relationship types) for the exploration knowledge substrate.

The agent uses a **level-aware learning pipeline** (B150–B157): B157 enables multi-level game progression. At each level transition, the agent analyzes solved levels (B150), generates game rule hypotheses (B151), and verifies them (B152). This accumulated knowledge configures the prompt (B153), exploration policy (B154), and orchestration mode (B156) for subsequent levels.

Before goal-seeking begins, the **Graph Exploration Agent** (B168) builds a knowledge substrate in KuzuDB through two-phase exploration: static structural analysis (zero steps) followed by a deterministic action sweep (~4 steps). A dual inference engine (Tier 1-3 deterministic + Tier 4 LLM background) propagates behavioral and causal relationships through the graph. Graph-inferred entity roles feed into the existing ObjectRoleMapper with higher confidence than blind heuristic bootstrapping.

See "ARC Inner-Loop: Level-Aware Learning Pipeline" and "ARC Graph-Based Exploration Agent" below for the full architecture.

### ARC Solve Phase State Machine (B201)

The ARC solver uses a **durable 7-phase state machine** owned by the Agent Orchestration & Control Plane (`PhaseController` in `agents/arc3/phase.py`). Phases are explicit, inspectable, and governed by gate conditions that must be satisfied before advancing.

**Design rules:**
- `PhaseController` is the single owner of phase transitions. The orchestrator and solve engine read the current phase but never advance it.
- `brain.current_phase` remains a string for backward compatibility with ledger recording.
- `finalization` is post-loop cleanup and is NOT a solve phase.
- Gate conditions reuse existing signals — no new LLM calls.
- Step budgets force-advance if a gate doesn't open within N steps.

#### Phase Order and Execution Pattern

**Once per attempt (setup):**
```
PERCEIVE → MODEL
```

**Per-step cycle (repeats until WIN, GAME_OVER, or budget exhausted):**
```
HYPOTHESIZE → ROUTE → EXECUTE → EVALUATE → PERCEIVE → HYPOTHESIZE (continue)
                                          → REPLAN (stall detected)
```

**Replan branches back to:**
```
REPLAN → MODEL        (need more world understanding)
REPLAN → HYPOTHESIZE  (hypothesis was wrong)
REPLAN → ROUTE        (just pick new strategy)
```

#### Phase Definitions

| # | Phase | Purpose | Code entry point |
|---|---|---|---|
| 1 | **PERCEIVE** | **Bootstrap:** intake initial observation, seed API knowledge cache. **Per-step (B202):** inspect ARC server response fields (state, reward, grid delta, available actions), write structured `ActionEffect` lesson record to SideQuests (B211). | `orchestrator.perceive()` [bootstrap], `orchestrator.perceive_step_response()` + `_write_action_effect_record()` [per-step] |
| 2 | **MODEL** | Build world/map understanding — entity roles, topology, spatial patterns, grid analysis. Register initial plan with SideQuests. | `orchestrator.plan()` |
| 3 | **HYPOTHESIZE** | Infer game archetype, victory condition, strategy candidates. Detect loops. Summarize action coverage. **Second pass (B212):** structured graph queries against prior `ActionEffect` lesson records to produce evidence-grounded `grounded_hypotheses` — runs when `step > 0` and archetype is known. | `orchestrator.hypothesize()` → `orchestrator.graph_hypothesize()` [step > 0, archetype known] |
| 4 | **ROUTE** | Select strategy chunk (BFS, directional, explore). Graduate or replan based on solve context. | `orchestrator.solve()` |
| 5 | **EXECUTE** | Submit chosen action to environment, receive frame response. | `orchestrator.act()` |
| 6 | **EVALUATE** | Ingest step result, record reward, check WIN/GAME_OVER. Decide: continue or replan. | `adapter.ingest_step()`, `orchestrator.record_step_result()` |
| 7 | **REPLAN** | Escalation phase when stalls detected. Analyzes signals to decide where to loop back. | `DurableARCRunner._replan_target()` |

#### Transition Table

```
┌──────────────┐
│   PERCEIVE   │
└──────┬───────┘
       │ observation received, API knowledge seeded
       ▼
┌──────────────┐
│    MODEL     │
└──────┬───────┘
       │ initial_exploration_complete OR step ≥ MODEL_BUDGET
       ▼
┌──────────────┐◄────────────────────────────────────────┐
│  HYPOTHESIZE │                                         │
└──────┬───────┘                                         │
       │ archetype_confidence ≥ 0.3 OR step ≥ HYP_BUDGET │
       ▼                                                 │
┌──────────────┐◄──────────────────────────┐             │
│    ROUTE     │                           │             │
└──────┬───────┘                           │             │
       │ active chunk selected             │             │
       ▼                                   │             │
┌──────────────┐                           │             │
│   EXECUTE    │                           │             │
└──────┬───────┘                           │             │
       │ action submitted, frame received  │             │
       ▼                                   │             │
┌──────────────┐                           │             │
│   EVALUATE   │── no stall ──────────────►│ HYPOTHESIZE │
└──────┬───────┘                           │             │
       │ loop_detected OR                  │             │
       │ no_progress ≥ 3                   │             │
       ▼                                   │             │
┌──────────────┐                           │             │
│   REPLAN     │── new strategy ──────────►┘             │
│              │── bad hypothesis ────────────────────────┘
│              │── need world model ──► MODEL
└──────────────┘
```

#### Gate Conditions

| Transition | Gate | Force-advance fallback |
|---|---|---|
| PERCEIVE → MODEL | Initial observation received, API knowledge seeded | None (always satisfies on first call) |
| MODEL → HYPOTHESIZE | `initial_exploration_complete == True` (all actions tested) | `step ≥ MODEL_BUDGET` (default: 4) |
| HYPOTHESIZE → ROUTE | `archetype_confidence ≥ 0.3` | `step ≥ HYPOTHESIS_BUDGET` (default: 6) |
| ROUTE → EXECUTE | Active chunk is not None | None (solve always produces a chunk or explore fallback) |
| EXECUTE → EVALUATE | Action submitted, frame response received | None (always satisfies after action) |
| EVALUATE → PERCEIVE | Not done AND no stall signals | (default path — no gate needed) |
| EVALUATE → REPLAN | `loop_detected == True` OR `no_progress_steps ≥ 3` | — |
| REPLAN → MODEL | `initial_exploration_complete == False` | — |
| REPLAN → HYPOTHESIZE | `archetype_confidence < 0.3` | — |
| REPLAN → ROUTE | (default — signals don't indicate model or hypothesis gap) | — |

#### Signal Sources

| Signal | Computed in | Type | Access path |
|---|---|---|---|
| `initial_exploration_complete` | `HypothesisManager._summarize_action_coverage()` | bool | `context["action_coverage"]["initial_exploration_complete"]` |
| `archetype_confidence` | `SolveEngine._archetype_confidence` | float | `solve_ctx.get("archetype_confidence")` |
| `loop_detected` | `HypothesisManager.hypothesize()` | bool | `orchestrator._hypothesis_context.get("loop_detected")` |
| `no_progress_steps` | `DurableARCRunner._run_puzzle()` | int | Local counter `consecutive_no_progress_steps` |
| `positions_known` | `SolveEngine._graduation_assessment()` | float | Internal to graduation (1.0 if player + goal known) |
| `victory_confidence` | `SolveEngine._victory_condition.confidence` | float | `solve_ctx["victory_condition"]["confidence"]` |
| `action_coverage` | `HypothesisManager._summarize_action_coverage()` | dict | `context["action_coverage"]` |

#### Checkpoint Support

`PhaseController` is checkpointable via `to_checkpoint()` / `from_checkpoint()`. On crash recovery, the controller restores its exact phase and history. Phase state is persisted as an optional `phase_state` field in `TaskCheckpoint`.

### ARC Harness / Meta-Harness Split

For ARC, the architectural boundary should be explicit:

- **ARC Harness** — the inner loop that plays one multi-level game. ARC-AGI-3 games have 7-8
  levels, progressing from simple tutorials to harder puzzles. The agent plays all levels (B157),
  analyzing each solved level (B150) to build up game rule understanding (B151/B152). Early
  levels teach the game's rules; later levels apply that knowledge. The existing navigation/
  exploration machinery (ActionFacts, HypothesisManager, PlanChunker) handles per-level action
  selection, with exploration policy adapting by level (B154) and prompts showing prior level
  insights (B153).
- **Meta-Harness** — the outer loop that proposes edits to the ARC harness, runs evaluations,
  logs traces and scores, compares candidate harnesses, and evolves the harness over time.
- **SideQuests** — the graph-native experience store and retrieval substrate for the outer loop.
  SideQuests is not the ARC harness itself. It is the structured memory backend that makes
  meta-harness search more queryable than raw flat-file navigation.

There are three different memory problems here:

- **Cross-game memory**: Game strategies (action semantics, game rules, level-solving approaches)
  from completed games, keyed by grid characteristics (size, colors, actions). Retrieved via
  embedding similarity to seed level 1 exploration. Stored/retrieved through `notify_turn` and
  `current_truth`. (B155)
- **Within-game memory (cross-level)**: Solved level diffs, game rule hypotheses, action semantics —
  knowledge accumulated across levels within a single game. Persists across levels (B157 preserves
  cross-level state) but is ephemeral to the game session. Not persisted to SideQuests.
- **Outer-loop memory**: What the meta-harness needs across many harness candidates and runs.
  Harness candidates, score summaries, traces, failure chains, mutation lineage.

SideQuests can support all three, but they should not be conflated.

The intended direction is:

1. keep the ARC harness focused on playing one multi-level game well (all 7-8 levels)
2. let cross-game learning (B155) transfer action semantics and game strategies between games
3. let the meta-harness optimize the ARC harness instead of hand-tuning retrieval/prompt logic
4. use SideQuests to store and retrieve prior harness candidates, score summaries, traces,
   failure chains, mutation lineage, and successful strategy fragments

This is a strong graph fit because the outer loop is relationship-heavy:

- harness candidate -> evaluation run
- evaluation run -> puzzle trace
- puzzle trace -> promoted action fact / path hypothesis / role inference
- run -> score / runtime / token budget / failure mode
- candidate -> parent candidate / mutation rationale / diff lineage

That workload is lineage-heavy, comparison-driven, and traversal-centric, which is exactly where a
labeled property graph is a better operational substrate than ad hoc directory traversal plus regex
search.

### Required Experience Entities (Outer-Loop)

- `HarnessCandidate`: A specific version/configuration of the ARC harness being evaluated.
- `HarnessEvalRun`: A collection of puzzle attempts using a specific `HarnessCandidate`.
- `HarnessMutation`: An atomic change to a harness candidate (e.g., prompt tweak, policy shift).
- `HarnessScoreSummary`: Aggregated performance metrics (correctness, tokens, runtime) for an eval run.
- `HarnessFailureCluster`: Grouping of similar failure modes across multiple puzzles or candidates.
- `PuzzleTraceRef`: A durable reference to the full execution trace of a puzzle solve attempt.

### Meta-Harness Proposer Loop (B107)

The **Meta-Harness Proposer Loop** is the automated outer-loop engine that evolves ARC harness
candidates. It follows a disciplined **Proposal / Evaluate / Store / Retrieve** cycle:

1.  **Retrieve**: The proposer queries the **Experience Store** (via `MetaHarnessQuerySurface`)
    for top-performing candidates, common failure clusters, and recent regression signatures.
2.  **Propose**: Based on retrieved context, the proposer generates a `HarnessMutation` (e.g.,
    refining the "evidence gap" trigger or tightening the "action fact" promotion threshold).
3.  **Evaluate**: The proposer hands the new `HarnessCandidate` to the **MetaHarnessRunner**
    for evaluation against a fixed puzzle set.
4.  **Store**: The runner persists the `HarnessEvalRun` and `HarnessScoreSummary` back into the
    SideQuests graph, linking it to the mutation and parent candidate.
5.  **Select**: The proposer compares the results against the baseline and decides whether to
    promote the candidate to the new "best known" or try a different mutation branch.

**Bounded Search Policy:**
To prevent unconstrained refactoring, the proposer is restricted to:
- **Prompt Logic**: adjustments to stable operating context or just-in-time retrieval triggers.
- **Heuristic Thresholds**: tuning promotion levels for action facts or path hypotheses.
- **Retrieval Policy**: modifying the `scope`, `limit`, or `min_similarity` for memory fetching.

The proposer operates as a coding-agent executor (Gemini/Haiku style), using SideQuests as its
long-term "experience backend" to avoid repeating failed experiments.

**Full agent architecture:** [`agents/arc3/arcAgent_Architecture.md`](../agents/arc3/arcAgent_Architecture.md)

### ARC Inner-Loop: Level-Aware Learning Pipeline (B150–B157)

ARC-AGI-3 is an **interactive multi-level game**, not a static transformation puzzle. Games have 7-8 levels progressing from simple tutorials to harder puzzles. There are **no static training examples** — the agent discovers rules by playing. Early levels are implicit tutorials. Solved levels become training data for later levels.

The agent uses a **level-aware learning pipeline**: play level → analyze → hypothesize → verify → apply knowledge to next level.

#### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ Game Start                                                     │
│                                                                │
│  B155: Retrieve cross-game memory (if similar game played)    │
│                                                                │
│  B168: GRAPH EXPLORATION PHASE (before goal-seeking)          │
│  ├─ Phase 1: Static analysis (0 steps) → GridEntity nodes    │
│  │   └─ Spatial + structural edges in KuzuDB                  │
│  ├─ Phase 2a: Deterministic sweep (~4 steps)                  │
│  │   └─ MOVED_BY, RESPONDS_TO, CORRELATES_WITH edges          │
│  ├─ Dual inference: Tier 1-3 blocking + Tier 4 LLM background│
│  └─ Handoff: graph roles → ObjectRoleMapper (high confidence) │
│                                                                │
│  Level 1: EXPLORE (graph-informed, not blind)                 │
│  ├─ B153: Exploration prompt ("discover what actions do")     │
│  ├─ B154: Full exploration budget (up to 5 forced steps)      │
│  ├─ ActionFact tracking: learning from scratch                │
│  └─ Navigation/VictoryHypothesizer: existing fallback         │
│                                                                │
│  Level 1 WIN ──► B157: _on_level_transition()                 │
│  ├─ B157: Capture (start_grid, end_grid, action_sequence)     │
│  ├─ B150: diff_grids() → GridDiff, initial LevelPattern      │
│  ├─ B151: hypothesize() → GameRuleHypothesis[]                │
│  └─ B156: Set confidence, select mode for level 2             │
│                                                                │
│  Level 2+: APPLY (growing knowledge)                          │
│  ├─ B153: Rule-application prompt (show prior level insights) │
│  ├─ B154: Reduced exploration (2 forced steps)                │
│  ├─ ActionFacts: carry over from prior levels                 │
│  └─ Game rule hypothesis guides action selection              │
│                                                                │
│  Level 2 WIN ──► B157: _on_level_transition()                 │
│  ├─ B150: Update LevelPattern with 2+ level consensus         │
│  ├─ B151: Refine hypotheses with more evidence                │
│  ├─ B152: Verify against ALL solved levels (zero cost)        │
│  └─ B156: Update confidence, may enter execution mode         │
│                                                                │
│  Level 3+: EXECUTE (high confidence)                          │
│  ├─ B153: Execution prompt if confidence > 0.8                │
│  ├─ B154: Zero forced exploration                             │
│  └─ Apply learned rule directly                               │
│                                                                │
│  ... continue through all levels (B157 game loop) ...         │
│                                                                │
│  Game Complete ──► B155: Store game strategy to memory         │
└──────────────────────────────────────────────────────────────┘
```

#### Why Level-Aware Learning

ARC-AGI-3 games require progressive skill acquisition:

1. **Level 1 = tutorial**: Simple version of the game. Agent discovers what actions do (ACTION1-4 = directional, ACTION5 = interact, ACTION6 = coordinate, ACTION7 = undo). This is trial-and-error — the existing navigation machinery is the right tool.

2. **Levels 2-3 = learning**: Agent has solved level(s). The (start_grid, end_grid, action_sequence) triples are implicit training examples. B150 analyzes what changed. B151 hypothesizes the game's rules. Confidence grows with each solved level.

3. **Levels 4+ = exploitation**: Action effects and game rules are well-established. The agent applies knowledge directly with minimal exploration. Each new solved level refines and validates the hypothesis.

The old approach treated every level as isolated, re-exploring from scratch. It also exited on the first WIN (runner bug), never attempting levels 2-8. With `win_levels: 8` and only level 1 attempted, the agent scored zero.

RHAE scoring: `(human_actions / ai_actions)^2` per level, weighted by level index, averaged across levels. Later levels count more — exactly where accumulated knowledge matters most.

#### What's Retained from the Old Approach

The navigation/exploration machinery is **retained** for level 1 and fallback:

| Component | Status | Why |
|-----------|--------|-----|
| `ActionFact` tracking | **Retained** | Essential for learning what actions do on level 1; persists across levels |
| `HypothesisManager` / `StateGraph` | **Retained** | Loop detection, state tracking on all levels |
| `_enforce_action_policy()` | **Retained + modified (B154)** | Level-progressive: full on level 1, minimal on later levels |
| `DissonanceDetector` | **Retained + tuned (B154)** | Detects stalls (thresholds 6→2 for tight per-level budgets) |
| `PlanChunker` | **Retained** | Structures multi-step plans on any level |
| `VictoryHypothesizer` | **Retained** | Level 1 fallback hypothesis generation |
| `GameArchetype` / `ObjectRoleMapper` | **Retained + enhanced (B168)** | Now bootstrapped with graph-inferred roles from exploration instead of blind heuristics |

#### Card Dependency Chain

```
B157 (Multi-Level Progression) ──── CRITICAL BLOCKER
       │
       ├──► B150 (Grid Diff Engine) ─────┐
       │         │                        ├──► B151 (Game Rule Hypothesizer) ──┐
       │         │                        │                                    │
       │         ├──► B168 (Graph         │    B153 (Level-Aware Prompts) ◄────┤
       │         │    Exploration Agent)   │    B155 (Cross-Game Memory) ◄──────┤
       │         │    + B119 + B166        │                                    │
       │         │                        └──► B152 (Level-Replay Verify) ─────┤
       ├──► B154 (Level-Progressive                                            │
       │     Exploration)                                                      │
       │                                                                       │
       └──────────────────────── B156 (Level-Aware Orchestration) ◄────────────┘
```

#### Key Files

| File | Role |
|------|------|
| `agents/arc3/runner.py` | B157: Multi-level game loop, level transition capture, per-level budgeting |
| `agents/arc3/grid_analysis.py` | B150: GridDiffEngine, GridDiff, FrameDelta, LevelPattern |
| `agents/arc3/repl_verification.py` | B152: LevelReplayVerifier, RuleRefinementLoop |
| `agents/arc3/solver.py` | B151: GameRuleHypothesizer, GameRuleHypothesis + existing SolveEngine |
| `agents/arc3/orchestrator.py` | B156: Level-aware orchestration, knowledge pipeline, mode routing |
| `agents/arc3/prompts.py` | B153: Exploration, rule-application, execution, navigation templates |
| `agents/arc3/entity_graph.py` | B168: EntityGraphBuilder — graph-based exploration + dual inference engine |
| `agents/arc3/supervisor.py` | B183: PuzzleSupervisor — trajectory-aware meta-supervisor |
| `agents/arc3/circuit_breaker.py` | B184: CircuitBreakerLLMClient — LLM call resilience |
| `agents/arc3/failure_taxonomy.py` | B185: FailureTaxonomy enum + classify_failure() |
| `agents/arc3/cost_tracker.py` | B180: CostTracker — per-puzzle token/USD budget enforcement |
| `agents/arc3/scheduler.py` | B189: PuzzleScheduler — puzzle ordering + health checks |
| `agents/arc3/strategy_racer.py` | B187: StrategyRacer — concurrent strategy variant racing |
| `agents/arc3/checkpoint.py` | CheckpointManager — atomic checkpoint for durable runs |
| `benchmarks/arc3/outcome_judge.py` | B181: OutcomeJudge — LLM-as-Judge rubric scoring |
| `benchmarks/arc3/trajectory_eval.py` | B186: TrajectoryEvaluator — offline trajectory quality scoring |
| `benchmarks/arc3/regression_monitor.py` | B188: RegressionMonitor — rolling regression detection |

### ARC Graph-Based Exploration Agent (B168)

The agent builds a **knowledge substrate** through deliberate exploration before attempting to solve the puzzle. Without this, heuristics like ObjectRoleMapper operate blind — guessing "smallest = player, largest = goal" with no grounding.

**Analogy:** A baby cannot solve a puzzle without first building neural pathways through exploration and curiosity. B168 emulates this — an Explorer/Curiosity agent builds up nodes and relationships that downstream agents (ObjectRoleMapper, autopilot, strategy selection) draw from.

#### Two-Phase Exploration

**Phase 1 — Static Analysis** (pre-action, step 0, no steps consumed):
- Extract all connected components from the initial grid → `GridEntity` nodes in KuzuDB
- Compute pairwise spatial relationships → `ADJACENT_TO`, `CONTAINS_ENTITY` edges
- Compute structural similarity between regions → `STRUCTURALLY_SIMILAR` edges (via `GridDiffEngine.compare_regions()`)
- Flag background entities (color 0 or >50% coverage)
- Create `GridSnapshot` node anchoring all entities at step 0

**Phase 2a — Deterministic Sweep** (~4-8 steps depending on available actions):
- Try each available action once and record what changes via `GridDiffEngine.diff_frames()`
- For each action: create `ActionEffect` node, identify which entities moved/changed
- Create behavioral edges: `MOVED_BY`, `RESPONDS_TO`, `CO_MOVES_WITH`, `CORRELATES_WITH`
- After sweep: graph knows which entities are mobile, static, interactive

**Handoff:** Graph-inferred roles (player, goal, wall, intermediate) fed to existing ObjectRoleMapper via `orchestrator.merge_graph_roles()` — higher confidence wins.

#### Dual Inference Engine

After each exploration step, `run_inference()` runs four tiers:

| Tier | Type | What it does |
|------|------|-------------|
| Tier 1 | Blocking | **Similarity propagation** — if entity A moved, propagate `is_mobile` through `STRUCTURALLY_SIMILAR` and `SAME_COLOR_AS` edges with decayed confidence |
| Tier 2 | Blocking | **Relational inference** — co-movement (`CO_MOVES_WITH`), co-occurrence of mover+reactor (`CORRELATES_WITH`), blocking detection (`BLOCKS`) |
| Tier 3 | Blocking | **Role elimination** — once player confirmed (2+ moves), propagate wall/intermediate roles via structural similarity; constrain remaining unknowns |
| Tier 4 | Background | **LLM causal reasoning** — examines `CORRELATES_WITH` edges with `mechanism='unknown'`, asks LLM to explain causation (e.g. "player moved → health bar shrank"), creates `CAUSES_CHANGE_IN` edges. Non-blocking via `asyncio.create_task()` |

**Exploration frontier:** After each inference pass, `_get_exploration_frontier()` returns entities with `role_confidence < 0.5` and `inferred_role = 'unknown'`. If inference collapses the frontier to 0, exploration can end early.

#### B168 Graph Schema

**Node types:** `GridEntity`, `GridSnapshot`, `ActionEffect`, `ActionFact` (B171), `VictoryCondition` (B172) (see `mcp_engine/schema.py`)

**Relationship types (15 total):**

```
# Structural (Phase 1)
(GridEntity)-[OBSERVED_IN {step}]->(GridSnapshot)
(GridEntity)-[ADJACENT_TO {min_distance, step}]->(GridEntity)
(GridEntity)-[STRUCTURALLY_SIMILAR {similarity, color_shifted, step}]->(GridEntity)
(GridEntity)-[SAME_COLOR_AS]->(GridEntity)
(GridEntity)-[CONTAINS_ENTITY {step}]->(GridEntity)

# Behavioral (Phase 2a)
(GridEntity)-[MOVED_BY {delta_row, delta_col}]->(ActionEffect)
(GridEntity)-[RESPONDS_TO {effect_type}]->(ActionEffect)
(GridEntity)-[BLOCKS {action_id, step}]->(GridEntity)

# Inference (Tier 2-4)
(GridEntity)-[CO_MOVES_WITH {step}]->(GridEntity)
(GridEntity)-[CORRELATES_WITH {step, mechanism}]->(GridEntity)
(GridEntity)-[CAUSES_CHANGE_IN {mechanism, confidence, step}]->(GridEntity)

# Fact provenance (B171)
(ActionFact)-[DERIVED_FROM_FACT {step}]->(ActionEffect)
(ActionFact)-[SUPPORTS_HYPOTHESIS {weight}]->(Hypothesis)

# Victory condition (B172)
(VictoryCondition)-[INFERRED_FROM {weight}]->(Hypothesis)
(VictoryCondition)-[REQUIRES_ENTITY {requirement}]->(GridEntity)

# Hypothesis linkage
(GridEntity)-[ENTITY_HYPOTHESIS {weight, step}]->(Hypothesis)
```

#### Integration Points

- **Runner** (`runner.py`): Creates `EntityGraphBuilder` between perceive/plan and the main action loop. Passes `llm_client` for Tier 4 inference.
- **Orchestrator** (`orchestrator.py`): `merge_graph_roles()` accepts graph-inferred `ObjectRole` dict, merges with existing heuristic roles (higher confidence wins).
- **Adapter** (`adapter.py`): `db` property exposed on all `BrainClient` implementations (`LocalBrainClient`, `NoOpBrainClient`, `LedgerBrainClient`).
- **NoOp compatibility:** When `brain.db` is `None`, the entire exploration phase is skipped — zero impact on baseline benchmarks.

#### Step Budget

With 4 available actions typical:
- Phase 1: 0 steps (static analysis only)
- Phase 2a: 4 steps (one per action)
- **Total: ~4 steps** out of 119+ budget (<4%)

---

### Structured ActionEffect Writes and Graph Inference (B211–B213)

#### Problem

The existing `ingest_step` / `notify_turn` flow stores action outcomes as **narrative text strings** (e.g. `"Step 3: ACTION2 changed 1 pixel"`). SideQuests ingests these into `Concept` nodes via NER and consolidation, producing text retrievable by semantic similarity — but not by structural graph pattern. You cannot query: _"find ActionEffect records where entity_type=compact_object and action=INTERACT and effect_class=large_transformation"_ because those typed fields don't exist. The knowledge is there but stored in a form that requires knowing the right text query in advance — circular.

#### B211: Structured ActionEffect Writes (write path)

After every step in `perceive_step_response()`, `_write_action_effect_record()` writes a typed lesson record via `brain.upsert_lesson`:

```python
{
    "lesson_type": "action_effect",
    "action": "ACTION5",
    "entity_type": "compact_object",    # from _solve_context["roles"]
    "effect_class": "large_transformation",  # derived from FrameDelta
    "n_cells_changed": 48,
    "direction": None,
    "new_colors": [...],
    "removed_colors": [...],
    "reward_signal": 0.0,
    "spatial_role": "trigger",
    "puzzle_archetype": "space",
    "task_id": "...",
    "step": 5,
}
```

`effect_class` derivation from `FrameDelta`:
- `n_cells_changed == 0` → `"no_effect"`
- `direction` present AND `n_cells_changed <= 4` → `"directional_movement"`
- `n_cells_changed > 30` → `"large_transformation"`
- otherwise → `"local_change"`

This write happens **in addition to** the existing `notify_turn` narrative. Not called at step 0 (no action yet).

#### B212: Graph Inference in HYPOTHESIZE (read path)

`graph_hypothesize()` runs inside the HYPOTHESIZE phase after `hypothesize()`, guarded by `step > 0` and archetype != `"unknown"`. It issues three tiers of structured queries:

| Tier | Tool | Query form | Retrieves |
|------|------|-----------|-----------|
| 1 | `recall_relevant_lessons` | `lesson_type:action_effect effect_class:large_transformation puzzle_archetype:{arch}` | Past steps where action caused significant change in same archetype |
| 2 | `current_truth` | Structural board description built by `_build_spatial_query()` | VictoryCondition/Hypothesis records from spatially similar past puzzles |
| 3 | `recall_procedures` | `{archetype} trigger_object interaction` | Stored Procedure nodes for similar archetypes |

Results are distilled rule-based (no LLM calls) by counting `(action, entity_type, effect_class)` triplets across retrieved lessons:

```python
_hypothesis_context["graph_evidence"] = {
    "action_effect_patterns": [...],   # raw tier 1 lessons
    "spatial_victory_hints": [...],    # tier 2 truth records
    "matching_procedures": [...],      # tier 3 procedures
    "grounded_hypotheses": [           # distilled evidence-backed candidates
        {"action": "ACTION5", "entity_type": "compact_object",
         "expected_effect": "large_transformation", "evidence_count": 3},
        ...
    ],
}
```

`grounded_hypotheses` with `evidence_count >= 2` are injected into the act/solve prompts under a **"GRAPH EVIDENCE"** section. The "rotation trigger" pattern emerges from accumulated evidence — not from puzzle-specific hard-coded heuristics.

#### B213: Revert Puzzle-Specific Heuristics (policy fix)

`_detect_split_map_rotate_cross()` (introduced by an earlier session) detected plus-shaped objects and hard-forced ACTION5 — solving one puzzle by giving the agent the answer. It was wired into three places (`_enforce_action_policy`, `perceive_step_response`, `_try_autopilot`). **B213 removes it entirely.** Graph inference (B212) is the generalized replacement.

B213 also adds the exploration-intent bypass described above in the Directional Chunk Enforcement section.

#### Data flow summary

```
per-step PERCEIVE  ──► _write_action_effect_record()
                          │
                          ▼
                   brain.upsert_lesson(lesson_type="action_effect", ...)
                          │
                          ▼ [next step or next puzzle]
HYPOTHESIZE        ──► graph_hypothesize()
                          │
                          ├─ recall_relevant_lessons("lesson_type:action_effect ...")
                          ├─ current_truth(spatial_query)
                          └─ recall_procedures(archetype query)
                          │
                          ▼
                   _hypothesis_context["graph_evidence"]["grounded_hypotheses"]
                          │
                          ▼
                   act() / solve() prompt: "GRAPH EVIDENCE" section
```

---

### ARC Agent Resilience & Evaluation Infrastructure (B180–B189)

The ARC agent includes a layer of operational infrastructure for cost control, failure handling, trajectory monitoring, and evaluation quality. These modules sit alongside the core solving pipeline and operate as cross-cutting concerns.

#### Meta-Supervisor (B183)

`PuzzleSupervisor` provides trajectory-aware meta-monitoring, replacing simple step-count escalation with richer decision logic.

**Decision types:** `CONTINUE` | `NUDGE` (suggest course correction) | `RESET_STRATEGY` | `ABANDON`

**Two-tier evaluation:**
1. **Rule-based checks (fast path, no LLM):** oscillation detection (same 2-3 states repeating), zero-reward stalls (no progress for N steps), budget exhaustion
2. **LLM escalation (optional):** for ambiguous trajectories where rule-based checks are inconclusive

Runs at configurable intervals (`check_interval`, default every 5 steps).

#### Circuit Breaker (B184)

`CircuitBreakerLLMClient` wraps the inner LLM client with retry/backoff/fail-fast behavior to prevent transient provider failures from crashing puzzles.

**States:** `CLOSED` (normal) → `OPEN` (fail-fast, no calls) → `HALF_OPEN` (probe with one call)

- `failure_threshold`: consecutive failures before opening (default 3)
- `cooldown_seconds`: time in OPEN state before HALF_OPEN probe (default 30s)
- `max_retries`: per-call retry limit with exponential backoff (default 3)
- Emits trace events for observability

#### Failure Taxonomy (B185)

`FailureTaxonomy` is a stable enum for classifying puzzle failures into structured categories that downstream metrics can distinguish:

| Category | Meaning |
|----------|---------|
| `LLM_TIMEOUT` | LLM call timed out |
| `LLM_PARSE_ERROR` | LLM response couldn't be parsed |
| `API_ERROR` | ARC API returned an error |
| `BUDGET_EXCEEDED` | Token or USD budget exhausted |
| `STRATEGY_EXHAUSTED` | All strategies tried and failed |
| `STUCK_IN_LOOP` | Agent oscillating between same states |
| `MAX_STEPS_REACHED` | Step limit hit without solving |
| `CRASH` | Unhandled exception |

`classify_failure()` is a defensive helper that maps exceptions, states, and signals → taxonomy bucket.

#### Cost Tracker (B180)

`CostTracker` accumulates per-puzzle token usage and computes dollar cost. Budget enforcement stops the puzzle before overspending.

- `model_name`, `input_price_per_m`, `output_price_per_m`: pricing configuration
- `budget_usd`: per-puzzle hard limit (default: unlimited)
- `record(tokens_in, tokens_out)`: increment counters
- `total_cost_usd`: computed property
- `budget_exhausted`: boolean check

#### Strategy Racer (B187)

`StrategyRacer` runs 2-3 strategy variants concurrently via `asyncio`, keeping the winner.

**Key design:** `BufferedBrainClient` wraps `BrainClientProtocol` to buffer write calls per-variant. Reads pass through to the real client; writes are buffered. The winning variant's writes are committed via `commit()`; losing variants' writes are discarded.

This enables safe concurrent runs where only the winning strategy's side effects persist.

#### Puzzle Scheduler (B189)

`PuzzleScheduler` handles puzzle ordering by difficulty, health checks, and concurrency readiness. Used by the DurableARCRunner to control which puzzles are attempted and in what order.

#### Checkpoint Manager

`CheckpointManager` provides atomic checkpoint read/write for durable ARC runs, stored at `~/.sidequests/arc_checkpoints/`. Enables run resumption after crashes.

### ARC Benchmark Evaluation (B181, B186, B188)

#### Outcome Judge (B181)

`OutcomeJudge` uses LLM-as-Judge to provide rubric-based grading for near-miss ARC puzzle attempts. This replaces binary pass/fail with a 3-dimension score:

| Dimension | Score | What it measures |
|-----------|-------|-----------------|
| Structural correctness | 0-5 | Grid dimensions, color palette, cell matching |
| Partial match | 0-5 | Fraction of cells matching expected solution |
| Reasoning quality | 0-5 | Trajectory narrative — correct archetype, strategy, execution |

Composite score is a weighted average. The judge prompt includes actual grid, expected grid, trajectory, and archetype.

#### Trajectory Evaluator (B186)

`TrajectoryEvaluator` performs offline algorithmic quality scoring across 5 dimensions:

| Dimension | What it measures |
|-----------|-----------------|
| Action diversity | Variety of actions used vs. repetitive patterns |
| Hypothesis convergence | Whether hypotheses narrow over time |
| Exploration efficiency | Information gained per step spent |
| Plan adherence | How well execution followed declared plans |
| Escalation quality | Appropriate use of strategy escalation |

Max score: 20 (4 points per dimension). Pure algorithmic — no LLM calls.

#### Regression Monitor (B188)

`RegressionMonitor` implements rolling 3-run comparison for cross-run regression detection. History stored as JSONL at `benchmarks/results/regression_history.jsonl`. Emits structured `RegressionAlert` objects with severity levels (warning/critical) when metrics degrade beyond thresholds.

---

### Domain Dictionary Pre-Seed (B160)

To accelerate entity recognition for domain-specific vocabularies, SideQuests supports pre-seeding the knowledge graph from a YAML domain dictionary.

**Dictionary location:** `.sidequests/domain_dictionary.yaml` (or `domain_dictionary.yaml` at project root)

**Format:**
```yaml
version: 1
entities:
  - text: "Kùzu"
    gist_class: "PhysicalThing"
    alt_labels: ["kuzu", "KuzuDB"]
  - text: "Gated Consolidation Loop"
    gist_class: "PlannedEvent"
    alt_labels: ["consolidation loop", "GCL"]
```

**Behavior:** Each entity is ingested as a `Concept` node with its gist class, embedding, and altLabels. Idempotent — re-ingestion with the same dictionary does not create duplicates. Triggered automatically on daemon startup or manually via `reload_domain_dictionary` tool.

### Warm Frontier Pre-Activation (B91)

`warm_frontier.py` maintains a bounded frontier of graph nodes that are likely to be needed soon, enabling zero-latency context matching for retrieval.

**Algorithm:**
1. **Direct Activation** — vector search for nodes similar to the current message
2. **Spread Activation** — expand to 1-hop neighbors of Phase 1 nodes (decayed by `HOPS_DECAY = 0.5`)
3. **Bounding** — keep top N nodes by activation score (`MAX_WARM_NODES = 20`)
4. **Persistence** — write `WARM_NODE` relationships to the graph

Warm nodes are preferred in retrieval, giving a biomimetic "priming" effect where recently relevant concepts are more readily available.

---

## Memory Audit CLI (`sidequests review`)

The system operates fully autonomously — no human confirmation required for uncertain nodes. However, the audit tool exists for users who want visibility or want to manually correct the graph.

`sidequests review` queries the graph for `confidence_low` nodes and displays them with context. User can promote, demote, or edit — but is never required to. M7 (Memory Control Panel) replaces this CLI with a richer web UI reading the same graph data.

Optional developer tooling note:
- local graph-browsing/debug workflows are allowed, but they must remain optional tooling outside the
  main SideQuests runtime/install path
- if we use Kuzu Explorer or similar tools to inspect the graph, treat them as read-only developer
  visibility aids, not part of the core product surface
