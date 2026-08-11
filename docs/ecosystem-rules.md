# HippoCampy — Ecosystem Rules

Status: active draft

## Purpose

This document is the source of truth for the ecosystem architecture of the HippoCampy platform. It defines stable layers, ownership boundaries, and rules that every coding agent (Claude, Gemini, Codex) and human contributor must follow.

Use it to answer:

- what the major layers are
- what belongs where
- how new capabilities should be added
- how to evaluate whether a proposed change fits the ecosystem

Companion references:

- Architecture specification: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- Codebase anatomy navigation guide: [docs/codebase-anatomy.md](codebase-anatomy.md)
- ARC harness ownership rules: [docs/arc-harness-rules.md](arc-harness-rules.md)
- Tool catalog (MCP tool contracts): [docs/tool-catalog.md](tool-catalog.md)
- Backlog rules: [backlog/BacklogRules.md](../backlog/BacklogRules.md)

---

## Ecosystem Model

This ecosystem is a local AI agent platform with a small set of stable layers, one shared knowledge layer, and cross-cutting guardrails.

### Stable Layers

1. **Agent Orchestration & Control Plane** — Durable workflow state, phase transitions, retries, checkpoints, gates, run export, and event coordination.
2. **Agent Runtime & Harness** — Specialized agents that retrieve, reason, plan, and propose actions using reusable instructions and governed access to tools and data.
3. **Shared Knowledge Assets** — Shared reusable prompts, skills, evals, examples, evidence, templates, and runtime pointers that feed the agent harness.
4. **Deterministic Tools & Services** — Reusable compute, validators, serializers, and bounded tool contracts exposed through stable interfaces.
5. **Data Products & Memory** — Governed memory surfaces and durable knowledge graph exposed through versioned MCP tool contracts.
6. **Trusted Systems** — External systems of record and environment authorities that remain canonical for governed state.

**Cross-cutting:** **Observability / Evaluation / Security** — Audit, telemetry, write traces, ledger tracking, and evaluation controls spanning every layer.

**Future layer (not active):** **Experience & Interaction** — Thin channels for human input, approvals, and supervision. Not needed while the system is benchmark-driven.

### Important boundary: Campy and ARC are separate

This is the most critical architectural rule in this project.

**Campy code and ARC code must remain separate.** They communicate only through the `BrainClientProtocol` interface and MCP tool contracts. No ARC file may import from `campy/brain/`. No Campy file may import from `agents/` or `benchmarks/`.

---

## Current Layer Mapping

| Layer | Current Components | Directory |
|---|---|---|
| Agent Orchestration & Control Plane | DurableARCRunner, CheckpointManager | `agents/arc3/runner.py`, `agents/arc3/checkpoint.py` |
| Agent Runtime & Harness | ARCOrchestrator, HypothesisManager, SolveEngine | `agents/arc3/orchestrator.py`, `agents/arc3/hypothesis.py`, `agents/arc3/solver.py` |
| Shared Knowledge Assets | API knowledge cache, prompt strategy, state-to-text prompts | `agents/arc3/api_knowledge.py`, `benchmarks/arc3/prompts/`, `benchmarks/arc3/PROMPT_STRATEGY.md` |
| Deterministic Tools & Services | StateSerializer, NER pipeline, embedding compute, spaCy, harness baseline | `benchmarks/arc3/state_serializer.py`, `campy/brain/temporal_lobe/loop/`, `campy/brain/hippocampus/graph/embeddings.py` |
| Data Products & Memory | Brain Daemon, Gated Consolidation Loop, Kùzu graph, all MCP tools | `campy/brain/`, `brain_daemon.py` |
| Context Window Integration | File Bridge, Trigger Manifest, Associative Hooks, Anticipatory Engine | `campy/brain/thalamus/file_bridge.py`, `campy/brain/thalamus/trigger_manifest.py`, `campy/brain/temporal_lobe/loop/step4b_associative.py`, `adapters/claude_code/hooks/` |
| Trusted Systems | ARC-AGI-3 API (Environment) | External API; interface in `benchmarks/arc3/harness.py` |

### Interface Boundaries

