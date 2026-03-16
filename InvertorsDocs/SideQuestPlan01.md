# SideQuest Phase 0 — Implementation Plan

**Date:** March 7, 2026
**Version:** 1.0
**Status:** Approved — Ready to Build

---

## Context

This plan captures all architectural decisions made during the March 7, 2026 design session. It supersedes the OpenClaw-fork approach originally described in the Inventor's Notebook. Phase 0 is now a standalone Brain Daemon with direct MCP STDIO adapters — no dependency on any third-party agent framework.

---

## What Was Resolved in This Session

### Gaps Identified & Closed

| Gap | Resolution |
|-----|-----------|
| "Fast classifier" was undefined | Replaced with correct 7-step biomimetic Loop starting with spaCy NER |
| Ontology routing position was wrong | Moved to Steps 2–3, BEFORE pattern matching (Step 4) — this is now a novelty claim |
| Local LLM was unspecified | Configurable provider abstraction; default Ollama + llama3.1:8b on Apple Silicon |
| OpenClaw dependency | Removed from Phase 0 entirely; deferred to later phase |
| Quest lifecycle undefined | Git-anchor auto MainQuest; manual SideQuest branching; auto-detection as future goal |
| Memory Control Panel undefined | FastAPI web app, 127.0.0.1 only |
| pathway_strength decay undefined | Formula defined: `new = current + 1 * log(1 + 1/days_since_last_access)` |
| Kahneman System 1/2 not documented | Added as named novelty claim in Step 2 and Section 5.7 of notebook |

---

## Architecture

### Deployment Model

```
Brain Daemon (Python, standalone)
  ├── Kùzu embedded DB (graph + vector, READ_WRITE exclusive)
  ├── Gated Consolidation Loop (9 steps: 1, 1b, 2, 3, 3b, 4, 5, 6, 7)
  ├── Unix domain socket IPC server
  └── Memory Control Panel (FastAPI, bound to 127.0.0.1 only)

Per-Assistant Adapters (hook config + MCP server)
  ├── adapters/claude_code/       # Phase 0 — hook config + MCP server
  ├── adapters/claude_desktop/    # M8
  ├── adapters/codex/             # M8
  ├── adapters/chatgpt_desktop/   # M8
  └── adapters/gemini_cli/        # M8

[Passive browser extension adapter (ChatGPT web, Gemini web) — deferred to later phase]
[OpenClaw adapter — deferred to Phase 1]
```

**Passive ingestion per adapter type:**

| Adapter | User turns | Assistant turns |
|---------|-----------|----------------|
| Claude Code (Phase 0) | `UserPromptSubmit` hook → Brain socket (zero LLM involvement) | `notify_turn` MCP tool call |
| All M8 adapters | `notify_turn` MCP tool call | `notify_turn` MCP tool call |

`notify_turn` is called automatically per system prompt instruction — the LLM acts as a courier only. The Brain's Step 4 confidence gate controls all selective attention. Tool call results and adapter-injected system messages are never forwarded.

### LLM Provider Configuration (`sidequests.toml`)

```toml
[llm]
provider = "ollama"           # ollama | openai | anthropic | google
model = "llama3.1:8b"
base_url = "http://localhost:11434"   # ollama only
# api_key loaded from env var for cloud providers

[embeddings]
model = "sentence-transformers/all-MiniLM-L6-v2"   # 384-dim — matches FLOAT[384] schema
# WARNING: changing model requires full re-embedding of all graph nodes.
# Run: sidequests reembed --confirm

[ingestion]
max_ingest_chars = 4000   # passive ingestion (conversational turns only). Truncates at last sentence boundary.
# Long documents → Open Brain pipeline (M6) with proper semantic chunking.

[quest]
auto_complete_days = 30   # suggest Quest completion after N days with no new messages (0 = disabled)

[pruning]
# Synaptic Pruning — decay rates per node type (power user setting, defaults work for most users)
# Values 0–1; lower = faster decay. Models the Ebbinghaus Forgetting Curve.
decay_rate.global_constraint  = 0.999   # half-strength in ~2 years
decay_rate.global_preference  = 0.999
decay_rate.decision           = 0.995   # half-strength in ~140 days
decay_rate.constraint         = 0.995
decay_rate.requirement        = 0.990   # half-strength in ~70 days
decay_rate.action_item        = 0.980   # half-strength in ~35 days
decay_rate.message            = 0.970   # half-strength in ~23 days
decay_rate.document_extract   = 0.970

archive_threshold        = 0.10   # archive when pathway_strength falls below this
resurrection_threshold   = 0.85   # resurrect archived node if new message matches above this
sweep_interval_seconds   = 300    # background sweep interval (pruning + confidence re-scoring)
```

