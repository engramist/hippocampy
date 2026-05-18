# HippoCampy — Architecture Specification

> **Canonical architecture reference for all agents and contributors.**
> This is the single source of truth for the system design, schema, Loop steps, tools, and IP claims.
> Agent-specific workflow files (CLAUDE.md, GEMINI.md, etc.) reference this document — do not duplicate architecture content there.

## Required Companion References

- Ecosystem rules (layer boundaries and separation rules): [docs/ecosystem-rules.md](ecosystem-rules.md)
- Tool catalog (keep in sync with tool schemas/handlers): [docs/tool-catalog.md](tool-catalog.md)
- Wiki projection architecture: [docs/wiki-projection-architecture.md](wiki-projection-architecture.md)
- ARC extraction boundary audit: [docs/arc-extraction-cleanup-audit.md](arc-extraction-cleanup-audit.md)
- Backlog card authoring and execution rules: [backlog/BacklogRules.md](../backlog/BacklogRules.md)
- Backlog planning/tracking status source: [backlog/masterBacklogTracker.md](../backlog/masterBacklogTracker.md)

## Patent Notice

**Patent Pending:** This system includes patent-pending memory architecture. U.S. Provisional Application #64/017,066 was filed March 25, 2026 (Confirmation #7549, Patent Center #75018063). Non-provisional filing deadline: March 25, 2027. No patent has been granted. See [docs/nonprovisional-strategy.md](nonprovisional-strategy.md) for strategy, filing facts, and public disclosure boundaries.

## Project Mission

**HippoCampy (Campy) — Phase 0: Standalone Brain Daemon** — Build a standalone local AI memory system backed by a Gated Consolidation Loop and a Graph-Native Kùzu database. The system exposes MCP STDIO adapters for Claude Code and Codex. OpenClaw integration is deferred to a later phase.

The core invention is the **Gated Consolidation Loop** — an active cognitive processing engine modeled on human biomimetic heuristics (Kahneman System 1/2, Representativeness, Availability) that transforms passive AI memory into a self-correcting, auditable knowledge graph structured around a Main Quest / Side Quest paradigm.

## Repository Scope After ARC_AGI Extraction

`hippocampy` is the local graph-native memory engine. ARC solver/runtime code, benchmark orchestration, and submission/compliance flows live in the sibling `ARC_AGI` repository.

This repository may still contain ARC-facing memory schemas, ingestion tools, wiki projections, and regression tests when they exercise the generic memory engine. Raw ARC run artifacts are evidence inputs only: they must be ingested into KuzuDB before retrieval or wiki projection treats them as memory.

## Context Strategy

Campy should **shrink decision context, not expand it**.

The operating philosophy is:
- keep only the minimum stable working context in the prompt
- use Campy retrieval to supply just-in-time decision support
- prefer compact summaries over raw dumps
- treat retrieval as a ranking/compression system, not a transcript loader
- gate retrieval behind concrete uncertainty triggers rather than always injecting memory

The immediate win is **small, purposeful context with fast, targeted retrieval**.

Longer-term backlog direction:
- move toward an active retrieval symbiosis where the agent begins with minimal working context and requests additional state only when a concrete decision requires it
- make passive Campy processes pattern-match likely-needed entities, neighborhoods, and paths ahead of demand so retrieval is effectively pre-warmed
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
- **LLM:** Configurable via `campy.toml` — Ollama (default/local) or cloud providers (OpenAI, Anthropic, Google) as opt-in
- **Memory Control Panel:** FastAPI web app bound strictly to `127.0.0.1` (no external access)
- **MCP Transport:** stdio only — no listening TCP/HTTP ports; Unix domain sockets for IPC between adapters and the Brain Daemon

## LLM Provider Configuration (`campy.toml`)