| Boundary | Interface | Location |
|---|---|---|
| ARC ↔ Campy | `BrainClientProtocol` | `benchmarks/arc3/adapter.py` |
| ARC ↔ Environment | `ARC3Harness._execute_action()`, `_initial_frame()` | `benchmarks/arc3/harness.py` |
| Agent ↔ Orchestrator | `ARCOrchestrator` public methods | `agents/arc3/orchestrator.py` |
| Adapter ↔ Brain Daemon | MCP STDIO / Unix domain socket | `adapters/*/adapter.py` |
| Hook Scripts ↔ Trigger Manifest | JSON file at `~/.campy/triggers/manifest.json` | `adapters/claude_code/hooks/*.sh` reads, `campy/brain/thalamus/trigger_manifest.py` writes |
| File Bridge ↔ Project Dir | Generated files (`CONTEXT.md`, ADRs) | `campy/brain/thalamus/file_bridge.py` writes to project `.campy/` dirs |

---

## Agent Orchestration & Control Plane

**Definition** — Durable workflow and coordination layer for run state, phase transitions, retries, checkpoints, gates, run export, and event handling. This is the control plane. It coordinates work; it does not reason or decide actions.

### Current owner

`DurableARCRunner` + `CheckpointManager` in `agents/arc3/runner.py` and `agents/arc3/checkpoint.py`.

### Rules

Agent Orchestration & Control Plane owns:

- run lifecycle (start, step, retry, export)
- phase transitions (bootstrap → hypothesize → solve → act → ingest → evaluate → finalization)
- checkpoint persistence and crash recovery
- retry policy and bounded retry logic
- gate enforcement (entity gate, observation completeness)
- run ID and session ID generation
- progress snapshots and run export
- write trace collection and aggregation
- Campy ledger aggregation
- orchestration report generation

Agent Orchestration & Control Plane does not own:

- reasoning or action selection
- prompt construction
- hypothesis generation
- entity classification
- memory or retrieval logic
- environment state transitions

### Control-plane rule

The control plane orchestrates. It does not become the dumping ground for reasoning logic, prompt assembly, or memory operations.

### Phase transition rule

Only the control plane decides and stamps the active phase. Agents and tools may produce events within a phase, but they do not redefine phase semantics.

### Gate rule

Gates are enforcement checks that the control plane runs before allowing a phase transition. A gate may:

- validate that prerequisite data exists (e.g., entity map populated)
- retry a bounded number of times if the check fails
- degrade gracefully and log the reason if retries are exhausted

A gate must not:

- crash the run
- perform unbounded retries
- make reasoning decisions

### Eventing rule

Events are a coordination mechanism, not a business-logic layer.

Use events to:

- decouple phase activities from downstream consumers
- notify that something happened (step completed, entity discovered, outcome reported)
- trigger write trace recording

Do not use events to:

- hide reasoning logic
- replace phase state
- bypass the control plane

---

## Agent Runtime & Harness

**Definition** — Execution environment for specialized agents that retrieve, reason, plan, use tools, and propose actions. This is the agent harness: the runtime shell where agent reasoning, hypothesis generation, solve strategy, prompt assembly, and tool invocation come together.

### Current owner

`ARCOrchestrator` + `HypothesisManager` + `SolveEngine` in `agents/arc3/`.

### Rules

Agent Runtime & Harness owns:

- reasoning and decision support
- hypothesis generation and state graph maintenance
- solve strategy (archetype classification, object role mapping, victory hypothesis)
- prompt block construction and rendering (PromptPacket, ContentBlock)
- action proposal and guard logic (mental sandbox, decision guard)
- entity discovery and classification
- memory query construction and retrieval trigger logic

Agent Runtime & Harness does not own:

- run lifecycle or phase transitions (belongs to Control Plane)
- memory storage or graph operations (belongs to Data Products & Memory)
- environment state transitions (belongs to Trusted Systems)
- durable workflow state (belongs to Control Plane)

### Agent definition

An agent is not only prompts and skills. An agent =

- a runtime shell in Agent Runtime & Harness
- reusable prompts/skills/knowledge loaded from Shared Knowledge Assets
- tool access through `BrainClientProtocol` to Data Products & Memory
- environment access through the harness to Trusted Systems

In practice:

- Agent Runtime & Harness defines **how the agent runs** (perceive → hypothesize → solve → act → evaluate)
- Shared Knowledge Assets defines **what reusable instructions and supporting material it runs with**

### Harness boundary

The agent harness is where planning, retrieval-trigger logic, tool selection, critique, and proposal generation live.

It is not:

- a memory system (that's Campy)
- the durable workflow state store (that's the Control Plane)
- the environment authority (that's the ARC API)

### Agent scaling rule

When new agents are added beyond ARC, each agent:

- gets its own directory under `agents/<agent_name>/`
- uses its own orchestrator and reasoning logic
- accesses Campy through `BrainClientProtocol` (same interface)
- accesses shared assets from the shared knowledge layer
- does NOT duplicate Campy tools, adapters, or memory logic

---

## Shared Knowledge Assets

**Definition** — Shared reusable prompts, skills, evals, examples, evidence, templates, and runtime pointers that feed the agent harness and keep reusable knowledge from getting trapped inside one agent or one conversation.

### Current contents

| Asset Type | Current Location | Purpose |
|---|---|---|
| API knowledge cache | `agents/arc3/api_knowledge.py` | Pre-computed ARC API contract chunks + entity cache |
| Prompt strategy | `benchmarks/arc3/PROMPT_STRATEGY.md` | Prompt construction rules and compaction strategy |
| State-to-text prompts | `benchmarks/arc3/prompts/state_to_text.md` | Serialization format reference |
| Rules checklist | `benchmarks/arc3/rules_checklist.md` | ARC rules and checklist |

### Rules

Shared Knowledge Assets exists so reusable knowledge does not get trapped in one agent's code or one conversation.

It should hold reusable:

- prompts (behavioral instructions for agents)
- skills (reusable operating recipes)
- evals (evaluation criteria and scoring rubrics)
- examples (reference inputs/outputs)
- evidence (prior art, learned lessons)
- templates (output format templates)
- runtime pointers (knowledge cache, lookup tables)

### Rule

If something is reusable across agents or efforts, it should move into Shared Knowledge Assets rather than being hardcoded inside one agent's orchestrator.

### Important distinction

Shared Knowledge Assets are **not**:

- per-run workflow state (belongs to Control Plane)
- durable memory or graph data (belongs to Data Products & Memory)
- runtime reasoning state (belongs to Agent Runtime)

### Skills vs prompts vs tools

- **Skill** = reusable operating recipe for agents (how to approach a class of work)
- **Prompt** = behavioral instructions for a specific agent or model interaction
- **Tool** = executable capability behind MCP or `BrainClientProtocol`
- **Workflow** = orchestrated sequence of tools/agents/state transitions (owned by Control Plane)

These are complementary, not interchangeable.

### Future direction

As agents scale beyond ARC:

- Move reusable API knowledge, skill definitions, and prompt templates into a shared `knowledge/` or `skills/` directory
- Make skills discoverable by name with a `SKILL.md` entry point
- Keep agent-specific prompts in the agent's own directory

---

## Deterministic Tools & Services

**Definition** — Reusable compute, validators, serializers, and bounded tool contracts for shared deterministic work. This is where parsing, validation, serialization, NER, embedding computation, and other bounded non-probabilistic work lives.

### Current components

| Component | Location | Purpose |
|---|---|---|
| StateSerializerForARC | `benchmarks/arc3/state_serializer.py` | Grid-to-text serialization |
| NER / Zoning pipeline | `campy/brain/temporal_lobe/loop/step1_ner.py` | spaCy entity extraction |
| Embedding computation | `campy/brain/hippocampus/graph/embeddings.py` | sentence-transformers vectors |
| gist classifier | `campy/brain/temporal_lobe/loop/step2_gist.py` | Ontological classification |
| Relation extraction | `campy/brain/temporal_lobe/loop/step1b_relations.py`, `step3b_relations.py` | Verb pattern + LLM relation extraction |
| Anomaly detection | `campy/brain/temporal_lobe/loop/anomaly_detection.py` | Behavioral integrity monitoring |

### Rules

Deterministic Tools & Services owns:

- stateless compute
- parsing and serialization
- NER and zoning
- embedding computation
- deterministic validators
- pattern matching and classification

Deterministic Tools & Services does not own:

- workflow state
- memory storage or graph operations
- reasoning or action selection
- phase transitions

### Tool contract rule

Prefer small, reusable, composable tools over giant black-box tools.

A good tool should:

- have a clear name and bounded purpose
- take explicit inputs and return explicit outputs
- be observable (write trace or log)
- delegate long-running coordination to the Control Plane
- delegate durable state to Data Products & Memory

A bad tool:

- hides a whole reasoning pipeline behind one vague action
- mutates memory without clear ownership
- bundles unrelated steps into one opaque action
- duplicates an existing tool with slightly different semantics

### Reuse rule

If a capability is useful across more than one agent or pipeline, it belongs in Deterministic Tools & Services rather than being trapped inside one agent's orchestrator.

### Campy internal tools

The Gated Consolidation Loop steps (NER, gist classification, relation extraction, pattern matching) are deterministic tools owned by Campy. They live inside `campy/brain/temporal_lobe/loop/` and are NOT exposed to agents. Agents interact with Campy only through MCP tool contracts.

---

## Data Products & Memory

**Definition** — Governed memory surfaces and durable knowledge graph exposed through versioned MCP tool contracts. This is HippoCampy: the Gated Consolidation Loop, Kùzu graph database, and all MCP tools.

### Current owner

Brain Daemon + `campy/brain/` + all MCP tool handlers.

### Boundary rule: Campy is a separate system

**Campy code and ARC code must remain separate.**

This means:

- No file in `agents/` may import from `campy/brain/`
- No file in `campy/brain/` may import from `agents/` or `benchmarks/`
- All communication between ARC and Campy goes through `BrainClientProtocol`
- `BrainClientProtocol` is defined in `benchmarks/arc3/adapter.py` — the only approved interface
- `LocalBrainClient` may import from `campy/brain/thalamus/tools/` because it IS the adapter implementation
- `NoOpBrainClient` and `LedgerBrainClient` are test/baseline implementations that do not touch `campy/brain/`

### Why this rule exists

Campy is designed to serve multiple agents, not just ARC. If ARC code reaches into Campy internals:

- adding a second agent requires duplicating that coupling
- Campy internal refactoring breaks ARC
- the MCP tool contracts become meaningless

### Rules

Data Products & Memory owns:

- the Kùzu graph database and all schema
- the Gated Consolidation Loop (Steps 1–7)
- all MCP tool contracts and handlers
- background sweep processes (decay, resurrection, re-scoring, Hebbian promotion)
- memory retrieval ranking and deduplication
- quest and plan lifecycle within the graph
- lesson extraction and outcome learning

Data Products & Memory does not own:

- workflow orchestration or phase transitions (belongs to Control Plane)
- reasoning or action selection (belongs to Agent Runtime)
- environment state transitions (belongs to Trusted Systems)
- prompt construction (belongs to Agent Runtime)

### MCP tool contract

All agent access to Campy must go through the MCP tool contract defined in [docs/tool-catalog.md](tool-catalog.md).

The 19 MCP tools are the stable API surface. Agents must not:

- bypass MCP tools to query Kùzu directly
- import Campy internal modules
- assume internal schema or implementation details

### Data / memory rule

This layer is the AI-ready memory foundation for the ecosystem.

Agents should retrieve durable context here through `BrainClientProtocol` and MCP tool contracts, not by inventing parallel memory systems or bypassing shared contracts.

### No shadow stores rule (CRITICAL)

**KuzuDB is the single source of truth for all persistent agent state. Do NOT create in-memory dicts, lists, or instance variables as parallel data stores.**

If a piece of data influences decisions across steps (roles, hypotheses, victory conditions, action facts, chunk history), it MUST be persisted to KuzuDB. In-memory variables may exist only as **read-through caches** that are populated from KuzuDB at the start of each step and flushed back after writes.

Violations of this rule:
- Storing `ObjectRole` in a Python dict while `GridEntity.inferred_role` exists in KuzuDB
- Storing `Hypothesis` objects in a Python dict while a `Hypothesis` node type exists in the schema
- Defining a node type in `schema.py` but never writing to it (ghost schema)
- Creating a new dataclass to hold persistent state without a corresponding KuzuDB node type

The correct pattern:
1. Define the node type in `campy/brain/hippocampus/schema.py`
2. Write to KuzuDB via `KuzuClient` when state changes
3. Read from KuzuDB (or a per-step cache populated from KuzuDB) when state is needed
4. Never treat the cache as authoritative — KuzuDB is authoritative

This rule exists because the whole point of a knowledge graph is to make inferences across data. Data trapped in Python dicts is invisible to graph queries, cross-puzzle learning, and any future agent that needs to reason about the same state.

---

## Trusted Systems

**Definition** — External systems of record and environment authorities that remain canonical for governed state. Agents and tools interact with trusted systems through approved adapters, not by bypassing ecosystem layers.

### Current owner

ARC-AGI-3 API (Environment).

### Rules

The ARC API is the canonical authority for:

- puzzle state transitions
- `available_actions` per frame
- `WIN` / `GAME_OVER` / `NOT_FINISHED` state
- grid content and frame responses
- game ID lifecycle

The ARC API does not own:

- reasoning or action selection
- memory or retrieval
- orchestration or phase transitions

### Trusted system rule

Agents and tools must reach the ARC API through the approved harness interface (`ARC3Harness._execute_action()`, `_initial_frame()`), not by making direct API calls from arbitrary code.

### Future trusted systems

When new environments or external data sources are added:

- each gets its own adapter in the harness layer
- the adapter exposes a typed protocol or interface
- the agent never calls the external system directly

---

## Observability / Evaluation / Security

**Definition** — Cross-cutting guardrails for audit, telemetry, evaluation, and security spanning every layer.

### Rules

Observability spans every layer:

- **Write traces** — every Campy tool call and phase event is recorded in a structured write trace, exported per step
- **Campy ledger** — every MCP tool invocation is logged with timing, phase, and result status
- **Orchestration report** — run-level summary of phase ownership, tool rules, violations, and gate results
- **Prompt trace / block trace** — ordered block list per step with owner/tool fields
- **Checkpoint persistence** — crash-safe per-task state for run recovery

### Evaluation

- benchmark results are exported as structured JSON with per-step traces
- evaluation metrics (reward, steps, token usage) are tracked per puzzle and per run
- regressions are detected by comparing against `benchmark_lock.json`

### Security

- STDIO transport mandatory; no TCP/HTTP listening ports
- all file read/write confined to project directory (canonicalized paths)
- block `..` escapes and symlink traversal
- Memory Control Panel binds `127.0.0.1` only
- no external network access except to configured LLM providers and ARC API

---

## Fail-Open (CRITICAL)

**Fail-open.** No Campy call may block, fail, or error an agent's own work when the
daemon is unavailable, slow, or returns an error. Read paths (recall, context injection,
hooks) degrade to empty and let the caller proceed. Write paths (capture) drop the write
and log — memory loss is acceptable, blocking the agent is not. The only surfaces allowed
to hard-fail are explicit user-invoked CLI commands, where the user asked Campy a direct
question and deserves a real error.

This is non-negotiable, in the same class as "no shadow stores" above. Campy sits on other
products' build paths; an outage in Campy must never become an outage in whatever the agent
was actually trying to do.

### Why this rule exists

Campy is positioned as a Layer-5 data product inside platforms explicitly designed so no
single component is unrecoverable. If Campy is down, the customer's agents must keep
working — degraded, slower, dumber, but running. An agent that *fails* because a memory
service is unreachable makes Campy a new outage source for someone else's product, which is
disqualifying regardless of how good the memory is.

Latency is the same failure by another name. A hung or slow daemon that holds a per-tool-call
hook for seconds is indistinguishable, from the customer's side, from an agent that is fully
blocked. A shared, generous default timeout is how this happens by accident — so there is no
shared default; every call site states its own budget.

### The exemption: implicit vs. explicit

- **Implicit calls** — anything the agent triggers on the caller's behalf without a human
  directly asking Campy a question: recall, context injection, session-start hooks,
  per-tool-call hooks, background capture/`notify_turn`. These MUST degrade silently to an
  empty/default result and let the caller proceed.
- **Explicit CLI commands** — `campy ask`, `campy recall`, `campy doctor`, and similar
  human-typed commands. A human asked Campy a direct question and is waiting on the answer;
  these should report a real "daemon offline" error rather than silently returning nothing,
  because a silent empty answer would be indistinguishable from "memory has nothing to say"
  and would mislead the user.

### The mechanism

- `campy/brain_transport.py` exposes two client functions:
  - `call_brain()` — raises on failure. Used only by explicit CLI paths.
  - `call_brain_soft()` — never raises; returns a caller-supplied default on any failure
    (unreachable daemon, timeout, HTTP error, JSON-RPC error object, malformed/truncated
    response). Used by every implicit path: adapters, hooks, background capture.
- `call_brain_soft()`'s `timeout` parameter is keyword-only and required — no default. Every
  call site must state its own budget from the timeout table below (or the shell-side
  equivalent, for `.sh` hooks that cannot import the Python constants).
- No retry/backoff on the soft path — a retry on a per-tool-call hook multiplies the latency
  problem instead of fixing it. Fire once, degrade, move on.

| Surface | Budget | Reasoning |
|---|---|---|
| `pre_tool_use` / `post_tool_use` hooks | 1.0s (`HOOK_TIMEOUT`) | fires per tool call; anything more is a tax on every agent action |
| session start / context injection | 3.0s (`CONTEXT_TIMEOUT`) | once per session, some latency tolerable |
| capture / write paths | 2.0s (`CAPTURE_TIMEOUT`) | fire-and-forget; the agent is not waiting on the result |
| explicit CLI (`ask`, `recall`) | 30.0s (`CLI_TIMEOUT`) | user asked, user waits, synthesis is slow |

### Degraded-state visibility

Degrading silently forever is its own failure. `call_brain_soft()` records consecutive
soft-failure counts (see `campy/brain_transport.py: read_soft_failure_state()`), surfaced in
`campy doctor` (the "Fail-Open State" check) and the activity feed
(`~/.campy/activity.log`, see `campy/cli/indicator.py` and `campy/brain/brainstem/activity_log.py`).
This is informational, not a health-check failure — a degraded streak means the daemon has
been unreachable, not that Campy is broken — so it must never flip `campy doctor`'s overall
exit code. It must also never be surfaced into the agent's own context: an infrastructure
complaint in front of an end user who cannot act on it is not "fail-open," it's noise
disguised as help.

---

## Separation Rules Summary

These are the non-negotiable import and dependency rules.

### What may import what

| Source | May import from | Must NOT import from |
|---|---|---|
| `agents/arc3/` | `benchmarks/arc3/adapter.py`, `benchmarks/arc3/schema.py`, `benchmarks/arc3/state_serializer.py` | `campy/brain/`, `brain_daemon.py` |
| `benchmarks/arc3/adapter.py` | `campy/brain/thalamus/tools/` (only in `LocalBrainClient`) | `agents/` |
| `benchmarks/arc3/harness.py` | `benchmarks/arc3/adapter.py`, external ARC API | `campy/brain/` (except via adapter) |
| `campy/brain/` | `campy/brain/` internals only | `agents/`, `benchmarks/` |
| `adapters/` | `campy/brain/`, `brain_daemon.py` | `agents/`, `benchmarks/` |
| `tests/` | anything (test code) | — |

### Quick check command

```bash
# Verify no Campy imports in ARC agent code
grep -rn "from campy\|import campy" agents/ && echo "VIOLATION" || echo "CLEAN"

# Verify no ARC imports in Campy code
grep -rn "from agents\|import agents\|from benchmarks\|import benchmarks" campy/ && echo "VIOLATION" || echo "CLEAN"
```

---

## Adding New Agents

When a second agent is added beyond ARC:

1. Create `agents/<agent_name>/` with its own orchestrator, reasoning, and solver logic.
2. The agent accesses Campy through `BrainClientProtocol` — same interface, same MCP tools.
3. The agent gets its own harness in `benchmarks/<benchmark_name>/` or uses a shared harness.
4. Shared prompts, skills, and knowledge move to a shared `knowledge/` directory.
5. Agent-specific prompts stay in the agent's own directory.
6. The import separation rules apply identically to the new agent.

---

## Adding New Tools

When a new MCP tool is added to Campy:

1. Define the tool schema in `campy/brain/thalamus/tool_schemas.py`.
2. Implement the handler in `campy/brain/thalamus/tools/`.
3. Add the tool to [docs/tool-catalog.md](tool-catalog.md).
4. Add the method to `BrainClientProtocol` in `benchmarks/arc3/adapter.py`.
5. Implement the method in `LocalBrainClient`, `NoOpBrainClient`, and `LedgerBrainClient`.
6. Add phase constraints in [docs/arc-harness-rules.md](arc-harness-rules.md).
7. Update adapter allow-lists if the tool should be exposed to external adapters.
8. Run: `pytest -q tests/test_adapters.py tests/test_analogical.py tests/test_web.py`

---

## Adding New Deterministic Tools

When a new deterministic tool or compute capability is added:

1. If it's ARC-specific, put it in `agents/arc3/` or `benchmarks/arc3/`.
2. If it's Campy-internal, put it in `campy/brain/temporal_lobe/loop/` or `campy/brain/hippocampus/graph/`.
3. If it's reusable across agents, put it in a shared `tools/` or `scripts/` directory.
4. It must not own workflow state, memory, or phase transitions.
5. It must take explicit inputs and return explicit outputs.

---

## One-Sentence Rule

The control plane owns workflow and phase transitions, the harness owns agent reasoning, shared knowledge feeds prompts and skills, deterministic tools own bounded compute, Campy owns memory and is accessed only through MCP, the ARC API is the trusted environment authority, observability spans everything, and **Campy code and ARC code never cross-import**.