All LLM calls use an OpenAI-SDK-compatible interface. Ollama and cloud providers share the same code path — only `base_url` and `api_key` differ. This makes the system portable for all users regardless of their preferred model.

---

## The Gated Consolidation Loop — 9 Steps

```
Incoming message
    ↓
[Step 1 — Zoning / NER]
  spaCy extracts: people, objects, places, actions, quantities, events
  → Zero LLM cost. Fast, deterministic.
    ↓
[Step 1b — Relation Extraction: Fast Path (Universal Verb Patterns)]
  Syntactic relation extraction via universal verb pattern matching.
  Zero LLM cost. No extra dependencies — spaCy already loaded in Step 1.
  Only verbs where syntax alone is sufficient signal regardless of domain:

  require/need/depend/necessitate    → REQUIRES
  enable/allow/support/permit        → ENABLES
  replace/supersede/deprecate        → REPLACES
  contradict/conflict/violate/negate → CONTRADICTS
  contain/include + "is part of"     → PART_OF

  Domain-agnostic: works for software, writing, research, business.
  Types requiring entity type context (CHOSEN_OVER, IMPLEMENTS, EXTENDS,
  ALTERNATIVE_TO) deferred to Step 3b which has full gist+schema.org context.
  Confirmed edges written to Kùzu immediately.
    ↓
[Step 2 — gist Rapid Classification (Kahneman System 1 / System 2)]
  System 1 (fast): embedding cosine similarity vs. gist class centroids
    > 0.85 similarity  → accept result instantly (no LLM)
    0.60 – 0.85        → ambiguous → escalate to LLM call (System 2)
    < 0.60             → noise → early exit → vector-log only
  gist classes: PhysicalThing, PlannedEvent, Restriction,
                Magnitude, Category, Agent, Event
  Self-improving: System 2 resolutions saved as labeled examples
                  → centroids improve → S2 rate decreases over time
    ↓
[Step 3 — schema.org Sub-graph Routing]
  gist class routes to ONLY the relevant schema.org property subset.
  Routing table is core IP — stored as (GistClass)-[ROUTES_TO]->(SchemaOrgType)
  graph edges, seeded at M1 schema init. Step 3 code queries these nodes
  at runtime — no hardcoded routing logic.

  gist:Restriction   → schema:Demand
    props: eligibleCustomerType, availability, validFrom, validThrough,
           businessFunction, description
  gist:PlannedEvent  → schema:Action
    props: agent, object, target, actionStatus, startTime, endTime,
           result, instrument
  gist:PhysicalThing → schema:Product
    props: name, identifier, description, version, inLanguage,
           isAccessoryOrSparePartFor
  gist:Magnitude     → schema:QuantitativeValue
    props: value, unitCode, unitText, minValue, maxValue, valueReference
  gist:Category      → schema:DefinedTerm
    props: name, description, termCode, inDefinedTermSet, sameAs
  gist:Agent (person)     → schema:Person
    props: name, jobTitle, description, email, knowsAbout
  gist:Agent (org/system) → schema:Organization
    props: name, description, member, parentOrganization, contactPoint
  gist:Event         → schema:Event
    props: name, startDate, endDate, eventStatus, location, organizer,
           description

  Agent disambiguation: spaCy entity label from Step 1 determines which
  schema:Agent sub-type to route to. PERSON → schema:Person,
  ORG → schema:Organization. Zero extra LLM cost.
  → Gives precise semantic "shape" for pattern matching AND for Step 3b
    ↓
[Step 3b — Relation Extraction: Semantic Path (Ollama with Type Context)]
  Runs AFTER Step 3 — has full gist class + schema.org type for each entity.
  Shape-First Principle (Named IP Claim): classify the ontological type before
  doing semantic work at any level. Applied here: Ollama receives typed entities,
  not raw text — knowing the shape (Product→Product) narrows the relation space.
  Triggered when: >1 entity AND Step 1b found no relation.

  Ollama prompt includes typed entities:
    Entity A: Kùzu (gist:PhysicalThing / schema:Product)
    Entity B: ChromaDB (gist:PhysicalThing / schema:Product)
    → "What is the relationship in: 'We chose Kùzu over ChromaDB'?"
  Forced output: { head, relation_type, tail, confidence } or null.
  Must choose from 9 named types — never forced to produce a relation.

  Handles types Step 1b cannot extract from syntax:
    CHOSEN_OVER   — requires decision context
    IMPLEMENTS    — requires type context
    EXTENDS       — domain-dependent meaning
    ALTERNATIVE_TO — requires situational context

  Why type context helps: asking about a Product→Demand relation is far
  more constrained than asking about raw text entities.
  Results written to Kùzu alongside CO_OCCURS_WITH edges.
    ↓
[Step 4 — Heuristic Pattern Matching + Selective Attention
           (Representativeness Heuristic + Cocktail Party Effect)]
  The Brain is always-on (adapter forwards all user + assistant turns passively).
  Step 4's confidence gate IS the selective attention filter — like hearing your
  name cut through background noise at a party. Most conversation is background;
  specific patterns cause the Brain's "senses" to fire:

  Decision sense:     "we decided", "we chose", past-tense resolution language
  Constraint sense:   "never", "must", "always", "forbidden", directive language
  Plan sense:         "we will", "next step", future-tense action language
  Entity sense:       known graph entity mentioned by name or near-match embedding
  Contradiction sense: Step 5 retrieval finds 0.75-0.92 similarity to existing node

  Cocktail Party Effect — Named Biomimetic Principle (IP Claim):
  Push-based selective attention, not pull-based LLM-instructed recall.
  The LLM does not decide what to remember. The Brain decides.

  Confidence gate (NOT a blocking gate — all above noise floor enter graph):
    < 60%   → noise, vector-log only, no structural node (background filtered out)
    60–90%  → store with confidence_low=true, low pathway_strength (low attention)
    > 90%   → store with full confidence, proceed to Steps 5–7 (full attention fired)
  No human confirmation required. Uncertain nodes are tentative knowledge,
  continuously re-scored as context accumulates.
    ↓
[Step 5 — Dual-Scope Candidate Retrieval (Availability Heuristic)]
  Branch scope: same MainQuest + vector similarity (find local duplicates)
  Global scope: GlobalConstraint / GlobalPreference nodes (if no branch hit)
    ↓
[Step 6 — Constrained Contradiction Arbitration]
  Triggers ONLY in gray zone (0.75–0.92 similarity) or same artifact type
  LLM forced output schema: {classification, rationale_tokens, referenced_nodes}
  classification: additive | contradiction | uncertain
  "uncertain" → store with confidence_low=true, re-scored as context grows
    ↓
[Step 7 — Pathway Update (Recognition / Availability Heuristic)]
  Additive:      strength += 1 * log(1 + 1/days_since_last_access) on access
                 No duplicate node created.
  Contradiction: Create new node. Draw [DEPRECATED_BY] from old → new.
                 Old node preserved in audit trail, filtered from current_truth.
  After update:  Trigger event-driven confidence re-scoring on confidence_low
                 nodes within 1–2 hops of updated node.
  CO_OCCURS_WITH: Write (or increment) CO_OCCURS_WITH edges between all
                 concept pairs from the same message that cleared noise floor
                 (>60% confidence). strength initialized to
                 min(confidence_A, confidence_B). Background sweep updates
                 strength as endpoint confidences change over time.

[Synaptic Pruning — Named Biomimetic Principle]
  Modeled on neuroscience synaptic pruning ("use it or lose it") and the
  Ebbinghaus Forgetting Curve (exponential memory decay without recall).
  Two complementary forces on every artifact node:
    Strengthening: strength += 1 * log(1 + 1/days_since_last_access)  [on access]
    Decay:         strength *= decay_rate ^ days_since_last_access     [background sweep]
  decay_rate is configurable per node type in sidequests.toml (power user).
  Sensible defaults provided — GlobalConstraints decay over years,
  raw Messages decay in weeks.

  Archive mechanic (never delete — audit trail preserved):
    strength < archive_threshold (default 0.10) → archived=true
    Excluded from current_truth and active re-scoring.
    Edges preserved but soft-archived alongside weakest endpoint.
    Visible in Memory Control Panel as historical record.

  Resurrection:
    Background sweep compares all archived nodes against all active (non-archived)
    nodes in the graph — not recent messages.
    Active nodes are confirmed, embedded knowledge — higher quality signal.
    No time window parameter needed. Frequency = sweep_interval_seconds.
    embedding similarity > resurrection_threshold (default 0.85, same as System 1)
    → un-archived, strength reset to resurrection_threshold (not 1.0).
    Node was dormant — earns full strength back through access (Step 7).

[Background Sweep — Single Pass, Three Jobs]
  Runs every sweep_interval_seconds (default 300s) on Brain Daemon idle:
    1. Re-score all confidence_low nodes against current graph state
    2. Apply time-decay: strength *= decay_rate ^ days_since_last_access
    3. Archive nodes below archive_threshold; check archived for resurrection

[Confidence Re-Scoring — Living Property]
  confidence is dynamic — re-evaluated continuously, not set once at Step 4.
  Event-driven: after every Step 7 update, re-score confidence_low nodes 1–2 hops out.
  Background sweep: catches orphaned tentative nodes not reached by recent events.
  Auto-promote: confidence_low node crosses 90% → confidence_low cleared.
  current_truth ranks results by pathway_strength × confidence.
```