```toml
[llm]
provider = "ollama"           # ollama | openai | anthropic | google
model = "llama3.1:8b"
base_url = "http://localhost:11434"   # ollama only
# api_key loaded from env var for cloud providers

[embeddings]
model = "sentence-transformers/all-MiniLM-L6-v2"   # produces 384-dim vectors — matches FLOAT[384] schema
# WARNING: changing this model requires full re-embedding of all nodes in the graph.
# Run: campy reembed --confirm before switching models.

[ingestion]
max_ingest_chars = 4000   # passive ingestion only (conversational turns). Truncates at last sentence boundary.
# Long document ingestion uses the Open Brain pipeline (M6) which does proper semantic chunking.

[capture]
enabled = true

[capture.codex]
enabled = true
scan_interval_seconds = 10
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 1

[capture.claude_code]
enabled = true
scan_interval_seconds = 10
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 1

[capture.vscode]
enabled = true
scan_interval_seconds = 15
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 5

[activity]
log_path = "~/.campy/activity.log"  # compact operator feed for writes, recall, capture, and daemon state

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

**Provisional patent filed.** The canonical inventor's notebook records the filing on March 25, 2026:
Application # **64/017,066**, Confirmation # **7549**, Patent Center # **75018063**.
Priority date is March 25, 2026; the non-provisional deadline to preserve priority is
March 25, 2027.

Public release is no longer blocked by the pre-filing disclosure constraint, but any public
distribution should still be reviewed for implementation readiness, private data, proprietary
tuning details, and non-provisional strategy. Core IP claims covered by the filed disclosure:
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

Durable capture assurance:

  Codex, Claude Code, and VS Code/Copilot persist local transcript JSONL files.
  The Brain Daemon may tail those files as a replayable fallback when MCP calls
  are unavailable, misconfigured, or temporarily offline.

  The durable capture layer is not a second source of truth. It writes an
  append-only local journal, deduplicates by source event id, and replays
  extracted user/assistant message text through `notify_turn` so KuzuDB remains
  the canonical memory store.

  Capture connectors must ignore tool results, hidden reasoning, and
  adapter-injected/system messages. They exist for durability across client
  installs, not to expand prompt context or bypass the Gated Consolidation Loop.

Operator visibility:

  The Brain Daemon writes a compact activity feed to `~/.campy/activity.log`.
  This feed records memory writes, recall calls, durable capture scans, and
  daemon lifecycle state without dumping full prompt or response bodies.
  `campy activity --follow` is the durable local indicator until client UIs
  expose native status-bar/chrome extension points for Campy.

  This activity feed is the primary operator-facing health signal. The daemon
  log remains the debugging/error log and may contain stack traces or low-level
  startup chatter. Agents should point users to `campy activity --follow`
  when they ask "is Campy writing/recalling right now?" and reserve
  `~/.campy/daemon.log` for troubleshooting failures.

Agent memory-use policy:

  `skills/campy-memory/SKILL.md` is the canonical policy for supported
  agents. It teaches when to recall, when not to recall, which retrieval tool
  to use, and how to preserve the anti-bloat context strategy. Codex can install
  this as a local skill; Claude, Gemini, ChatGPT Desktop, VS Code, and other MCP
  clients receive the same policy through agent docs and adapter prompt
  fragments.

  `memory_decision` is the runtime helper for uncertain cases. It recommends
  whether to recall and which tool to call, but does not retrieve memory in v1.
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
hippocampy/
├── campy.toml
├── brain_daemon.py
├── mcp_engine/
│   ├── schema.py                # Kùzu schema init (all node + relationship DDL)
│   ├── tool_schemas.py          # Canonical MCP tool schema definitions (single source of truth)
│   ├── hippocampus.py           # Semantic Quest Routing (B17)
│   ├── working_memory.py        # Context Window Awareness (B18)
│   ├── warm_frontier.py         # Passive graph pre-activation (B91) — bounded warm node frontier
│   ├── capture.py               # Durable transcript capture fallbacks for supported local clients
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
│   ├── tabular_store.py         # SQLite-per-dataset storage layer (B249)
│   ├── tabular_ingest.py        # Tabular data ingestion pipeline — CSV/XLSX/TSV (B250)
│   ├── memory_router.py         # Ingestion classification — routes data to optimal storage (B251)
│   ├── bundle_compiler.py       # Heterogeneous retrieval — assembles ContextBundles (B252)
│   ├── formatters/              # Agent output formatters — per-adapter bundle shapes (B253)
│   │   ├── base.py              # BundleFormatter protocol
│   │   ├── generic.py           # Default JSON formatter
│   │   ├── claude_code.py       # Structured markdown with headers and decision lists
│   │   ├── claude_desktop.py    # Conversational prose with citations
│   │   ├── codex.py             # Ultra-compact code-focused output
│   │   ├── chatgpt_desktop.py   # Friendly bullet points
│   │   └── arc.py               # Structured JSON for ARC agents
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
├── sidequests/
│   ├── brain_transport.py       # shared daemon transport for adapters
│   └── cli/
│       ├── arc.py               # ARC artifact ingestion CLI wrapper
│       └── wiki.py              # wiki projection CLI helpers
├── docs/
│   ├── wiki-projection-architecture.md
│   └── arc-extraction-cleanup-audit.md
└── ../ARC_AGI/                  # sibling repo: ARC solver/runtime/benchmark code
```

ARC solver modules and benchmark harnesses were extracted from this repository. Campy keeps only the memory-facing integration surface: graph schema, MCP tools, ingestion/projection code, and regression tests that validate the memory engine as an ARC consumer backend.