---

## Kùzu Graph Schema

The graph is a first-class citizen. Any entity with identity, relationships, or query value is a node — not a property on another node.

### Concept Node
General-purpose entity extracted by Step 1 NER. All named relationships (REQUIRES, ENABLES, etc.) connect `Concept` nodes. Tools, people, products, events, and quantities referenced in relationships land here. `pathway_strength` initialized to `max(confidence, 0.50)` at creation.

| Field | Type | Notes |
|-------|------|-------|
| `concept_id` | STRING | PK |
| `text_raw` | STRING | |
| `embedding` | FLOAT[384] | |
| `embedding_model` | STRING | |
| `embedding_dim` | INT | |
| `gist_class` | STRING | set by Step 2 |
| `schema_org_type` | STRING | set by Step 3 |
| `confidence` | FLOAT | |
| `confidence_low` | BOOLEAN | |
| `pathway_strength` | FLOAT | initialized to max(confidence, 0.50) |
| `archived` | BOOLEAN | |
| `created_at` | TIMESTAMP | |

When Step 4 classifies a Concept at >90% confidence, a specific artifact node (Decision, Constraint, etc.) is created and linked via `(Concept)-[REIFIED_AS]->(artifact)`. Named relationships between Concepts are preserved alongside the reified artifact.

### Core Artifact Nodes
All require: `text_raw (STRING)`, `embedding FLOAT[384]`, `embedding_model (STRING)`, `embedding_dim (INT)`, `confidence (FLOAT)`, `confidence_low (BOOLEAN)`

| Node | Purpose |
|------|---------|
| `MainQuest` | High-level user goal (auto-created from git anchor). Fields: `status STRING` (active\|completed\|archived), `completed_at TIMESTAMP`, `purpose STRING` |
| `SideQuest` | Sub-branch / tangent of a MainQuest. Same status fields as MainQuest. |
| `Decision` | Resolved choice made during a quest |
| `Constraint` | A rule or limit that governs a quest |
| `Requirement` | A stated need or acceptance condition |
| `ActionItem` | A concrete next step |
| `GlobalConstraint` | Workspace-level constraint (cross-quest) |
| `GlobalPreference` | Workspace-level preference (cross-quest) |
| `Document` | Physical file instance (`document_id`, `location_uri`, `content_hash`, `last_modified_at`, `mime_type`) |
| `Message` | Raw chat transcript chunk (`byte_start`, `byte_end`) |
| `DocumentExtract` | Parsed document chunk with line range provenance |

### Session & Infrastructure Nodes
No embedding required. Track where and how work happens across LLMs and machines.

| Node | Fields |
|------|--------|
| `Session` | `session_id (STRING)`, `started_at (TIMESTAMP)`, `last_active_at (TIMESTAMP)`, `onboarded (BOOLEAN)`, `purpose (STRING)` |
| `LLMProvider` | `provider_id (STRING)`, `provider_name (STRING)`, `model_name (STRING)`, `is_local (BOOLEAN)`, `context_window (INT)` |
| `Workspace` | `workspace_id (STRING)`, `path (STRING)`, `os (STRING)`, `hostname (STRING)` |

### Ontology Nodes
The gist → schema.org routing table lives in the graph, not in code.

| Node | Fields |
|------|--------|
| `GistClass` | `name (STRING)`, `centroid (FLOAT[384])` — mean embedding of seed + System 2 resolved examples; computed at M1 init, updated on each System 2 resolution |
| `SchemaOrgType` | `name (STRING)`, `properties (STRING[])` — the relevant property subset for this type |

### Label Nodes (SKOS-Inspired — Graph-Native)
Every label is a first-class node with its own embedding. `current_truth` searches concept embeddings AND all attached label embeddings — a concept is findable via any phrasing ever associated with it.

| Node | Fields |
|------|--------|
| `Label` | `label_id (STRING)`, `text (STRING)`, `embedding (FLOAT[384])`, `language (STRING)` default "en", `label_type (STRING)` — preferred\|alternative\|hidden, `confidence (FLOAT)`, `source (STRING)` — user\|system\|LLM, `created_at (TIMESTAMP)` |

| label_type | SKOS Term | Meaning |
|-----------|----------|---------|
| `preferred` | `skos:prefLabel` | Canonical name — one per language per concept |
| `alternative` | `skos:altLabel` | Synonyms, paraphrases, abbreviations — accumulate through use |
| `hidden` | `skos:hiddenLabel` | Search-only terms not shown in UI (misspellings, deprecated names) |