## Optimization: Knowledge Pre-seeding (B108)

To reduce cold-start latency and avoid repeated LLM calls for stable protocol or project concepts, Campy supports **Knowledge Pre-seeding**.

- **Precomputed Artifacts**: Stable knowledge fragments can be ingested with pre-labeled entities and relations.
- **Loop Fast-Path**: When `precomputed` data is provided to `notify_turn`, the Gated Consolidation Loop bypasses Step 1 (NER), Step 2 (gist classification), and Step 3b (semantic relation extraction).
- **Local Re-embedding**: Entities are re-embedded locally during pre-seeded ingestion to ensure compatibility with the current `embeddings.model` configured in `campy.toml`.

This ensures consumers spend more time on the current task and less time re-learning stable API, project, or domain facts on every run.

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

`decay_rate` is configurable per node type in `campy.toml` (power user setting — sensible defaults provided). GlobalConstraints decay over years; raw Messages decay in weeks.

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

Raw `Message` nodes are part of the graph and may be retrieved as bounded
episodic evidence, especially for "what did we just say?" queries before the
Dreaming/sweep phase has consolidated the turn into Decisions, Constraints,
Lessons, or Procedures. Message recall must remain bounded and provenance-like:
it may add candidate `Message` nodes via vector or exact-text lookup, but those
candidates still rank by the same `pathway_strength × confidence ×
(1 + outcome_boost)` rule. Exact text lookup is candidate generation, not a
ranking override.

Raw `Message` and `DocumentExtract` results are not tracked with `LOADED` edges
for now. Their returned text still counts toward session token estimates and
bloat warnings, but they do not become handoff candidates or persistent
working-memory cargo. Consolidation should promote durable knowledge into
Decision, Constraint, Requirement, ActionItem, GlobalConstraint, or
GlobalPreference nodes before it participates in working-memory handoff.

## Active Agent System — Plan/Evaluate Loop (B66–B69)

Modern agentic workflows involve agents formulating multi-step plans before execution. The passive system (`notify_turn`) captures *what happened*; the active system captures *what was intended, what was tried, and whether it worked*.

### The Cognitive Loop

| Phase | Human Analog | Campy Implementation |
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

**External Consumer Evidence Nodes**:
- `ArcRun`, `ArcTaskResult`, `ArcArtifact`, `ArcEvent` — durable records created by `ingest_arc_artifacts` from sibling `ARC_AGI` run artifacts
- `ArcMechanic`, `ArcActionPattern`, `ArcEffectPattern`, `ArcPrecondition`, `ArcFailureMode`, `ArcRecoveryPolicy` — cross-run mechanic memory published by external ARC consumers
- `ArcWorldModelStep`, `ArcWorldModelSummary` — world-model evaluation evidence imported from ARC artifacts
- `Hypothesis` and `Exploration` — generic graph-native reasoning structures retained for non-ARC and external-consumer experiments

**Metacognitive & Procedural Nodes:**
- `Procedure` (B194) (`procedure_id`, `name`, `domain`, `archetype`, `description`, `steps_json`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `success_count`, `application_count`, `success_rate`, `confidence`, `pathway_strength`, `archived`, `created_at`, `last_applied_at`) — reusable parameterized strategy templates distilled from successful Plans
- `KnowledgeGap` (B193) (`gap_id`, `domain`, `gap_type`, `description`, `severity`, `message_count`, `lesson_count`, `resolved`, `created_at`, `resolved_at`) — metacognitive gap tracking for proactive learning

**Tabular Data Nodes** (B249):
- `Dataset` (`dataset_id`, `name`, `description`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `storage_uri STRING` — path to per-dataset SQLite file in `~/.campy/tables/`, `schema_json STRING` — column names/types/samples, `row_count INT64`, `column_count INT32`, `source_format STRING` — csv/xlsx/tsv/xls, `content_hash STRING`, `confidence`, `confidence_low`, `pathway_strength`, `archived`, `created_at`, `last_accessed_at`)

**Entity Curation Nodes:**
- `DisambiguationEvent` (B158) (`event_id`, `concept_id_a`, `concept_id_b`, `similarity`, `status`, `resolved_at`, `resolved_by`, `created_at`) — gray-zone entity pairs awaiting human or system resolution

**Task Graph Nodes** (B127/B128 — first-class execution DAGs):
- `TaskGraph` (`graph_id`, `name`, `description`, `label`, `status`, `version`, `created_at`) — durable dependency-aware execution graph
- `TaskNode` (`task_id`, `name`, `description`, `status`, `input_data`, `output_data`, `error_msg`, `created_at`, `started_at`, `completed_at`) — individual task within a graph

**Session & Infrastructure Nodes** (no embedding required):
- `Session` (`session_id`, `started_at`, `last_active_at`, `onboarded BOOLEAN`, `purpose STRING`, `routing_state STRING`, `routing_confidence FLOAT`, `routing_method STRING`, `token_estimate INT64`, `token_limit INT64`, `loaded_node_count INT32`, `last_injection_at TIMESTAMP`)

**Relationship Nodes:**
- `LOADED` (`injected_at TIMESTAMP`, `token_estimate INT32`, `source STRING`, `load_hits INT32`) — links `Session` to consolidated artifact nodes currently in its context window. Raw `Message` / `DocumentExtract` episodic recall is token-counted but not `LOADED`-tracked.
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

# Dataset provenance and linkage (B249)
(Dataset)-[DATASET_DERIVED_FROM]->(Document)
(Dataset)-[DATASET_BELONGS_TO_QUEST]->(MainQuest | SideQuest)
(Concept)-[DESCRIBED_BY_DATASET {extraction_method, created_at}]->(Dataset)

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
(Session)-[LOADED {injected_at, token_estimate, source, load_hits}]->(ConsolidatedArtifactNode)
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

# External consumer evidence and ARC memory integration
(ArcRun)-[ARC_RUN_HAS_TASK]->(ArcTaskResult)
(ArcRun)-[ARC_RUN_HAS_ARTIFACT]->(ArcArtifact)
(ArcTaskResult)-[ARC_TASK_HAS_EVENT]->(ArcEvent)
(ArcEvent)-[ARC_EVENT_FROM_ARTIFACT]->(ArcArtifact)
(ArcMechanic)-[ARC_MECHANIC_HAS_ACTION_PATTERN]->(ArcActionPattern)
(ArcMechanic)-[ARC_MECHANIC_CAUSES_EFFECT_PATTERN]->(ArcEffectPattern)
(ArcMechanic)-[ARC_MECHANIC_REQUIRES]->(ArcPrecondition)
(ArcMechanic)-[ARC_MECHANIC_FAILS_AS]->(ArcFailureMode)
(ArcFailureMode)-[ARC_FAILURE_RECOVERED_BY]->(ArcRecoveryPolicy)
(ArcRun)-[ARC_RUN_HAS_WORLD_MODEL_STEP]->(ArcWorldModelStep)
(ArcRun)-[ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(ArcWorldModelSummary)

# Generic hypothesis linkage
(Hypothesis)-[GENERALIZES]->(Hypothesis)
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

**`memory_decision`** — call when unsure whether a prompt warrants recall. Returns a compact recommendation (`should_recall`, `recommended_tool`, `query`, `reason`, `confidence`, `context_budget`, `anti_bloat_guidance`) without retrieving memory. Routes multi-entity or broad context queries to `compile_context` (B254). This is the runtime companion to `skills/campy-memory/SKILL.md`.

**`current_truth`** — call before answering architecture or past-decision questions. Searches consolidated artifacts and bounded episodic `Message` evidence, then ranks by graph strength (`pathway_strength × confidence`, plus bounded outcome valence). Includes optional `include_rationale` for 1-hop provenance context.

**`explore_graph`** — directed multi-hop traversal with configurable depth, strategy (DFS/BFS), edge types, direction, and context window (B10)

**`recall_relevant_lessons`** — cross-quest analogical recall (B11)

**`recall_plans`** — retrieve past strategies by goal similarity (B67)

**`analogical_search`** — cross-quest search (M8)

**`reconstruct_timeline`** — reconstruct temporal sequence of messages and decisions for a topic (B192)

**`recall_procedures`** — retrieve reusable Procedure templates by archetype or semantic query, ranked by success rate (B194)

**`get_knowledge_gaps`** — return active KnowledgeGap nodes for proactive metacognitive review (B193)

### Bundle Compilation & Tabular Tools (B249–B254)

**`compile_context`** — heterogeneous retrieval: assembles a `ContextBundle` from exact facts (GlobalConstraint/Preference), semantic search, graph traversals, tabular data, and wiki summaries. 5-stage pipeline with token budget management (small ≤8K, medium ≤128K, large 200K+). Output formatted per agent type via `mcp_engine/formatters/`. This is the primary retrieval tool for multi-entity queries; `memory_decision` routes here when it detects broad context needs.

**`ingest_document`** (extended) — now dispatches `.csv`, `.xlsx`, `.tsv`, `.xls` files to the tabular ingestion pipeline (B250). Tabular files get dual storage: full data in per-dataset SQLite + metadata/extracted facts in the Kuzu graph.

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


### ARC Memory Integration Tools

These tools exist so external ARC consumers can use Campy as graph-native memory without reintroducing ARC runtime code into this repo:

- **`ingest_arc_artifacts`** — import ARC_AGI run artifacts into KuzuDB as durable graph records
- **`publish_mechanic_summary`** — persist learned ARC mechanics and action/effect patterns
- **`recall_mechanic_priors`** — retrieve graph-backed mechanic priors for an ARC agent
- **`recall_scene_graph_priors`** — retrieve progress priors keyed by scene graph signatures

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


## Wiki Projection (B221-B224)

The wiki is a read-only Markdown projection of graph state designed for tactile browsing in Obsidian or any Markdown viewer. KuzuDB remains the single source of truth.

Core invariants:
- generated pages are cache artifacts, not authoritative state
- persona directories provide isolated lenses over the same graph
- projection happens during the Dreaming/sweep phase
- manual notes belong under `wiki/manual-notes/` and must be ingested back through normal memory pathways
- drift protection moves manually edited generated pages to conflict copies before regenerating canonical pages

Primary implementation files:
- `mcp_engine/wiki_projection.py`
- `mcp_engine/sweep.py`
- `campy/cli/wiki.py`
- `docs/wiki-projection-architecture.md`

### ARC Artifact Projection

ARC_AGI artifacts do not become wiki pages directly. They first flow through `ingest_arc_artifacts`, which writes `ArcRun`, `ArcTaskResult`, `ArcArtifact`, `ArcEvent`, `ArcMechanic`, and world-model evaluation nodes into KuzuDB. The `arc_agi` wiki persona then projects those graph records into browsable Markdown.

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
pip install hippocampy        # or: pip install -e . from repo
campy setup                    # Claude Code (auto-detected)
campy setup --target claude-desktop
campy setup --target chatgpt-desktop
campy setup --target gemini-cli
campy setup --target codex
```

`campy setup` per target:
1. Detects Ollama or prompts for cloud provider + API key
2. Writes `campy.toml` (project root) or `~/.campy/config.toml` (global)
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
| M1 | Kùzu schema + `campy.toml` config + IPC daemon skeleton + LLM provider abstraction. Phase 0 = English only. **Centroid bootstrap:** embed all 105 `GistSeedExamples.md` sentences, mean-pool per class, store as `GistClass.centroid FLOAT[384]`. spaCy model: `en_core_web_md` (auto-downloaded by installer). |
| M2 | Passive ingestion: Claude Code `UserPromptSubmit` hook captures user turns; `notify_turn` MCP tool captures assistant turns. `current_truth` tool (basic vector retrieval). Claude Code adapter fully wired. Hook config written by `campy setup`. |
| M3 | Loop Steps 1–4 + Step 3b. Step 1b: verb pattern relation extraction (universal, no LLM). Steps 2–3: gist + schema.org routing. Step 3b: Ollama relation extraction with type context (CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO). Step 4: pattern matching + confidence gating + Cocktail Party selective attention. Named relationship types: 9 types + `[hebbian] co_occurrence_threshold = 10` in `campy.toml`. |
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

## Relationship To ARC_AGI

`ARC_AGI` is now a sibling repository. It owns:

- ARC solver runtime modules
- ARC benchmark harness and submission/compliance logic
- ARC-specific prompt policy and phase orchestration
- ARC experiment artifacts that are not graph memory records

`hippocampy` owns:

- the shared graph-native memory backend
- durable schema for generic memory and ARC-facing evidence records
- MCP/adapter tool surfaces used by external consumers
- artifact ingestion tools that convert ARC outputs into graph memory
- wiki projections generated from KuzuDB records

Historical ARC backlog cards/plans may be archived or migrated, but active ARC solver architecture should be documented in `ARC_AGI`, not here. See `docs/arc-extraction-cleanup-audit.md` for the current boundary manifest.

## Memory Audit CLI (`campy review`)

The system operates fully autonomously — no human confirmation required for uncertain nodes. However, the audit tool exists for users who want visibility or want to manually correct the graph.

`campy review` queries the graph for `confidence_low` nodes and displays them with context. User can promote, demote, or edit — but is never required to. M7 (Memory Control Panel) replaces this CLI with a richer web UI reading the same graph data.

Optional developer tooling note:
- local graph-browsing/debug workflows are allowed, but they must remain optional tooling outside the
  main Campy runtime/install path
- if we use Kuzu Explorer or similar tools to inspect the graph, treat them as read-only developer
  visibility aids, not part of the core product surface
ace