### Audit Nodes (embeddings optional)
| Node | Fields |
|------|--------|
| `MergeEvent` | `pre_pathway_strength`, `delta_pathway_strength`, `alias_added[]`, `metadata_patch` |

### Relationships
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

# Ontology routing table (graph-native — core IP)
(GistClass)-[ROUTES_TO]->(SchemaOrgType)

# SKOS-inspired labels (graph-native, each with own embedding)
(ArtifactNode)-[HAS_PREF_LABEL]->(Label)    # one per language
(ArtifactNode)-[HAS_ALT_LABEL]->(Label)     # many, accumulate through use (Hebbian)
(ArtifactNode)-[HAS_HIDDEN_LABEL]->(Label)  # search only, never displayed

# Concept promotion (Step 4 classifies at >90% → artifact node created)
(Concept)-[REIFIED_AS]->(Decision | Constraint | Requirement | ActionItem)

# Hebbian implicit layer — always preserved, never deleted
(Concept)-[CO_OCCURS_WITH {count INT, strength FLOAT}]->(Concept)

# Named semantic layer — Concept→Concept, preserved through reification
# inferred_by: "system" (Step 1b verb pattern) | "LLM" (Step 3b Ollama) | "user"
# Step 1b fast-path types (verb patterns, no LLM):
(Concept)-[REQUIRES    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[ENABLES     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[REPLACES    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[CONTRADICTS {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[PART_OF     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
# Step 3b semantic-path types (Ollama with gist+schema.org type context):
(Concept)-[CHOSEN_OVER    {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[IMPLEMENTS     {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[EXTENDS        {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
(Concept)-[ALTERNATIVE_TO {confidence FLOAT, inferred_by STRING, inferred_at TIMESTAMP}]->(Concept)
```

### Hebbian Relationship Promotion — Three Triggers

When a `CO_OCCURS_WITH` edge is ready to become a named semantic relationship, a named edge is created **alongside** it. The implicit layer is preserved permanently as Hebbian evidence.

**Trigger 1 — Loop explicit extraction** (`inferred_by: "system"` or `"LLM"`, confidence 0.85+)
A message explicitly states the relationship in natural language. Step 1b (verb pattern match) or Step 3b (Ollama with type context) extracts the named triple directly. Most reliable — grounded in what was actually said. `inferred_by: "system"` for verb-pattern matches; `inferred_by: "LLM"` for Step 3b Ollama extractions.

**Trigger 2 — LLM auto-promotion** (`inferred_by: "LLM"`, confidence 0.70–0.85)
When `co_occurrence_count` crosses a configurable threshold (default: 10), Step 6 arbitration presents the co-occurrence evidence to the LLM and asks it to name the relationship. The count is the evidence; the LLM provides the label. Medium confidence — inferred, not stated.

**Trigger 3 — User promotion via Memory Control Panel** (`inferred_by: "user"`, confidence 1.0)
User sees a strong `CO_OCCURS_WITH` edge in the graph view and explicitly names it. Highest trust — human-curated. User can also edit or demote any named edge here.

---

## Pre-Build Design Decisions

### IPC Protocol (Adapter ↔ Brain Daemon)

**Decision:** JSON-RPC 2.0 over Unix domain socket — same wire format as MCP itself.

Adapters are transparent proxies: read JSON-RPC from LLM stdio → forward to Brain Daemon Unix socket → return response. Zero translation layer. No custom protocol to maintain.

**Implementation:** Python `asyncio` + built-in `json`. No external JSON-RPC library.

```
LLM → [stdio, JSON-RPC 2.0] → Adapter → [Unix socket, JSON-RPC 2.0] → Brain Daemon → Kùzu
```

---

### MCP Tool Schemas (M2 LLM-facing tools)

**Ingestion model:** User turns captured by Claude Code `UserPromptSubmit` hook (zero LLM involvement). Assistant turns via `notify_turn` MCP tool — LLM as courier only, never decides what to remember. M8 adapters use `notify_turn` for both turn types.

M2 LLM-facing tools: `notify_turn` + `current_truth`.

**`current_truth`** — call before answering architecture or past-decision questions
```json
{
  "name": "current_truth",
  "description": "Retrieve relevant memory before answering architecture or past decision questions.",
  "inputSchema": {
    "type": "object",
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
Response: `{ results: [{ node_id, node_type, text_raw, pathway_strength, similarity, session: { llm_model, started_at } }] }`

Remaining tools defined at their respective milestones — signatures sketched here for IPC interface planning:

**`branch_quest`** (M5) — `{ name: string, description?: string }` → `{ quest_id, quest_name, branch }`
**`complete_quest`** (M5) — `{ quest_id: string }` → `{ status: "completed", completed_at }`
**`diff_since`** (M5) — `{ since_session_id: string, scope?: "branch"|"global"|"both" }` → `{ created: [...], updated: [...], deprecated: [...] }`
**`get_open_loops`** (M5) — `{ scope?: "branch"|"global"|"both", limit?: int }` → `{ nodes: [...] }`

---

### LLM Adapter Instruction Model (Always-On Fragment + Onboarding Skill)

**Decision:** Two-layer model. Every active-mode adapter injects both layers.

**Layer 1 — Always-On System Prompt Fragment** (~28 tokens, every session):
```
[SideQuest | Quest: {quest_name} | Branch: {branch}]
The Brain is capturing decisions and constraints automatically.
Before answering about past choices or architecture → current_truth
Exploring a tangent? → offer branch_quest
```
- No ingest_message trigger — passive ingestion is automatic, LLM doesn't control it
- "offer branch_quest" not "call" — branching requires user confirmation
- `quest_name` and `branch` injected at runtime from active MainQuest/SideQuest node

**Layer 2 — Onboarding Skill** (once per LLM + Quest combination):
```
SideQuest's Brain is always listening — it automatically captures decisions,
constraints, and plans from your conversation through selective attention.
You don't need to flag things manually.

Two things you control:
- current_truth: call before answering any architecture or past-decision
  question. The Brain's graph is more reliable than your context window
  for resolved choices.
- branch_quest: offer (don't call unilaterally) when the conversation
  shifts to a distinct tangent worth tracking separately.

If current_truth returns a confidence_low result, flag the uncertainty
to the user — don't present tentative memory as confirmed fact.
```

Tracked via `Session.onboarded BOOLEAN`. First session for an LLM+Quest pair → full onboarding injected, `onboarded` set to `true`. All subsequent sessions → Layer 1 fragment only.

---

### Memory Audit CLI (`sidequests review`)

**Decision:** System operates fully autonomously — no human confirmation required for uncertain nodes. `sidequests review` exists as an optional audit tool, not a required gate.

`sidequests review` queries the graph for `confidence_low` nodes and displays them with context. User can promote, demote, or edit at any time. M7 (Memory Control Panel) replaces this CLI with a richer web UI reading the same graph data.

---

### Installation Story

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
3. Registers MCP adapter in the standard config file for each target:
   - **Claude Code:** `.mcp.json` in project root (or via `claude mcp add` CLI)
   - **Claude desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **ChatGPT desktop / Codex / Gemini CLI:** their respective MCP config files
4. Starts Brain Daemon + smoke test (Ollama ping + Kùzu schema init + `tools/list` round-trip)

---

## Quest Lifecycle

| Phase | Mechanism |
|-------|-----------|
| MainQuest creation | Auto: deterministic hash of `git_repo_root + git_branch` |
| SideQuest creation | Manual: user calls `branch_quest` MCP tool |
| Quest completion | `complete_quest` tool: sets `status = "completed"`, `completed_at = now()`. Completed quests excluded from `current_truth` branch scope; included in M8 analogical search. Auto-suggest after `auto_complete_days` inactivity. |
| SideQuest → MainQuest promotion | Via Memory Control Panel UI |
| Future goal | Auto-detect SideQuest branching via topic divergence embedding |

### Purpose / Intent Capture

The Brain infers purpose automatically. User confirmation is optional (power user feature), never required.

**Inference trigger:** First confirmed (>90%) artifact stored by the Loop in a new Quest or Session.
Ollama synthesizes a 1–2 sentence purpose from early messages + first confirmed artifact.

**Two scopes:**
| Scope | Stored On | Updated When |
|-------|----------|-------------|
| Session | `Session.purpose` | Set once per session on first confirmed artifact. Not updated mid-session. |
| Quest | `MainQuest.purpose` / `SideQuest.purpose` | Set from first session. Re-inferred if later sessions show significant topic drift. |

**Confidence:** `confidence_low=true` initially — inferred, not confirmed. Quest proceeds regardless.

**User edit/confirm surface:**
- M7: Memory Control Panel shows tentative purpose with confirm/edit option
- Pre-M7: `sidequests review` CLI surfaces tentative purpose candidates
- User edits stored with `inferred_by: "user"`, confidence 1.0 (trusted)

---

## Module File Structure

```
sidequests-brain/
├── sidequests.toml
├── brain_daemon.py              # Main process: IPC server + Loop orchestration
├── mcp_engine/
│   ├── schema.py                # Kùzu schema initialization
│   ├── tools.py                 # MCP tool surface
│   ├── loop/
│   │   ├── step1_ner.py         # spaCy NER
│   │   ├── step1b_relations.py  # Relation extraction: universal verb patterns (no LLM)
│   │   ├── step2_gist.py        # gist hybrid classifier (System 1 + System 2)
│   │   ├── step3_schema_org.py  # schema.org routing + mapping table (core IP)
│   │   ├── step3b_relations.py  # Relation extraction: Ollama with gist+schema.org type context
│   │   ├── step4_pattern.py     # Representativeness heuristic + confidence gating
│   │   ├── step5_retrieval.py   # Dual-scope retrieval
│   │   ├── step6_arbitration.py # Constrained contradiction arbitration
│   │   └── step7_pathway.py     # Pathway update + DEPRECATED_BY + MergeEvent
│   ├── llm/
│   │   ├── provider.py          # OpenAI-SDK-compatible abstraction layer
│   │   └── providers/
│   │       ├── ollama.py
│   │       ├── openai.py
│   │       ├── anthropic.py
│   │       └── google.py
│   └── graph/
│       ├── kuzu_client.py       # Kùzu connection + Cypher execution
│       └── embeddings.py        # sentence-transformers wrapper
├── adapters/
│   ├── claude_code/
│   │   └── adapter.py           # STDIO MCP adapter → IPC socket proxy
│   └── codex/
│       └── adapter.py
├── web/
│   ├── server.py                # FastAPI, bound to 127.0.0.1 only
│   └── static/                  # Graph view, soft-lock UI, merge rollback, Ledger export
└── tests/
    ├── test_loop.py
    ├── test_retrieval.py
    └── test_adapters.py
```

---

## Kùzu Implementation Notes

| Topic | Decision |
|-------|----------|
| **Version** | Pin `kuzu==0.11.3`. kuzu-db archived October 2025 — last stable release. Watch RyuGraph fork for migration path. `kuzu_client.py` abstraction layer isolates all Kùzu calls. |
| **Portability** | All Kùzu-specific syntax lives exclusively in `kuzu_client.py`. Loop steps, tools, and the daemon never import `kuzu` directly. Migration to Neo4j or another provider = rewrite `kuzu_client.py` only. The data model (nodes, relationships, properties) is standard property graph — fully portable. |
| **Concurrency** | Brain Daemon holds the sole `READ_WRITE` connection. Single `asyncio.Lock` wraps all write operations. MCP adapters use `kuzu.Database(path, read_only=True)` for any direct reads — no write contention. |
| **Embedding type** | HNSW indexes require fixed-dimension arrays: `FLOAT[384]` (not `FLOAT[]`). One HNSW index per node table, created at M1 schema init. |
| **Filtered vector search** | Use projected graphs to prefilter before HNSW scan (not postfilter): `CALL project_graph('active_decisions', 'Decision', {'Decision': 'n.archived = false AND n.confidence_low = false'})` then `CALL QUERY_VECTOR_INDEX(...)`. |
| **Multi-table search** | No cross-table HNSW index. `current_truth` uses `UNION ALL` across per-table `QUERY_VECTOR_INDEX` calls in a single Cypher query, sorted by score with `LIMIT`. |
| **Relationship typing** | Named semantic relationships: `FROM Concept TO Concept` only. `REIFIED_AS` uses multi-FROM/TO: `CREATE REL TABLE REIFIED_AS (FROM Concept TO Decision, FROM Concept TO Constraint, FROM Concept TO Requirement, FROM Concept TO ActionItem)`. |

---

## Build Milestones

### M1 — Foundation
- Kùzu schema init (all nodes + relationships). **Pin `kuzu==0.11.3`** — design `kuzu_client.py` as sole Kùzu abstraction layer (all Kùzu-specific syntax here only — loop steps never import `kuzu` directly). Language scope: English only.
- **Centroid bootstrap** (required before M3): parse `InvertorsDocs/GistSeedExamples.md`, embed all 105 sentences with `all-MiniLM-L6-v2`, mean-pool per class (15 examples each), store result as `GistClass.centroid FLOAT[384]`. Runs at schema init.
- `sidequests.toml` loading — includes `[nlp] spacy_model = "en_core_web_md"`
- LLM provider abstraction + Ollama connection smoke test
- Brain Daemon IPC server (Unix domain socket)
- MCP server skeleton (tool registration, no logic)
- spaCy model auto-download: `python -m spacy download en_core_web_md` (run by `sidequests setup`)

### M2 — Minimum Viable Brain
- Passive ingestion — two-part capture:
  - **User turns:** `UserPromptSubmit` Claude Code hook (shell script → Brain socket, zero LLM involvement). Hook config written by `sidequests setup`.
  - **Assistant turns:** `notify_turn` MCP tool (LLM calls automatically per system prompt, acts as courier only). Response always `{ "status": "queued" }` — never blocks.
  - For M8 adapters: `notify_turn` handles both user and assistant turns.
- Internal ingestion function: raw vector write, no Loop processing.
- `current_truth` tool: basic vector similarity retrieval.
- Claude Code adapter fully wired (hook config + MCP server).
- Error/degraded mode: Scenario A (daemon down → OFFLINE fragment + local queue), Scenario B (Ollama down → confidence_low storage + background sweep retry)

### M3 — Gated Consolidation Loop (Steps 1–4 + Step 3b)
- Step 1: spaCy NER integration
- Step 1b: Universal verb pattern relation extraction — 5 types (REQUIRES, ENABLES, REPLACES, CONTRADICTS, PART_OF), ~20 lemmas. Zero LLM cost. Domain-agnostic.
- Step 2: gist hybrid classifier — centroids seeded from `InvertorsDocs/GistSeedExamples.md` (105 examples, 15 per class). Ollama System 2 fallback for 0.60–0.85 range.
- Step 3: schema.org sub-graph routing (GistClass→SchemaOrgType edges already seeded in graph at M1 init)
- Step 3b: Ollama relation extraction with type context — 4 remaining types (CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO). Triggered: >1 entity AND Step 1b found nothing. Prompt includes gist class + schema.org type per entity.
- Step 4: heuristic pattern matching + Cocktail Party selective attention gating. No blocking gate — confidence_low nodes stored and re-scored continuously.
- `sidequests.toml` additions: `[hebbian] co_occurrence_threshold = 10`

### M4 — Deduplication + Pathway Strengthening (Steps 5–7)
- Step 5: dual-scope candidate retrieval (branch + global)
- Step 6: constrained contradiction arbitration (gray-zone LLM only)
- Step 7: pathway update (strengthen vs. create) + DEPRECATED_BY edges + reversible MergeEvent with delta pointers

### M5 — Quest Lifecycle
- MainQuest auto-creation from git repo root hash + branch
- `branch_quest` tool for manual SideQuest creation
- `complete_quest` tool: sets `status = "completed"` + `completed_at`, excludes from active `current_truth`
- Auto-suggest completion after `auto_complete_days` days of inactivity (configurable)
- Graph-Native RAG read flow: embed prompt → vector search → graph traversal → context injection

### M6 — Open Brain (Document Ingestion)
- Document node creation (URI, hash, metadata)
- Semantic paragraph chunking → DocumentExtract nodes
- Provenance tracking (location_uri + line start/end)
- Full Loop processing of DocumentExtracts

### M7 — Memory Control Panel
- FastAPI server (127.0.0.1 only, no auth required for local)
- Graph visualization (D3.js or Cytoscape.js)
- Soft-lock confirmation UI (60–90% candidates queue)
- MergeEvent rollback UI (delta display + one-click revert)
- Constraint Ledger export (Markdown + JSON)

### M8 — Additional Adapters + Cross-Quest Analogical Reasoning
- Claude desktop app STDIO adapter (MCP supported natively)
- Codex STDIO adapter
- ChatGPT desktop app STDIO adapter (MCP supported natively)
- Gemini CLI STDIO adapter (MCP supported natively)
- Broadened RAG: when task pattern similarity detected, search across historical MainQuests
- Surface high-strength Decision/Constraint artifacts from past quests into current context

---

## Security Constraints (Non-Negotiable)

- STDIO transport mandatory; no TCP/HTTP listening ports on the MCP interface
- Brain Daemon IPC uses Unix domain sockets (macOS/Linux) or named pipes (Windows)
- Memory Control Panel binds strictly to `127.0.0.1`, never `0.0.0.0`
- All file read/write confined to project directory via `realpath()` canonicalization
- Block `..` path escapes and symlink traversal
- Only allowlisted file extensions (`.db`, `.log`) may be written by the daemon

---

## Acceptance Criteria (Phase 0 Complete When All Pass)

1. **Multi-Agent State Share:** Decision established in Claude Code is immediately visible and respected by a subsequent Codex prompt.
2. **Temporal Deprecation:** Deprecating a Constraint in Codex instantly updates the `diff_since` view when queried by Claude Code.
3. **Deterministic Rollback:** Deleting a MergeEvent via the UI immediately reverts `current_truth` for all connected adapters.
4. **Bridge Test:** Constraint created from a chat message displays raw text + provenance in UI; a paraphrased query retrieves it via embedding similarity.
5. **Open Brain Test:** Ingesting a local markdown document creates a `Document` node and `DocumentExtract` children; a Constraint extracted from that doc appears in `current_truth` with exact `location_uri` and line ranges.
6. **Cross-Project Analogical Test:** Starting a new MainQuest (e.g., "Move demo to AWS") surfaces a relevant `Constraint` (e.g., "Use IAM roles, not static keys") established in a distinct MainQuest completed months prior.
