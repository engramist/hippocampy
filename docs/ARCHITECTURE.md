# HippoCampy — Architecture Specification

> **Canonical architecture reference for all agents and contributors.**
> This is the single source of truth for the system design, schema, Loop steps, tools, and IP claims.
> Agent-specific workflow files (CLAUDE.md, GEMINI.md, etc.) reference this document — do not duplicate architecture content there.

## Required Companion References

- Ecosystem rules (layer boundaries and separation rules): [docs/ecosystem-rules.md](ecosystem-rules.md)
- Codebase anatomy navigation guide: [docs/codebase-anatomy.md](codebase-anatomy.md)
- Codebase anatomy refactor plan: [docs/codebase-anatomy-refactor-plan.md](codebase-anatomy-refactor-plan.md)
- Tool catalog (keep in sync with tool schemas/handlers): [docs/tool-catalog.md](tool-catalog.md)
- Wiki projection architecture: [docs/wiki-projection-architecture.md](wiki-projection-architecture.md)
- ARC extraction boundary audit: [docs/arc-extraction-cleanup-audit.md](arc-extraction-cleanup-audit.md)
- Backlog card authoring and execution rules: [backlog/BacklogRules.md](../backlog/BacklogRules.md)
- Backlog planning/tracking status source: [backlog/masterBacklogTracker.md](../backlog/masterBacklogTracker.md)
- Open architectural questions (measured-but-unresolved, deferred, or awaiting counsel): [Open Research Questions](#open-research-questions), below

## Patent Notice

**Patent Pending:** This system includes patent-pending memory architecture. U.S. Provisional Application #64/017,066 was filed March 25, 2026. Non-provisional filing deadline: March 25, 2027. No patent has been granted. See [PATENTS.md](../PATENTS.md) for filing facts.

## Open Research Questions

This section is not settled design. It records architectural questions that are **open**
(unresolved, awaiting input), **measuring** (an in-flight card is producing the answer),
**resolved** (answered, kept here so the answer and its methodology stay attached to the
question), or **deferred** (deliberately postponed, with the condition that would reopen
it). Everything else in this document describes what Campy *does*; this section describes
what is still uncertain about why it does it that way. Every number below states how it
was measured (warm/invoked vs. cold/import-time RSS, and sample size where relevant) — a
bare figure with no methodology is exactly the defect this section exists to prevent.

Each entry: **Question** / **Status** / **Why it matters** / **Evidence so far** /
**Where the detail lives** / **Decision rule** (where one was fixed in advance, before the
evidence came in).

### Does the spaCy ingestion step earn its place?

| Field | Detail |
|---|---|
| Status | `measuring` — [B401](../backlog/B401.md), currently blocked on B400 merging |
| Why it matters | spaCy's only load-bearing output is candidate entity **spans** — `if not entities: return summary` gates the entire Gated Consolidation Loop. Its NER labels are discarded (`classify_concept()` recomputes `gist_class` independently) and its Step 1b dependency-parse relations are backstopped by Step 3b's LLM `extract_semantic_relations()`. The graph's schema already carries a SKOS-style `Label` gazetteer (`HAS_PREF_LABEL`/`HAS_ALT_LABEL`/`HAS_HIDDEN_LABEL`) that Step 1 (`step1_ner.py`) never queries — zero `db`/`gateway`/`MATCH` access. |
| Evidence so far | Warm RSS (model loaded **and invoked**, matching a running daemon), measured on the design-doc author's machine: baseline Python 14.5 MB; + spaCy loaded and invoked 541.0 MB; + fastembed loaded and invoked 818.6 MB; spaCy with the `torch` import blocked 386.9 MB. `torch` accounts for ~154 MB resident / 436 MB on disk and is never used for computation (`thinc`'s backend is `NumpyOps`). `step1_ner.py`'s own docstring states spaCy NER "misses most software/tech terms... noun chunks catch them." B387's separate ONNX-replacement measurement (entity-span F1 0.534 vs. spaCy, 46 sentences) cannot settle this question — it measures agreement between two candidate generators, not correctness against ground truth. |
| Where the detail lives | [docs/superpowers/specs/2026-09-05-entity-candidate-generation-design.md](superpowers/specs/2026-09-05-entity-candidate-generation-design.md) (full analysis, §1–§4); [backlog/B401.md](../backlog/B401.md) (the three measurements this status depends on) |
| Decision rule | Fixed in advance, per the design doc and B401: gazetteer coverage **high** and Step 1b relation survival **low** → delete the spaCy step, link against the graph. Coverage high, survival high → keep a parser but demote NER behind the gazetteer. Coverage **low** → gazetteer not yet dense enough, keep spaCy, revisit after more ingestion. A result that does not cleanly fit is to be escalated, not forced onto the nearest branch. |

### What is the real warm memory floor?

| Field | Detail |
|---|---|
| Status | `resolved` |
| Why it matters | B384's `<80 MB` daemon-memory target propagated into four downstream cards and review commentary before anyone re-derived it. It was **import-time-only RSS** — never a running daemon's footprint — because `fastembed`'s model is lazily loaded and is not actually resident until `.embed()` is called. |
| Evidence so far | Warm (model loaded **and invoked**) RSS, same measurement run as above: baseline Python 14.5 MB → + spaCy loaded and invoked 541.0 MB → + fastembed loaded and invoked **818.6 MB**. Contrast with the import-time-only figures that produced the original target: B387's table (`bare Python` 14.8 MB, `+ kuzu` 24.3 MB, `+ kuzu + fastembed` 76.1 MB) and B389's table (same shape) measure imports only, before any model is invoked — calling `.embed()` alone reaches ~266–277 MB per the design doc. `<80 MB` warm is not achievable while ONNX embeddings run in-process; the design doc recommends restating any future target against the measured 818.6 MB warm baseline rather than carrying `<80 MB` forward. |
| Where the detail lives | [docs/superpowers/specs/2026-09-05-entity-candidate-generation-design.md](superpowers/specs/2026-09-05-entity-candidate-generation-design.md) §5, "Measurement methodology" — states the going-forward rule that all future memory figures must be reported warm, per component, with the stage at which they were taken recorded alongside the number |
| Decision rule | N/A — resolved. Standing methodology rule for all future memory claims: report cold-import and warm-invoked RSS separately, per component. |

### Kùzu exit rationale

| Field | Detail |
|---|---|
| Status | `resolved` |
| Why it matters | B384 originally justified the Kùzu → RDF-star (Oxigraph) migration primarily on memory savings. [B389](../backlog/B389.md) states plainly that this justification was wrong and must not be repeated in that migration's PR. Getting the *actual* driver right matters because a memory-based justification would be trivially refuted (see evidence) and would undermine the real, non-memory case for the migration. |
| Evidence so far | Kùzu's own memory cost is small: bare Python 14.8 MB, `+ kuzu` 24.3 MB, `+ kuzu + fastembed` 76.1 MB (B389's table). These are import-time RSS figures — the table is headed "Imports \| RSS," the same shape as B387's original table that §5 above found to understate a running daemon's footprint — not warm/invoked numbers, so they should not be read as the daemon's real resident cost. Read only as Kùzu's marginal cost over fastembed alone (fastembed-only import RSS is 75.1 MB per B387's table), Kùzu adds roughly 1 MB — consistent with B389's own framing ("Kùzu costs ~1 MB on top of fastembed"). The actual drivers B389 gives, in order: (1) Kùzu has been archived/EOL since October 2025 — an unmaintained embedded database holding the sole source of truth is the real risk, and the primary driver; (2) B311 commit-checkpoint memory spikes (150 MB → 1.1 GB transient); (3) B285 — no in-place HNSW index updates, and rebuilding requires an archive-move Kùzu 0.11.3 cannot do cheaply; (4) native RDF-star edge annotation for the provenance model. |
| Where the detail lives | [backlog/B389.md](../backlog/B389.md) |
| Decision rule | N/A — resolved. |
| Contradiction flagged, not reconciled | This document's own `Technology Stack` and `Kùzu Implementation Notes` sections (above) still name **RyuGraph** as the migration fork to watch. B389's actual in-flight target is an **Oxigraph**/RDF-star client (`campy/brain/hippocampus/graph/oxigraph_client.py`), not RyuGraph. Per this section's own rule (record, do not decide), that mismatch is recorded here rather than silently edited into the existing `Technology Stack` / `Kùzu Implementation Notes` text. |

### CoNLL-2003 licence for commercial use

| Field | Detail |
|---|---|
| Status | `open`, flagged for patent counsel |
| Why it matters | HippoCampy has an active patent filing (see Patent Notice above). The ONNX NER model built for B387 is fine-tuned on CoNLL-2003 (via Reuters RCV1 news text); whether a model trained on that corpus is a "derivative work" for licensing purposes is unsettled for pretrained NLP models generally, and has not had a formal counsel review here. |
| Evidence so far | Per the completion notes for B387 (commit `1de6a1c`, branch `feat/b387-torch-free-ingestion` — **not yet merged to `main`**; `backlog/B387.md` on `main` does not yet contain this writeup): the shipped base model is `elastic/distilbert-base-cased-finetuned-conll03-english`, whose Hugging Face `cardData.license` is Apache-2.0, verified directly via the HF API. Training-data provenance was investigated separately: the Reuters/NIST agreement gates redistribution of the raw corpus text, not downstream model weights; `elastic`'s explicit, unchanged-since-2022 Apache-2.0 grant plus industry precedent (`dslim/bert-base-NER`, MIT license, ~2.1M downloads/month, same CoNLL-2003 provenance) were judged to support proceeding — but this was an engineering judgment call, explicitly flagged for counsel review given the active patent filing, and was not blocked on that review. |
| Where the detail lives | [backlog/B387.md](../backlog/B387.md) (card, on `main`); full Gate-0 licence writeup is in the commit message and PR description for "feat(B387): finish torch-free NER" — commit `1de6a1c` on branch `feat/b387-torch-free-ingestion`, not yet on `main` as of this writing |
| Decision rule | Not formally fixed. If counsel review finds the CoNLL-2003/Reuters training-data provenance disqualifying, the NER model choice (or its training-data lineage) needs replacement before the non-provisional filing deadline (March 25, 2027); no such finding has been reported. |

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
- **Embeddings:** `fastembed`/ONNX Runtime (local; `sentence-transformers/all-MiniLM-L6-v2`, same model as before B355 — see B342/B353/B355 below for why the runtime changed)
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
provider = "sentence-transformers"   # config label kept for backward compat; backed by fastembed/ONNX
                                      # since B355, not PyTorch -- same model, ~6.5x smaller footprint
                                      # contribution from the embedding backend itself (1.22GB -> 186MB,
                                      # see B355's correction note; the daemon's own torch floor from
                                      # spaCy is unrelated and unaffected by this)
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
- **No encryption at rest for the primary KuzuDB store.** The graph database on disk
  (`~/.campy/db/` or the configured path) is not encrypted by Campy itself — this is a
  deliberate scope decision, not an oversight. Campy is a local single-user tool
  (`LocalSingleUserResolver`, see `campy/brain/auth.py`); its threat model assumes the
  filesystem itself is the trust boundary, the same assumption most local-first single-user
  tools make (browsers, local SQLite-backed apps, etc.). Protection against data-at-rest
  exposure (lost/stolen device, disk imaging) is expected to come from OS-level full-disk
  encryption — FileVault (macOS), BitLocker (Windows), or LUKS (Linux) — which every mainstream
  OS enables easily and which this project does not attempt to duplicate. Users running Campy
  in a regulated or otherwise high-security environment should confirm disk encryption is
  enabled on the host, the same way they would for any other local data store. (Backup
  snapshots inherit the same posture — see B319's "What this card does not do" below.)

## IP Protection

**Provisional patent filed.** Application # **64/017,066**, filed March 25, 2026. See
[PATENTS.md](../PATENTS.md) for filing facts. Priority date is March 25, 2026; the
non-provisional deadline to preserve priority is March 25, 2027.

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

  `plugin/skills/recall/SKILL.md` is the canonical recall policy. It ships
  with the Campy plugin and auto-installs to all supported agents: Claude Code
  (`~/.claude/plugins/hippocampy/skills/`), Codex (`~/.codex/skills/`),
  Gemini CLI (`~/.gemini/skills/`), and VS Code Copilot
  (`.github/copilot-instructions.md`). The dev-only `skills/campy-memory/`
  remains as the memory-awareness reference for contributors.

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
- **Archived-node HNSW hygiene (B285):** Kuzu 0.11.3 supports `DROP_VECTOR_INDEX(table, index)`; inserts are immediately visible in index queries; deletes remove rows from index; updating indexed embeddings is disallowed. Because removing archived vectors requires row movement (invasive archive-table design), current B285 scope ships archived-ratio telemetry + adaptive retrieval headroom. Automatic rebuild remains disabled by behavior design until a dedicated archive-move architecture decision lands.
- **Relationship table typing:** Named semantic relationships defined as `FROM Concept TO Concept` only. `REIFIED_AS` uses Kùzu's multi-FROM/TO syntax: `CREATE REL TABLE REIFIED_AS (FROM Concept TO Decision, FROM Concept TO Constraint, FROM Concept TO Requirement, FROM Concept TO ActionItem)`.

### Graph Engine Portability

Campy now keeps an engine-neutral escape hatch for the graph itself:

- `campy export-graph --out <dir>` streams every node table to `nodes/<Table>.jsonl`, every relationship table to `rels/<RelTable>.jsonl`, and writes a `manifest.json` with `format_version`, `exported_at`, `engine`, `embedding_dim`, per-table primary keys, and row counts.
- `campy import-graph --in <dir> --db <fresh.db>` restores a dump into an empty database, recreates the schema, loads nodes first, loads relationships second, and rebuilds vector indexes after bulk load.
- Export/import must remain streamed. Do not materialize the whole graph in memory just to move between engines.
- The migration playbook is: export the live graph, implement a new facade behind `campy/brain/hippocampus/graph/kuzu_client.py`, run the facade conformance suite, import into the new engine, then rerun the calibration and round-trip tests.
- `campy/brain/hippocampus/graph/kuzu_client.py` stays the only module that imports `kuzu` directly. All portability work must route through that facade.

### Module Structure

The engine lives under `campy/brain/`, organized into functional brain regions. See
[docs/codebase-anatomy.md](codebase-anatomy.md) for the region-to-responsibility map and
placement guide (`brainstem`, `sensory_cortex`, `temporal_lobe`, `hippocampus`, `thalamus`,
plus `basal_ganglia` for avoidance-learning/frustration-cluster detection and `llm` for the
provider abstraction).

```
hippocampy/
├── campy.toml
├── campy/
│   ├── brain_daemon.py
│   ├── cli/                     # campy CLI (setup, install, status, doctor, ...)
│   ├── brain/
│   │   ├── brainstem/           # daemon lifecycle, config, sweeps, telemetry
│   │   ├── sensory_cortex/      # capture, ingestion, tabular data
│   │   ├── temporal_lobe/       # consolidation loop, routing, anomaly detection
│   │   │   └── loop/            # Gated Consolidation Loop steps 1–7
│   │   ├── hippocampus/         # schema, graph client, embeddings, quest identity
│   │   │   └── graph/           # kuzu_client.py, embeddings.py
│   │   ├── thalamus/            # MCP tools, tool schemas, retrieval, bundle compiler
│   │   │   ├── tools/           # MCP tool implementations
│   │   │   ├── compression/     # pluggable thalamic compression registry (B289)
│   │   │   └── formatters/      # per-adapter output formatters (B253)
│   │   ├── basal_ganglia/       # avoidance learning, frustration-cluster detection
│   │   └── llm/                 # provider.py — OpenAI-SDK-compatible LLM abstraction
├── adapters/
│   ├── openclaw_gateway.py      # OpenClaw prompt construction (Layer 1 + Layer 2 model)
│   ├── claude_code/, codex/, claude_desktop/, chatgpt_desktop/, gemini_cli/
│   └── */hooks/                 # Claude Code hook scripts (Layer 2)
├── web/                         # FastAPI, 127.0.0.1 only
├── docs/
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
| Anomaly / Security sense | Content contradicts a high-confidence GlobalConstraint (pathway_strength > 0.8) — flags an internal *consistency* conflict (candidate goal hijacking), sets `flagged_for_review` |
| Success sense (B69) | "perfect", "great job", "approved", "all tests pass" — Dopamine signal |
| Failure sense (B69) | "that's wrong", "revert", "that broke", "start over" — Pain signal |
| Emotion / Salience sense | Frustration ("I told you", "stop doing"), excitement ("love it", "brilliant"), urgency ("ASAP", "critical") — boosts pathway_strength via multiplier [1.0–1.6], rescues borderline content (0.45–0.60) above noise floor |

No human confirmation required. Uncertain nodes enter as tentative knowledge, re-scored continuously.

**Prompt injection — what's actually mitigated and what isn't.** The Anomaly/Security sense above is a
*contradiction* detector, not an injection detector: it flags new content that conflicts with an existing
high-confidence constraint. A novel injected instruction with nothing pre-existing to contradict is not
caught by it. The real mitigation is B339 (`campy/brain/thalamus/memory_formatter.py`): recalled memory
content fed into `ask`'s LLM prompt is HTML-escaped and wrapped in `<retrieved_memory source="..."
trust="stored_data">` boundary tags, with an explicit system instruction that tagged content is data, not
directives — the same data/instruction boundary this document's own consuming agents are expected to
apply to tool results generally. `flagged_for_review` (set by the Anomaly/Security sense above) is now
also consulted at recall time — `bundle_compiler.py`'s exact-fact, semantic, and graph-traversal stages
exclude flagged nodes from what gets surfaced back into a prompt. This reduces but does not eliminate
injection risk; it has not been evaluated against a dedicated adversarial-prompt test suite. Threat model:
Campy runs as a local single-user tool (`LocalSingleUserResolver`, see `campy/brain/auth.py`) with no live
multi-tenant ingestion path, so the realistic exposure is self-poisoning from content the user's own
sessions or document ingestion pull in (a scraped page, a malicious doc) — not third-party attack. See
`backlog/B339.md`.

**Step 4b — Associative Pattern Check (Anticipatory Engine — Phase 3):**
When a message contains error/failure signals or significant action patterns (docker, kubectl, deploy, etc.), Step 4b checks the entity's embedding against stored Lessons and Procedures via HNSW vector search. If similarity exceeds 0.65 and the matched node has no trigger metadata, Step 4b auto-binds trigger columns (`trigger_pattern`, `trigger_hook_type`, `trigger_tool`, `trigger_project_scope`). The manifest compiler picks these up on the next sweep cycle, and hook scripts start injecting the Lesson/Procedure text into agent context. Near-zero cost — runs only when signals are present, uses existing entity vectors, no LLM calls.

**Step 5 — Dual-Scope Retrieval (Availability Heuristic):** Check branch scope (same MainQuest + vector similarity) then global scope (GlobalConstraint/GlobalPreference nodes) for existing matches.

**Step 6 — Constrained Contradiction Arbitration:** Only runs in gray zone (0.75–0.92 similarity) or same artifact type match. LLM forced to `{classification, rationale_tokens, referenced_nodes}`. "Uncertain" → soft-lock.

**Step 7 — Pathway Update:**
- Additive: increment `pathway_strength` on access: `strength += 1 * log(1 + 1/days_since_last_access)`. No duplicate node created.
- Contradiction: create new node + `[DEPRECATED_BY]` edge from old to new. Old node preserved in audit trail, filtered from `current_truth`.
- After pathway update: trigger **event-driven confidence re-scoring** on nearby `confidence_low` nodes (within 1–2 hops).
- **CO_OCCURS_WITH write:** After Step 7 completes, write (or increment) `CO_OCCURS_WITH` edges between all concept pairs from the same message that cleared the noise floor (>60% confidence). Edge `strength` initialized to `min(confidence_A, confidence_B)` — capped at the weaker node. Background sweep updates `strength` as endpoint confidences change over time.

## Biomimetic Learning Principles

### Basal Ganglia (`campy/brain/basal_ganglia/`)

Procedural learning, action selection, reward prediction, and exploration policy.

Submodules:
- **`frustration_clusters.py`** — Detects high-salience frustration clusters and auto-generates avoidance Procedures (graph-only, no LLM)
- **`procedure_synthesis.py`** — Synthesizes automation Procedures from clusters of successful Plans (LLM-assisted, `min_cluster_size=2`)
- **`procedure_maturity.py`** — Implements Procedure lifecycle: nascent → developing → mature → degraded → archived
- **`action_selector.py`** — Go/No-Go gating for action selection based on accumulated graph evidence (used by ARC and general agents)
- **`reward_predictor.py`** — Records prediction error (dopamine-style learning signal) for plan outcomes
- **`exploration_policy.py`** — Balances exploitation (repeat known-good actions) with exploration (try untested actions)

Maturity lifecycle tracks Procedure reliability:
- `nascent` (fresh) → `developing` (3+ applications, 50%+ success) → `mature` (10+ applications)
- Degradation detected at `success_rate < 0.4` (→ `degraded`) → archived (manual or decay)

The synergy with **Amygdala** is critical: emotional salience at encoding time (salience_score) feeds frustration cluster detection at consolidation time. Pain drives habit formation — the same neuroscience principle that makes humans pull their hand from a hot stove.

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
- `Lesson` (`lesson_id`, `text_raw`, `embedding`, `domain`, `lesson_type`, `confidence`, `confidence_low`, `pathway_strength`, `archived`, `created_at`, `last_audited_at`, `stale_flagged`, `orphan_flagged`, `trigger_pattern STRING`, `trigger_hook_type STRING`, `trigger_tool STRING`, `trigger_project_scope STRING`) — trigger columns enable Layer 2 associative hooks and are auto-populated by Layer 3 Step 4b
- `Plan`, `PlanStep` — see Active Agent System section above

**External Consumer Evidence Nodes**:
- `ArcRun`, `ArcTaskResult`, `ArcArtifact`, `ArcEvent` — durable records created by `ingest_arc_artifacts` from sibling `ARC_AGI` run artifacts
- `ArcMechanic`, `ArcActionPattern`, `ArcEffectPattern`, `ArcPrecondition`, `ArcFailureMode`, `ArcRecoveryPolicy` — cross-run mechanic memory published by external ARC consumers
- `ArcWorldModelStep`, `ArcWorldModelSummary` — world-model evaluation evidence imported from ARC artifacts
- `Hypothesis` and `Exploration` — generic graph-native reasoning structures retained for non-ARC and external-consumer experiments

**Metacognitive & Procedural Nodes:**
- `Procedure` (B194) (`procedure_id`, `name`, `domain`, `archetype`, `description`, `steps_json`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`, `success_count`, `application_count`, `success_rate`, `confidence`, `pathway_strength`, `archived`, `created_at`, `last_applied_at`, `trigger_pattern STRING`, `trigger_hook_type STRING`, `trigger_tool STRING`, `trigger_project_scope STRING`) — reusable parameterized strategy templates distilled from successful Plans. Trigger columns enable Layer 2 associative hooks — when set, the manifest compiler includes this Procedure in the trigger manifest for automatic context injection.
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

**`memory_decision`** — call when unsure whether a prompt warrants recall. Returns a compact recommendation (`should_recall`, `recommended_tool`, `query`, `reason`, `confidence`, `context_budget`, `anti_bloat_guidance`) without retrieving memory. Routes multi-entity or broad context queries to `compile_context` (B254). This is the runtime companion to the recall skill (`plugin/skills/recall/SKILL.md`).

**`current_truth`** — call before answering architecture or past-decision questions. Searches consolidated artifacts and bounded episodic `Message` evidence, then ranks by graph strength (`pathway_strength × confidence`, plus bounded outcome valence). Includes optional `include_rationale` for 1-hop provenance context.

**`explore_graph`** — directed multi-hop traversal with configurable depth, strategy (DFS/BFS), edge types, direction, and context window (B10)

**`recall_relevant_lessons`** — cross-quest analogical recall (B11)

**`recall_plans`** — retrieve past strategies by goal similarity (B67)

**`analogical_search`** — cross-quest search (M8)

**`reconstruct_timeline`** — reconstruct temporal sequence of messages and decisions for a topic (B192)

**`recall_procedures`** — retrieve reusable Procedure templates by archetype or semantic query, ranked by success rate (B194)

**`get_knowledge_gaps`** — return active KnowledgeGap nodes for proactive metacognitive review (B193)

### Bundle Compilation & Tabular Tools (B249–B254)

**`compile_context`** — heterogeneous retrieval: assembles a `ContextBundle` from exact facts (GlobalConstraint/Preference), semantic search, graph traversals, tabular data, and wiki summaries. 5-stage pipeline with token budget management (small ≤8K, medium ≤128K, large 200K+). Output formatted per agent type via `campy/brain/thalamus/formatters/`. This is the primary retrieval tool for multi-entity queries; `memory_decision` routes here when it detects broad context needs.

**`ingest_document`** (extended) — now dispatches `.csv`, `.xlsx`, `.tsv`, `.xls` files to the tabular ingestion pipeline (B250). Tabular files get dual storage: full data in per-dataset SQLite + metadata/extracted facts in the Kuzu graph.

### Augmented Inference Tools (B289)

**`ask`** — thalamic compression pipeline: augments the query with graph-native memory via `compile_bundle`, compresses the context bundle through four pluggable compressors, makes a single LLM inference call, and captures the result via `notify_turn`. Use when you want a synthesized, memory-grounded answer. Use `current_truth` for raw facts; use `compile_context` for assembled context bundles.

**Compression pipeline** (`campy/brain/thalamus/compression/`): pluggable registry with `ContentRouter` dispatching by `section_type`:
- `StructuredDataCompressor` — converts `exact_fact`/`tabular` sections to TOON format (30–60% token reduction)
- `LLMCompressor` — compresses `summary` prose sections using the configured LLM
- `ASTCodeCompressor` — folds `code` sections to signatures using tree-sitter (75–90% token reduction)
- `GraphBundleCompressor` — graph-native scoring for `semantic`/`graph` sections: scores nodes by `cosine_similarity(query_emb, node_emb) × pathway_strength`, prunes the bottom `graph_prune_threshold` fraction, serializes survivors in compact `PREFIX:text` notation. **Do not substitute with StructuredDataCompressor** — it prunes semantic irrelevance, not syntactic overhead.

Config defaults (all optional, `campy.toml` `[compression]` section): `compression_model` (empty = inherit from `[llm]`), `graph_prune_threshold` (0.30), `structured_format` ("toon"), `ast_compression` (true).

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

## Context Window Integration — Layer Cake Architecture

Four layers work together to get graph knowledge into agent context windows without requiring explicit tool calls. Each layer operates at a different timescale and precision level; they compose — higher layers discover and write, lower layers deliver.

### Layer 1 — File Bridge (Semantic Context)
**Module:** `campy/brain/thalamus/file_bridge.py`
**CLI:** `campy context regen`
**Delivery:** Generates `CONTEXT.md` (domain vocabulary, active decisions, project constraints) and ADR files from graph state. Written to project directories where agents read them as regular files. Regenerated on sweep cycle or on-demand via CLI.

### Layer 2 — Associative Hooks (Reflexive Memory)
**Modules:** `campy/brain/thalamus/trigger_manifest.py`, `adapters/claude_code/hooks/pre_tool_use.sh`, `post_tool_use.sh`
**CLI:** `campy trigger add|list|remove|compile`
**Delivery:** Procedure and Lesson nodes with `trigger_pattern` columns are compiled into `~/.campy/triggers/manifest.json` on each sweep cycle. Claude Code hook scripts grep this manifest on every tool call — if a regex pattern matches the tool input (PreToolUse) or output (PostToolUse), the matching Lesson/Procedure text is injected as `additionalContext`. Zero daemon round-trip on the hot path.

### Layer 3 — Anticipatory Engine (Prospective Memory)
**Module:** `campy/brain/temporal_lobe/loop/step4b_associative.py`
**Delivery:** Online mode runs as GCL Step 4b during message processing. When error/action signals are detected, checks entity embeddings against stored Lessons/Procedures. Auto-binds trigger metadata to unbound matches (similarity > 0.65). The manifest compiler picks these up next sweep cycle — closing the learn → discover → deliver loop. Near-zero cost: graph queries only, no LLM calls.

### Layer 4 — Process Skills (Deliberate Recall)
**Modules:** `plugin/skills/` (12 skills, auto-install with plugin)
**Delivery:** 12 skills ship with the Campy plugin and auto-install to all supported agents (Claude Code, Codex, Gemini CLI, VS Code Copilot). Five process skills are forked from Matt Pocock's skills with lean Campy memory integration: `campy-grill` (domain grilling), `campy-diagnose` (6-phase debug loop), `campy-tdd` (red-green-refactor), `campy-handoff` (session handoff + graph persistence), `campy-improve-architecture` (deepening opportunities). Seven Campy-native skills handle memory operations: `recall`, `brief`, `learn`, `session-start`, `memory-awareness`, `quest-management`, `status`. Enhanced skills suggest Campy MCP tools at natural inflection points without mandating calls — session-start already loads graph context.

### Layer interaction
```
Layer 3 (Anticipatory) discovers patterns → writes trigger metadata to graph
Layer 2 (Hooks) compiles triggers → delivers context on tool calls
Layer 1 (File Bridge) generates context files → agents read as regular files
Layer 4 (Skills) provides deep retrieval → user-initiated complex queries
```

The trigger manifest (`~/.campy/triggers/manifest.json`) is the shared bus between Layers 2 and 3. Layer 3 writes trigger_pattern columns; Layer 2's manifest compiler reads them and produces the JSON file that hook scripts consume.

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
- `campy/brain/thalamus/wiki_projection.py`
- `campy/brain/brainstem/sweep.py`
- `campy/cli/wiki.py`
- `docs/wiki-projection-architecture.md`

### ARC Artifact Projection

ARC_AGI artifacts do not become wiki pages directly. They first flow through `ingest_arc_artifacts`, which writes `ArcRun`, `ArcTaskResult`, `ArcArtifact`, `ArcEvent`, `ArcMechanic`, and world-model evaluation nodes into KuzuDB. The `arc_agi` wiki persona then projects those graph records into browsable Markdown.

## Error / Degraded Mode

**Scenario A — Brain Daemon unreachable** (socket missing/refused — crashed or never started — **or**
alive but too slow to answer within its timeout budget, see below):
- Adapter detects connection failure (or timeout) at startup or per-call
- Modifies injected fragment to: `[SideQuest OFFLINE — memory unavailable]`
- Returns graceful MCP error on `current_truth` calls (LLM session continues without memory)
- Queues failed passive ingestion messages to a local flat file; replays when daemon reconnects

This message is a generic soft-failure indicator, not literally "the process is down" — `call_brain_soft()`
(`campy/brain_transport.py`) treats a socket connect refused/missing, a malformed response, *and* a plain
timeout (`CONTEXT_TIMEOUT`/`CAPTURE_TIMEOUT`, both a few seconds) identically, fail-open by design so an
unresponsive daemon never hangs the calling agent. B342's investigation (see below) found a real, live
case of the timeout path firing with the daemon fully alive: under heavy memory pressure (page faults
into swapped/compressed memory are slow), an otherwise sub-100ms response can exceed the timeout budget,
producing this exact message even though nothing crashed. The fail-open design itself is correct and
deliberately not changed by that finding — the daemon's own memory footprint being small and bounded
(B353's initiative) is what actually reduces how often this happens in practice, not a wider timeout.

**Scenario B — Ollama unreachable** (daemon up, LLM steps fail):
- Step 2 System 1 (embedding similarity) still runs — only LLM-dependent sub-steps degrade
- Step 2 System 2 unavailable → store concept as `confidence_low=true`, skip LLM call; background sweep retries when Ollama is back
- Step 6 arbitration unavailable → store both gray-zone candidates as `confidence_low=true`; background sweep arbitrates later
- No data loss in either failure mode

## Installation Story

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/install.sh | sh

# or install manually
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

## Context Integration CLI

**`campy context regen`** — Force-regenerate CONTEXT.md and ADR files for the current project from graph state. Useful after bulk ingestion or when context files are stale.

**`campy trigger add`** — Bind a trigger pattern to a Procedure or Lesson node. Options: `--pattern`, `--hook` (PreToolUse|PostToolUse), `--tool`, `--scope`, `--procedure` or `--lesson`.

**`campy trigger list`** — Show all active trigger bindings in a table.

**`campy trigger remove`** — Clear trigger metadata from a Procedure or Lesson node.

**`campy trigger compile`** — Force-compile the trigger manifest from graph state (normally runs on sweep cycle).

## B312 — Provenance + Explicit Supersession on Fact-Bearing Nodes

First card in the cloud/interop series (B312–B317). Every other card in that series
assumes this has landed, and it is the schema contract downstream agents (Claude,
Gemini, Codex) should read before writing to fact-bearing tables.

### Provenance columns

Four columns on every table in `schema.PROVENANCE_TABLES`:

| Column | Type | Meaning |
|---|---|---|
| `source` | `STRING` | Owning source identifier, namespaced `<kind>:<id>` — e.g. `agent:claude-code`, `harvest:git`, `user:direct`, `import:temporal`. |
| `source_version` | `STRING` | Version of the source at observation time (git SHA, adapter version, model ID). Nullable when genuinely unversioned. |
| `observed_at` | `TIMESTAMP` | When the fact became true / was observed. Distinct from `created_at` (when Campy wrote the row) — the two match for live capture, diverge for backfill/harvest. |
| `evidence_ref` | `STRING` | Pointer to evidence — message ID, file path + line, run ID, URL. Nullable but strongly preferred. |

`PROVENANCE_TABLES` (`campy/brain/hippocampus/schema.py`) is the Tier 1 (claimed/observed
facts: `Concept`, `Decision`, `Constraint`, `Requirement`, `ActionItem`, `GlobalConstraint`,
`GlobalPreference`, `Lesson`, `Procedure`, `KnowledgeGap`, `Plan`, `PlanStep`, `Hypothesis`,
`ActionFact`, `ActionEffect`, `VictoryCondition`, `Rule`, `Transition`, `DocumentExtract`,
`WorkSummary`, `WorkArtifact`) + Tier 2 (learned/inferred Arc\* patterns: `ArcMechanic`,
`ArcActionPattern`, `ArcEffectPattern`, `ArcPrecondition`, `ArcFailureMode`,
`ArcRecoveryPolicy`, `ArcWorldModelStep`) table set. Structural/ontology/runtime-record
tables (`Session`, `Message`, `Document`, `MainQuest`, `ArcRun`, `TaskGraph`, ...) do **not**
carry provenance — they are Campy's own bookkeeping, not claims about the world.

`Plan` and `VictoryCondition` already had a `source` column before this card (plan
origin `"active"`/`"passive"`, VC origin) — a different, narrower concept than the B312
provenance `source`. B312 did not overwrite or duplicate that column; those two tables
only gained the other six columns (`PlanStep`, which had no pre-existing `source` column,
got the full seven).

### Explicit supersession

Three node columns (same table set as provenance) plus a `DEPRECATED_BY` rel table:

| Column | Type | Meaning |
|---|---|---|
| `superseded_by` | `STRING` | Primary key of the node that replaced this one. `NULL` = current. |
| `superseded_at` | `TIMESTAMP` | When supersession happened. |
| `supersession_reason` | `STRING` | One of `SUPERSESSION_REASONS` (below). |

`SUPERSESSION_REASONS` (module-level frozenset in `schema.py`): `replaced` (a newer fact
says it better), `contradicted` (proven false), `source_removed` (upstream source no
longer asserts it), `merged` (folded into another node — pairs with `MergeEvent`),
`expired` (time-bounded fact whose window closed).

**B326 update — SUPERSEDES/DEPRECATED_BY reconciliation, final state.** B312 originally
introduced this contract backed by a new `SUPERSEDES` rel table (same-type-pair-only,
direction `(newer)-[:SUPERSEDES]->(older)`), which turned out to be the mirror image of
the pre-existing `DEPRECATED_BY` rel table (`(older)-[:DEPRECATED_BY]->(newer)`,
originally covering only `Concept`/`Decision`/`Constraint`/`Lesson` self-pairs) — two
mechanisms for "this was replaced by that" with opposite arrows and no shared write path.
B323's audit (Task 4) flagged the drift and filed the merge as **`backlog/B326.md`** rather
than fixing it in place. B326 landed that merge:

- `DEPRECATED_BY` is now the **only** "replaced by" rel table. It was widened from its
  original four self-pairs to cover every `PROVENANCE_TABLES` entry as a same-type pair
  (`FROM Concept TO Concept, FROM Decision TO Decision, ...`), matching what `SUPERSEDES`
  used to cover. Cross-type supersession/deprecation edges remain out of scope, unchanged
  from both B312 and B323's scope boundary.
- **Direction: `(older)-[:DEPRECATED_BY]->(newer)`** — "A is deprecated by B" — is the
  direction that survived. This is `DEPRECATED_BY`'s *original*, pre-B312 convention, kept
  as-is rather than flipped to match `SUPERSEDES`'s `(newer)->(older)` convention. The
  decision was made by auditing every existing reader/writer: `DEPRECATED_BY` already had
  five independent call sites depending on `(older)->(newer)` —
  `apply_contradiction()` in `campy/brain/temporal_lobe/loop/step7_pathway.py`, the
  Lesson-dedup archival path in `campy/brain/brainstem/sweep.py`, two endpoints in
  `web/server.py` (the graph-view export and the MergeEvent-rollback edge cleanup), and
  `compile_card_context()` in `campy/brain/thalamus/tools/context_tools.py` — while
  `SUPERSEDES` had exactly one writer (`mark_superseded()`) and no readers outside its own
  tests. Flipping `DEPRECATED_BY` would have silently broken all five call sites (a
  wrong-direction Cypher `MATCH` returns zero or wrong rows, not an error); repointing
  `mark_superseded()` to `DEPRECATED_BY`'s existing direction was the strictly smaller,
  safer change.
- `SUPERSEDES` no longer exists. `mark_superseded()` writes `DEPRECATED_BY` directly (see
  below). `init_schema()` migrates any pre-existing `SUPERSEDES` edges on an older database
  into `DEPRECATED_BY` (reversing direction per-table, via a per-`PROVENANCE_TABLES`-table
  `MATCH`/`MERGE` so one table's failure doesn't abort the rest) before dropping the
  `SUPERSEDES` table — no lineage is silently orphaned. See the `DEPRECATED_BY` DDL comment
  and the "B326 — retire SUPERSEDES" step in `schema.py`'s `init_schema()` for the exact
  mechanics.
- The `superseded_by`/`superseded_at`/`supersession_reason` node columns above are
  unchanged by this merge — they remain the fast filter regardless of which rel table backs
  the traversable edge.

### Write-side API (`campy/brain/hippocampus/provenance.py`)

- `provenance_fields(*, source, source_version=None, observed_at=None, evidence_ref=None) -> dict`
  — builds the four provenance params for a `CREATE`, defaulting `observed_at` to
  `now(UTC)` (returned as an ISO-8601 string, matching this codebase's `timestamp($x)`
  convention).
- `async mark_superseded(db, *, table, node_id, superseded_by, reason, at=None) -> None`
  — sets the three supersession columns **and** creates the `DEPRECATED_BY` edge
  (`(old)-[:DEPRECATED_BY]->(new)`, per the B326 update above) in one call, so the two
  halves cannot drift. Raises `ValueError` for a `reason` outside `SUPERSESSION_REASONS` or
  a `table` outside the provenance-tracked set. A caller that sets `superseded_by` directly
  without going through this function (and thus without the matching edge) has introduced a
  bug — the ID becomes a dangling reference instead of traversable lineage.

### Populated at capture time (best-effort, bounded)

Only two write paths populate non-NULL provenance today, per this card's scope:

- `campy/brain/thalamus/tools/lessons.py`: `upsert_lesson` (source defaults from the
  caller's `agent_source` param via the existing `agent:<id>` convention, `evidence_ref`
  defaults to `session_id`), and the Plan/PlanStep/Lesson writes inside
  `_create_plan_graph` / `_store_plan_outcome_lesson` when called with `capture_source`/
  `evidence_ref`.
- `campy/brain/thalamus/tools/capture.py`: `notify_turn` derives `capture_source` as
  `"user:direct"` for user turns or `"agent:<agent_source>"` for assistant turns, and
  threads it (with `evidence_ref=message_id`) into the passive-plan-detection and
  outcome-sense-lesson calls above.

Every other write site (`quests.py`'s `report_outcome`/`register_plan`, the ~500 other
Tier 1/Tier 2 writers) still writes `NULL` provenance. That is intentional — B312 does not
retrofit all write sites, and NULL is the correct value for facts written before this
card landed. Recall paths (`recall_relevant_lessons`, `current_truth`, etc.) must — and
do — tolerate NULL provenance without error; neither reads the provenance columns
directly, so this holds by construction.

### Migration

`schema.py`'s existing additive `_MIGRATIONS` mechanism (`ALTER TABLE ... ADD`, guarded
by `_column_exists()`) carries all 28 tables' worth of new columns — no new migration
path was introduced. `init_schema()` is idempotent and safe to run against an existing
pre-B312 database: node tables use `IF NOT EXISTS`, so pre-existing rows are untouched;
the new columns are added and default to `NULL`.

### Explicitly out of scope for B312

- The `authority` property (projected vs. earned) — **B313**.
- Backfilling provenance onto existing rows.
- Retrofitting provenance into write sites beyond `upsert_lesson` and `notify_turn`.
- Changing `campy/brain/brainstem/sweep.py` to emit `expired` supersessions instead of
  silent `archived` flips.
- Cross-type supersession edges.

## B323 — Task Dependency Graph, Agent Provenance, and Card/Branch Context Bundle

Reconciles against B312 rather than duplicating it. Composes with B322 (learned coupling) —
B322 *learns* dependency from observed co-change; this card *declares* it. Three additions,
all new tables; nothing pre-existing is redefined.

### Task 0 audit findings

Confirmed against `campy/brain/hippocampus/schema.py` before writing any DDL:

- `Workspace`, `ANCHORED_TO`, `DEPRECATED_BY`, `LOADED`, `PRODUCED_LESSON` all already
  existed exactly as the backlog card described.
- `BLOCKS` (`FROM GridEntity TO GridEntity, action_id STRING, step INT32` — ARC puzzle-grid
  mechanics) and `ENABLES` (`FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING,
  inferred_at TIMESTAMP` — concept inference) are untouched by this card. Neither their
  definitions nor any pre-existing edges are affected by `init_schema()` — regression-tested
  in `tests/test_task_dependency.py`.
- No write path anywhere in `campy/` creates an `ANCHORED_TO` edge (confirmed by grep) —
  only the DDL and one read in `hippocampus.py` existed. This made the `ANCHORED_TO` widening
  (Task 2) a defensive, not evidence-based, migration.

### TASK_BLOCKS / TASK_ENABLES — declared task dependency

New rel tables, multi-pair like the pre-existing `DEPRECATED_BY`:

```
TASK_BLOCKS:  FROM MainQuest TO MainQuest, FROM SideQuest TO SideQuest, FROM ActionItem TO ActionItem
TASK_ENABLES: same pairs
```

Edge properties: `declared_by STRING`, `confidence DOUBLE`, `observed_at TIMESTAMP`,
`source STRING`, `source_version STRING` (B312 provenance), `authority STRING` ("earned" for
an agent-declared edge, per B313).

**Cycle safety** (`campy/brain/thalamus/tools/task_graph.py`,
`add_task_dependency_edge()` / `TASK_DEPENDENCY_TABLES`): before inserting
`(from_id)-[:TASK_BLOCKS|TASK_ENABLES]->(to_id)`, a bounded `*1..10` traversal checks for an
existing path from `to_id` back to `from_id` — if found, the edge would close a cycle and is
rejected with `TaskDependencyCycleError` naming the full loop path. A self-edge
(`from_id == to_id`) is rejected the same way without a traversal. This is a bounded check,
not full transitive-closure maintenance — a cycle more than 10 hops away in a same-type
dependency chain would be missed, judged acceptable for hand-declared card dependencies.
`TASK_BLOCKS` and `TASK_ENABLES` are checked independently of each other.

### Workspace / ANCHORED_TO extension

`Workspace` gains `branch_name STRING` and `active BOOLEAN` via the existing additive
`_MIGRATIONS` mechanism — the table itself is never redefined. `ANCHORED_TO` widens from
`FROM MainQuest TO Workspace` to also cover `FROM ActionItem TO Workspace`, via the
drop+recreate `_REL_MIGRATIONS` path (now data-driven over a `"check"` query per entry,
generalized from the single hardcoded `ESTABLISHED_IN` case). Both the fresh-DB `REL_TABLES`
DDL and the upgrade-path `_REL_MIGRATIONS` entry carry the widened definition, matching the
`ESTABLISHED_IN` precedent. Safety: the migration probes for existing `ANCHORED_TO` edges
first and only drops+recreates when none exist; if edges are ever found on a real DB, the
migration is skipped (logged, not silently forced) rather than risking data loss — the same
defer behavior `ESTABLISHED_IN`'s migration already uses.

### AgentWorker + SOLVED_BY — agent-as-node provenance

A third agent-identity mechanism was explicitly rejected. There were already two: B312's
`source` column (`"agent:<id>"` convention) and the pre-existing `agent_source` column on
`WorkArtifact`/`WorkSummary`. This card adds a node type only for what a string column
cannot do — traversing *from* an agent:

- `AgentWorker (worker_id STRING PRIMARY KEY, model_name STRING, provider STRING,
  first_seen_at TIMESTAMP, last_seen_at TIMESTAMP)`
- `SOLVED_BY: FROM Decision TO AgentWorker, FROM ActionItem TO AgentWorker, FROM Lesson TO AgentWorker`
  (`confidence DOUBLE, observed_at TIMESTAMP`) — `SOLVED_BY_TABLES` in `schema.py` is the
  authoritative table/pk map.
- `upsert_agent_worker_and_link()` (`campy/brain/hippocampus/schema.py`) is the single write
  path: it no-ops (never raises) unless `worker_id` follows the `"agent:<id>"` convention and
  `node_table` is in `SOLVED_BY_TABLES` — there is no `AgentWorker` for a human
  (`"user:direct"`) or harvester (`"harvest:*"`) source. `AgentWorker.worker_id` is always the
  identical string a write's B312 `source` column holds; this is asserted directly in
  `tests/test_task_dependency.py`.
- Called in the same write that sets B312 provenance, never as a separate capture pass:
  `campy/brain/thalamus/tools/lessons.py`'s `upsert_lesson()` and
  `_store_plan_outcome_lesson()` call it immediately after the `Lesson` CREATE/UPDATE that
  sets `source`, using that identical value. `capture.py`'s `notify_turn()` also calls it
  after `_store_plan_outcome_lesson()` (surfacing the new `outcome_lesson_id` in its
  response) — a no-op today since that call site is user-turn-only and therefore always
  `"user:direct"`, but kept for when that guard changes rather than adding the wiring later.
  **Deviation from the card's file list:** the card's "Files to Modify" named only
  `capture.py` for this task, but capture.py's own writes never carry non-NULL agent-sourced
  provenance on a `SOLVED_BY`-covered table — the real write site is `lessons.py`'s two
  functions above (`upsert_lesson` is explicitly one of B312's two named capture paths). This
  card therefore also touches `campy/brain/thalamus/tools/lessons.py`, which was necessary to
  make the "same write as B312 provenance" requirement (and its acceptance criterion) true
  rather than aspirational.

### DEPRECATED_BY / SUPERSEDES reconciliation (Task 4)

B312 landed with a `SUPERSEDES` rel table whose arrow direction
(`(newer)-[:SUPERSEDES]->(older)`) mirrors the pre-existing `DEPRECATED_BY` table
(`(older)-[:DEPRECATED_BY]->(newer)`) in reverse, with no shared write path — drift this
card was written to catch. The preferred fix (extend `DEPRECATED_BY`, retire `SUPERSEDES`)
was **not** applied in this card: B312 had already landed with `SUPERSEDES` live
(`mark_superseded()` writing it, `tests/test_provenance.py` exercising it) by the time this
card's audit ran, and merging two live rel tables in place is a schema-safety decision that
deserves its own audited card rather than a drive-by inside this one — exactly the situation
the B323 card text anticipated ("if B312 has already landed, file the reconciliation as a
follow-up and say so — do not silently add a third mechanism"). No third mechanism was
added. The merge is tracked as **`backlog/B326.md`**; `backlog/B312.md` was updated in this
same change to record the decision. Until B326 lands, `SUPERSEDES` and `DEPRECATED_BY` both
exist and neither writes the other.

### compile_card_context — card/branch context bundle

New tool (`campy/brain/thalamus/tools/context_tools.py`, registered in `TOOL_HANDLERS`):
`compile_card_context(params, db, config)`, `params: {target_id, max_hops?}`.

- **Resolution**: `target_id` is matched first against a card
  (`MainQuest`/`SideQuest`/`ActionItem`, exact match on `name`/`text_raw` then a `CONTAINS`
  lexical fallback mirroring quests.py's B303 card-identifier convention), then against
  `Workspace.branch_name`. Cards win on ambiguity. The response's `interpreted_as` field
  always says which table/column resolved the target, so a caller is never guessing.
- **Bounded traversal**: expands `TASK_BLOCKS` / `TASK_ENABLES` / `ANCHORED_TO` one hop at a
  time in a Python-driven BFS (`_card_context_dependency_hop`), both directions, from the
  resolved node outward. `max_hops` defaults to 3 and is clamped to a hard cap of 5
  (`max_hops=99` clamps to 5). No Cypher `*` (bounded or unbounded) appears anywhere in the
  issued queries — each hop is a single fixed-depth `MATCH` per (node, rel type, direction);
  the bound comes from the Python loop, not the query. `tests/test_card_context_bundle.py`
  asserts this directly by capturing every issued query and checking none contain `*`.
  Rediscovering the same underlying edge from both endpoints (inherent to a bidirectional
  BFS) is deduplicated by normalizing each edge to its true DB direction before recording it.
- **Content on everything reached**: for every `MainQuest` reached (including the target
  itself), `PRODUCED_LESSON` edges pull its Lessons; for each such Lesson,
  `DEPRECATED_BY` is checked in both directions (this Lesson deprecated by something newer,
  or deprecating something older) and `SOLVED_BY` attribution is pulled. `SOLVED_BY` is also
  pulled directly for any reached `ActionItem`/`Decision` (the other `SOLVED_BY_TABLES`
  members). `DEPRECATED_BY` only fires here for `Lesson` nodes reached via
  `PRODUCED_LESSON` — `MainQuest`/`SideQuest`/`ActionItem` themselves are not
  `DEPRECATED_BY`-covered tables, so a quest/action-item's own supersession status isn't
  applicable and is correctly absent.
- **Structured + Markdown**: returns `bundle` (a `bundle_compiler.ContextBundle.to_dict()`,
  reusing that module's `BundleSection`/`ContextBundle` shapes rather than inventing a
  second bundle representation) and `markdown` (rendered from that same structure by a
  dedicated section-type renderer in `context_tools.py`, mirroring
  `ClaudeCodeFormatter._format_section`'s per-section-type convention rather than routing
  through the `formatters/` package, whose section vocabulary — `exact_fact`/`semantic`/
  `graph`/`tabular`/`summary` — is shaped for the free-text-query bundle, not this one's
  `target`/`dependencies`/`lessons`/`superseded`/`attribution` sections).
- **Fail-open (B318)**: the entire hop-traversal loop is wrapped in one `try`/`except` in
  `compile_card_context` itself; a failure there sets `dependency_traversal_failed: true` in
  the response and the bundle keeps only its `target` section — no exception propagates to
  the caller. Only a missing or unresolvable `target_id` returns an `{"error": ...}` dict;
  a resolved target whose traversal fails never does.

## AWS Bedrock LLM Provider (B324)

A Campy deployed inside a customer's AWS account (see B315/B316) has no local Ollama —
an ECS task cannot reach `http://localhost:11434/v1`, so the synthesis path (`ask`,
consolidation, lesson synthesis) was dead in any cloud deployment until this card. Bedrock lets
Campy use whatever models the customer's Bedrock account already exposes, inheriting the
model-governance decision (access, guardrails, logging, region, data residency) that customer
made at the Bedrock level rather than routing around it. `ollama` remains the default provider;
Bedrock is opt-in.

**Why a sibling class, not a fifth `OpenAI(base_url=...)` branch.** Every other provider in
`campy/brain/llm/provider.py` is constructed as `OpenAI(base_url=..., api_key=...)` because
Ollama/OpenAI/Anthropic/Google all expose (or shim) the OpenAI chat-completions wire format.
Bedrock does not — it is `bedrock-runtime` with SigV4 auth and its own request/response shapes.
`campy/brain/llm/bedrock.py` implements `BedrockLLMClient`, a class satisfying the same
interface (`chat()`, `chat_with_usage()`, `achat()`, `achat_with_usage()`, `last_usage`) that
`LLMClient` does, over `boto3.client("bedrock-runtime").converse(...)`.

**Interface extraction.** `create_llm_client()` / `create_llm_client_for_step()` in
`provider.py` are typed to return `LLMClientProtocol` (a `typing.Protocol`) rather than the
concrete `LLMClient` class, so callers holding the return value don't need to know which
provider they actually got. `create_llm_client_for_step()` delegates to `create_llm_client()`
for provider dispatch (it only resolves per-step config overrides), so Bedrock support did not
need to be duplicated there.

**Why Converse, not `InvokeModel`.** `InvokeModel` requires a different request/response body
per model family (Anthropic, Llama, Mistral, Titan, Nova all differ) — per-family branching
that breaks whenever the customer picks a different model. Converse normalizes all of them
behind one request shape, which is the actual requirement here: the customer chooses the
model, Campy does not.

**Message translation (OpenAI-style → Converse).**

- `{"role": "system", "content": ...}` messages are lifted out of `messages` entirely and
  passed as the top-level `system=[{"text": ...}, ...]` parameter — Converse has no `system`
  message role.
- Every remaining message's string `content` is wrapped as `[{"text": ...}]`.
- Converse requires strict user/assistant alternation and rejects consecutive same-role
  messages; adjacent same-role messages are merged into one message with multiple content
  blocks before sending.
- `temperature` is nested under `inferenceConfig`, not passed at the top level.
- Usage comes back as `response["usage"]` with `inputTokens` / `outputTokens` / `totalTokens`,
  mapped to the `prompt_tokens` / `completion_tokens` / `total_tokens` keys B180's usage
  tracking already expects — `last_usage` behaves identically regardless of provider.
- Response text is read from `response["output"]["message"]["content"][0]["text"]`; an empty
  `content` list returns `""` instead of raising `IndexError`.

**Auth — no stored secret.** Bedrock has no `api_key` config key. `create_bedrock_client()`
uses `boto3.Session(profile_name=...)` and boto3's default credential chain: the ECS task role
in deployment, the developer's local profile/SSO/env credentials otherwise. This is what makes
Bedrock compose naturally with B315/B316 — the same IAM identity that scopes the workspace also
authorizes the model call, with nothing for Campy to store or rotate.

**Config (`config["llm"]`):**

```toml
[llm]
provider = "bedrock"
model    = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"   # or any Bedrock model id
region   = "us-east-1"          # optional; falls back to AWS_REGION / boto3 default
profile  = "..."                # optional, local dev only — not used in ECS
```

`timeout_seconds` / `max_retries` — the same keys every other provider reads — are honored via
botocore's `Config(read_timeout=..., retries={"max_attempts": ...})`, so behavior matches the
rest of the file.

**Inference profile errors are translated, not surfaced raw.** Bedrock has both bare model IDs
and cross-region *inference profile* IDs prefixed by geography (`us.`, `eu.`, `apac.`). Several
current models are only invocable via an inference profile; passing the bare ID returns a
`ValidationException` that does not explain this. `BedrockLLMClient` detects that specific
failure (matching on Bedrock's known "on-demand throughput isn't supported ... inference
profile" wording) and raises `BedrockInferenceProfileError` naming the likely fix — prefixing
the model ID with a geography — rather than surfacing the raw boto error.

**`boto3` is an optional dependency.** It is declared under the `bedrock` extra in
`pyproject.toml` (`pip install 'hippocampy[bedrock]'`) and imported lazily inside
`bedrock.py`/inside the `"bedrock"` branch of `create_llm_client()` — never at module import
time. A machine that never installed boto3 can still `import campy.brain.llm.provider` and use
every other provider; only asking for `provider = "bedrock"` without boto3 installed raises a
message naming the extra to install (caught by the same try/except that already returns `None`
for any unavailable provider, so callers keep the existing graceful-degradation contract).

**Installer + smoke test.** `campy/cli/install.py`'s guided installer (`run_install()`) adds a
third LLM provider choice — "AWS Bedrock (uses your AWS credentials — no API key)" — handled by
`BedrockInstaller`, which prompts for region, model ID, and an optional named AWS profile, and
never prompts for an API key. `verify_llm_connectivity()` and
`campy/cli/smoke_test.py::check_bedrock()` both validate Bedrock reachability via the
control-plane `list_foundation_models()` call rather than invoking a model — consistent with the
existing smoke test's reasoning for BYOK providers ("we don't want to burn tokens on a smoke
test"). `campy/cli/setup.py` does not prompt for a provider (it registers adapters against
whatever `campy.toml` already has); it now documents that Bedrock is configured via
`campy install`, not `campy setup`.

### Embeddings decision — deliberately NOT moved to Bedrock

This card does **not** move embeddings to Bedrock, and that is a considered decision, not an
oversight:

- `campy/brain/hippocampus/graph/embeddings.py` uses a local embedding model
  (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim — run via `fastembed`/ONNX Runtime as of
  B355, previously PyTorch/`SentenceTransformer`; same model, same output, see B342/B353/B355
  below), and **every embedding column across ~53 node tables in `schema.py` is `FLOAT[384]`**,
  with Kùzu HNSW indexes built on that fixed dimension. `schema.py` has a startup dimension
  check specifically to stop a mismatched model from corrupting the index.
- No Bedrock embedding model outputs 384 dimensions: Titan Text Embeddings V2 supports
  1024/512/256, Cohere Embed outputs 1024. Switching embeddings to Bedrock is therefore not a
  provider swap — it is a schema migration across every embedding column, a full re-embed of
  the existing graph, and an index rebuild, with silently-degraded recall if any part is missed.
- **Recommendation: keep the local embedding model even in cloud deployments.** It is a small
  CPU model, and as of B355 the embedding backend itself contributes roughly 6.5x less footprint
  than the PyTorch stack this recommendation originally weighed (~186MB vs. ~1.22GB, measured on
  top of the daemon's other fixed costs — see B355's correction note for the full accounting; an
  earlier draft of this section cited a 228MB whole-daemon figure that was an isolated-test
  artifact, not the real daemon's baseline). It runs fine in a container and avoids the dimension
  problem entirely either way. Revisit only if a deployment forbids shipping model weights — and
  then as its own card with an explicit re-embed plan, not folded into a provider card.

**Cost this recommendation used to carry, resolved by B355.** This section originally flagged
that `sentence-transformers==3.3.1` pulled in `transformers`, which carried several HIGH
`pip-audit` advisories with no available fix at the time — a real dependency-posture concern for
any container shipped to a customer. B355 (2026-08-22) replaced that stack with `fastembed`/ONNX
Runtime, which does not depend on `transformers` at all; that specific advisory surface is gone
from this dependency tree, not merely mitigated. The `starlette` posture note (pulled in via
`fastapi`) is unrelated and still stands as its own follow-up for a cloud deployment's dependency
review.

**Explicitly out of scope for B324:** Bedrock Guardrails, model-invocation logging, and
provisioned throughput are not implemented (Guardrails is a plausible follow-up for a governed
deployment — it's a `converse()` parameter, so this card's shape accommodates it later).
Streaming (`converse_stream`) is not added — Campy's synthesis path is non-streaming today.
Bedrock Agents/Knowledge Bases are out of scope — this card is model inference only. The default
provider is unchanged (`ollama`); Bedrock is opt-in.

## B313 — Authority: Projected vs Earned Memory

Depends on B312 (reuses `source` and `source_version`). Answers the question B312 left open
(see B312's "Explicitly out of scope" list above): not every fact-bearing row is something
Campy alone knows. Some are mirrors of a catalog, record, or run history owned by another
system. `CLAUDE.md`'s "KuzuDB is the single source of truth for all persistent agent state"
rule is correct for the former and wrong for the latter — holding a mirrored fact as if Campy
were its source of truth creates exactly the "second, silently-stale authority" failure mode
governed platforms reject. `authority` gives the two kinds of fact a shared graph without a
shared authority contract.

### The `authority` column

One column, same table set as B312 (`schema.PROVENANCE_TABLES` — Tier 1 fact-bearing tables
plus the Tier 2 Arc\* learned-pattern tables):

| Column | Type | Values |
|---|---|---|
| `authority` | `STRING` | one of `schema.AUTHORITY_VALUES` — `earned` \| `projected` |

- **`earned`** — the fact exists nowhere else; Campy is the only place it lives, and losing
  the row loses it permanently. This is the default, and it is the conservative one: treating
  a projected fact as earned merely backs up something that didn't need it, while treating an
  earned fact as projected risks *deleting something unrecoverable* during a `drop_projections()`
  rebuild. When in doubt, a row reads as earned.
- **`projected`** — the fact is a mirror of something owned elsewhere (a harvested capability
  catalog, another service's App/Iteration records, workflow-engine run history, ...). A
  projected fact is only meaningful if it can actually be rebuilt, so it **requires** non-NULL
  `source` and `source_version` — see "Write-time invariant" below.

`authority_of(row) -> str` (`campy/brain/hippocampus/provenance.py`) is the single NULL-safe
read path: a NULL/missing column, an unrecognized value, or a genuinely absent row all read
back as `"earned"` — the same conservative default, applied uniformly rather than scattered as
`row.get("authority") or "earned"` across call sites. Pre-B313 rows (and any row from a table
whose local schema predates this migration) are NULL and therefore read as earned, which is
correct: they were never anything but earned.

### Write-time invariant (`validate_authority()`)

```python
def validate_authority(authority: str, source: str | None, source_version: str | None) -> None
```

Raises `ValueError` when `authority == "projected"` and either `source` or `source_version` is
NULL/empty — without both, "this is rebuildable from the source" is an unverifiable claim.
`authority == "earned"` has no such requirement (there is nothing external for an earned fact
to point at). `provenance_fields()` (B312's write helper) grew an optional `authority` kwarg
that runs through this validation when passed; when omitted (every pre-B313 call site), the
returned dict is byte-for-byte what it was before this card — `authority` is left out of the
dict entirely rather than defaulted in, so the column is written NULL and reads back as earned
via `authority_of()`. No existing caller had to change.

### Two read paths that make the property useful (`provenance.py`)

- `async find_stale_projections(db, *, source, current_version, tables=None) -> list[dict]` —
  every projected fact from `source` whose `source_version` no longer matches
  `current_version`. This is what turns projection drift from an invisible risk into a report:
  "show me everything Campy is still presenting as current that the source has since moved
  past." Rows with a NULL `source_version` are excluded (not reported as stale) — that state
  should be unreachable through `validate_authority()`, so it's a pre-B313 anomaly this
  function doesn't try to diagnose.
- `async drop_projections(db, *, source, dry_run=True, tables=None) -> dict` — deletes every
  `projected` row from one `source` so it can be safely re-projected. The single most
  dangerous function this card adds, so it carries three safeguards: the delete (and the count
  behind it) always filters on `authority = 'projected' AND source = $source` together, never
  on `source` alone; `dry_run` defaults to `True`; and the return shape
  `{"deleted": N, "skipped_earned": M}` surfaces `skipped_earned` explicitly so a caller can
  see the authority filter actually excluded something, not just trust that it would have.

Neither function is a scheduled job — B313 establishes the query and the safe-delete
primitive; running them on a schedule, and the harvester that would actually write `projected`
rows in the first place, are both future work.

### Recall surfaces authority (`current_truth`, `bundle_compiler`)

`current_truth` (`campy/brain/thalamus/tools/retrieval.py`) includes `authority` in every
result row alongside `confidence`, read via `authority_of(node)` off the already-fetched node
dict — no extra query. `bundle_compiler`'s `_stage_exact_facts` / `_stage_semantic_context`
(`campy/brain/thalamus/bundle_compiler.py`) do the same for `GlobalConstraint`/
`GlobalPreference`/`Concept`/`Decision`/`Constraint`/`Requirement`, but those two stages
project named columns in their Cypher (`RETURN n.text_raw as text, ...`) rather than the whole
node, and Kùzu raises a binder error on a `RETURN`ed property a table's schema doesn't have.
Reduced test fixtures (and any local schema that predates this card) don't have `authority`,
so both stages first check for the column (`_table_has_authority()`, a `CALL table_info(...)`
probe mirroring `schema.py`'s `_column_exists()`) and fall back to defaulting every row's
`authority` to `"earned"` when it's absent, rather than raising and losing the whole section.
This card does not re-rank or filter on `authority` — it is visible, not yet actionable.

### Export/backup: earned by default

`campy/brain/hippocampus/graph/export.py`'s `export_graph_dump()` / `export_graph()` both
gained `include_projected: bool = False`. Default excludes rows where `authority = 'projected'`
(rows with NULL `authority` are still included — NULL reads as earned) from every
`PROVENANCE_TABLES` table; every other table is unaffected, since only that table set carries
the column at all. The rationale mirrors the column's own: a disaster-recovery export exists
to protect memory that cannot be reconstructed. A projected fact is by definition reconstructible
from its source, so the default export is smaller with no loss of anything actually
irreplaceable; pass `include_projected=True` for a full mirror. `import_graph_dump()` needs no
code change to tolerate an earned-only dump — a `PROVENANCE_TABLES` table's JSONL file simply
has fewer rows, not a missing file, and a relationship whose endpoint was an omitted projected
row fails its `MATCH` during `_create_relationships()` and is silently skipped (standard Cypher
semantics: zero `MATCH` rows means the paired `CREATE` never fires), not an error.

### Explicitly out of scope for B313

- No harvester or projection-ingest path — nothing writes `projected` facts today except
  tests. This card establishes the contract; the first real producer is future work.
- No re-ranking or filtering of recall by `authority`.
- No scheduled drift detection — `find_stale_projections()` is a function, not a background
  job.
- No change to what `archived` means or how `campy/brain/brainstem/sweep.py` behaves.

## B320 — Idempotent Writes: Content-Addressed Deduplication

Retried captures (timeout, dropped socket, an ambiguous error under B318's fail-open
transport) are correct client behavior that Campy cannot prevent. Before this card, every
write minted a fresh `uuid4()` primary key, so the same fact captured twice became two
unrelated nodes — inflating recall bundles and corrupting every frequency-derived signal
(`pathway_strength`, valence aggregation, consolidation clustering) into treating a network
blip as reinforcement.

**The constraint that shapes this card, unchanged from the backlog card:** Kùzu 0.11.3
cannot alter a primary key in place — changing one means dropping and recreating the table,
destroying every existing edge into it. So primary keys stay exactly `uuid4()` as before;
dedup happens on a new additive `content_hash` column instead.

### `content_hash` column

One column, added to `schema.CONTENT_HASH_TABLES` — a **narrower** set than B312/B313's
`PROVENANCE_TABLES`: the 21 Tier 1 claimed/observed-fact tables only (`Concept`, `Decision`,
`Constraint`, `Requirement`, `ActionItem`, `GlobalConstraint`, `GlobalPreference`, `Lesson`,
`Procedure`, `KnowledgeGap`, `Plan`, `PlanStep`, `Hypothesis`, `ActionFact`, `ActionEffect`,
`VictoryCondition`, `Rule`, `Transition`, `DocumentExtract`, `WorkSummary`, `WorkArtifact`).
The Tier 2 Arc\* learned-pattern tables are deliberately excluded — this card only wires
dedup-on-write into `capture.py`/`lessons.py`, so extending the column to tables nothing
writes it to yet would be dead schema. `CONTENT_HASH_TABLES` is computed as "every
`PROVENANCE_TABLES` entry that isn't an `Arc*` table" so it stays in lockstep with
`PROVENANCE_TABLES` if Tier 1 ever grows, rather than being a second hardcoded list that can
drift from the first.

| Column | Type | Meaning |
|---|---|---|
| `content_hash` | `STRING` | sha256 identity hash of the fact's canonical (table, text, source, workspace_id, extra) tuple. `NULL` on every pre-B320 row. |

Added both directly in `NODE_TABLES`' DDL (for fresh installs) and via `_MIGRATIONS`
(`ALTER TABLE ... ADD`, guarded by the existing `_column_exists()` check) for upgrades —
the same two-mechanism pattern B312/B313 used, for the same reason: a fresh `CREATE TABLE`
already has the column so the migration is a no-op there, while an existing database only
gains it through the `ALTER`.

**No backfill.** `content_hash` is never computed for existing rows — a backfill would
surface pre-existing duplicates and invite an automated merge, which is a destructive
operation against real user memory that belongs in its own card with its own dry-run and a
human in the loop. `NULL` means "written before B320" and is guaranteed to never match
anything (see below) — it is not treated as a wildcard or an implicit empty-string hash.

### The hash contract (`campy/brain/hippocampus/provenance.py`)

`content_hash(*, table, text, source, workspace_id="local", extra=None) -> str` — a pure
function (no clock, no randomness, no I/O) returning a 64-character lowercase hex sha256
digest, stable across process restarts and calls separated in time by construction.

**Included** (this is what "the same fact" means):

- `table` — a `Concept` and a `Lesson` with identical text are not the same fact.
- `text`, normalized via `_normalize_text_for_hash()`: Unicode NFC, leading/trailing
  whitespace stripped, internal whitespace runs collapsed to a single space. **Case is
  preserved, never folded** — case can be semantically load-bearing (code, identifiers,
  proper nouns), and lowercasing would silently merge facts a caller means to keep distinct.
- `source` — the B312 provenance source string. The same text asserted by two different
  sources is two different facts, not a duplicate to collapse.
- `workspace_id` (default `"local"`) — the same fact learned in two workspaces stays two
  distinct facts: different owners, different lifecycles, and (per B316) different
  databases entirely.
- `extra` — optional caller-supplied discriminators, canonicalized as
  `json.dumps(extra, sort_keys=True, separators=(',', ':'))` so key order never affects the
  hash.
- `CONTENT_HASH_VERSION` (currently `1`) — folded into the hashed payload itself, so bumping
  the constant re-partitions every future dedup decision instead of silently colliding old
  and new hashes for text the rules now treat differently. Treat this constant, and the
  canonicalization rules above, as a versioned contract — changing what "the same fact"
  means is a deliberate, visible act (a version bump), never a silent drift.

**Excluded** — anything that legitimately varies between a call and its retry, because
including it would make the hash useless (a retry producing a *different* hash is exactly
the bug this card exists to fix): `observed_at`, `created_at`, `session_id`, `message_id`,
embeddings, `confidence`, and every uuid.

`resolve_dedupe_key(..., idempotency_key=None)` is the key a write helper actually dedupes
on: `content_hash()` unless the caller supplies `idempotency_key`, which replaces it
entirely. This is the floor-vs-ceiling split the card calls for — content hashing is the
floor every caller gets for free, while a well-behaved client that already tracks its own
logical-write identity can guarantee exact-once semantics even when its retry's text
differs slightly (content hashing alone can't catch that). An explicit `idempotency_key` is
stored prefixed `idemp:` — a namespace disjoint from `content_hash()`'s raw 64-hex-char
digests, so a caller-chosen key can never accidentally collide with a hash computed for
unrelated content.

`find_live_by_dedupe_key(db, *, table, pk_column, dedupe_key, touch_last_accessed=False)` —
the lookup side. Two things are true by construction, not convention:

- `n.content_hash = $key` — Kùzu's `=` against a `NULL` operand is never true, so every
  pre-B320 row is excluded automatically; there is no separate `IS NOT NULL` guard to forget.
- `n.superseded_by IS NULL` — a superseded row (B312) is excluded, so re-capturing content
  identical to a fact that has since been superseded creates a fresh live node instead of
  resurrecting the dead one.

### Dedupe-on-write and the reinforcement judgement call

Before inserting a fact-bearing node in a converted write path: compute the dedupe key, look
for a live match, and if found, **do not insert** — return the existing node's id instead,
in a shape indistinguishable from a fresh insert. A retrying caller cannot tell it was
deduped: no exception, no warning, same response keys.

**A dedup hit never bumps `pathway_strength`.** A genuine re-observation arguably *is*
reinforcement, while a retry is not, and content alone cannot distinguish the two. The card
defaults to *not* reinforcing: under-counting reinforcement is recoverable (a later, clearly
distinct observation still reinforces normally), while inflating it from a network retry
poisons ranking in a way nothing later can undo. Where a table has a `last_accessed_at`
column (`Concept` does — though `Concept` writes are not converted by this card, so nothing
currently exercises this path), `find_live_by_dedupe_key(..., touch_last_accessed=True)` may
refresh *only* that column on a hit, never `pathway_strength`.

**Dedup lookups fail open.** Every call site wraps the `find_live_by_dedupe_key()` lookup in
a `try`/`except` that falls back to `existing = None` (i.e. proceeds with a normal insert) on
any error. Dedup is a best-effort optimization on the primary capture path, never a hard
dependency of it — matching the existing try/except-around-optional-enhancement style
already used throughout `notify_turn` (warm frontier, proactive push, and friends). This is
also what makes the feature safe against a caller (or test double) whose `db` doesn't
implement `execute_read`.

### Scope: `capture.py` and `lessons.py` only

The same two write paths B312 named as the primary capture path — `capture.py`'s
`notify_turn` (and the two functions it calls into for Tier-1 writes,
`_maybe_create_passive_plan_from_turn` → `lessons._create_plan_graph`, and the outcome-sense
branch → `lessons._store_plan_outcome_lesson`) — plus `lessons.upsert_lesson` directly.
`sweep.py`, `temporal_lobe/loop/*`, and `dictionary.py` are untouched: those are internal
consolidation paths the daemon itself controls, where a retry is not the failure mode this
card is defending against. They can be converted later against this same pattern if they
prove to need it.

Both `_create_plan_graph` and `_store_plan_outcome_lesson` only activate dedup when the
caller supplies `capture_source` or `idempotency_key` — which is true for every call from
`notify_turn` (it always derives a non-empty `capture_source`), but false for `quests.py`'s
`register_plan`/`report_outcome`, which pass neither. Those callers see **zero** behavior
change from this card: `content_hash` stays `NULL` on their writes, and every call inserts,
exactly as before B320. This is a deliberate scope fence, not an oversight — quests.py's
callers are explicit user-declared actions (`register_plan`), not retriable network-facing
captures.

`upsert_lesson` applies content-hash dedup only when the caller omits `lesson_id` — an
explicit `lesson_id` is already a stronger identity mechanism than content hashing (the
pre-existing match-by-id branch, unchanged by this card, including its
`pathway_strength += 0.1` reinforcement on update) and silently redirecting an explicit-id
call to a different node because its content happens to match would violate the caller's
stated intent.

### What this card does not do

- Does not change any primary key.
- Does not backfill `content_hash` onto existing rows.
- Does not merge or clean up duplicates that already exist in a user's graph — a destructive
  operation against real memory that needs its own card, its own dry-run, and a human in the
  loop.
- Does not convert `sweep.py`, `temporal_lobe/loop/*`, or `dictionary.py`.
- Does not do semantic/near-duplicate detection — this is exact-content dedup only.
  `capture.py`'s pre-existing B279 cosine-similarity guard (>0.90 against recent `Plan`
  embeddings, inside `_maybe_create_passive_plan_from_turn`) is a *different*, fuzzier
  mechanism the two are complementary rather than redundant: B279 catches "a
  differently-worded restatement of the same plan", B320 catches "the exact same capture,
  retried". Embedding-similarity merging elsewhere in Campy (`MergeEvent`,
  `DisambiguationEvent`) is likewise a separate mechanism with different risks.

## B314 — GraphGateway: Named-Query Chokepoint + Raw-Cypher Ratchet

`campy/brain/hippocampus/graph/kuzu_client.py`'s docstring has always claimed *"THIS IS THE
ONLY FILE THAT IMPORTS KUZU. Migration to Neo4j or another provider = rewrite this file
only."* The `import kuzu` half of that was always true. The rewrite-one-file half was not:
Cypher text was written inline at every call site across the codebase and passed straight
through `KuzuClient.execute()`/`execute_read()`/`execute_write()` as strings — measured at
~500+ lines across 46 files at the time this card was written. Kùzu is pinned at `0.11.3` and
was archived upstream in Oct 2025, which makes that not a hypothetical risk. Separately, a
chokepoint is the only place a future tenant-visibility predicate (B316, workspace router)
can be injected reliably — enforcing it at 500 call sites individually is not auditable;
enforcing it at one is.

A single card cannot safely migrate 500 query sites. B314 builds the seam, proves it on one
vertical slice, and installs a ratchet so the count can only go down from here. Bulk
migration is follow-up work, one module at a time.

### `GraphGateway` / `NamedQuery` / `QueryRegistry`

New module `campy/brain/hippocampus/graph/gateway.py`:

- **`NamedQuery`** (frozen dataclass): `name` (dotted, `<domain>.<verb>_<subject>` —
  e.g. `"lessons.recall_by_similarity"`), `cypher` (a static parameterized template —
  all variable input goes through `$param`, never string interpolation), `params` (the
  declared, required parameter names), `mutating` (routes to `execute_write` vs
  `execute_read`), `description` (one line). Validated in `__post_init__`, so a bad query
  raises at import time, not in production: non-static/empty cypher, a bare `{` that isn't
  part of a Kùzu literal property map (the signature of a leftover, unresolved format
  placeholder — e.g. `f"MATCH (a:{table})"` left half-built), params not a `tuple[str,
  ...]`, or a missing description.
- **`QueryRegistry`**: holds `NamedQuery` objects keyed by name; `register()` raises on a
  duplicate name.
- **`GraphGateway`**: wraps a `KuzuClient` + `QueryRegistry`.
  - `run(name, /, **params)` — the sanctioned path. Looks up `name` (raises `KeyError`
    naming it if unregistered), validates the caller's kwargs against the query's declared
    `params` *before touching the database* (raises `TypeError` on any mismatch, missing or
    unexpected), then routes to `KuzuClient.execute_write()` (mutating queries — preserving
    the existing per-event-loop asyncio write-lock discipline in `_get_write_lock()`, never
    bypassed) or `KuzuClient.execute_read()` (reads — materialized dict rows, keyed by each
    RETURN clause's alias).
  - `execute_raw(cypher, params, *, mutating, reason)` — the escape hatch. `reason` is a
    required keyword (omitting it is a `TypeError`) and is logged; every call is migration
    debt, counted by the ratchet below.

Registry organization: one module per domain under
`campy/brain/hippocampus/graph/queries/` (`lessons.py` today; `quests.py`, `retrieval.py`,
... as follow-up cards migrate them), each exporting a tuple of `NamedQuery` objects,
assembled into one process-wide `REGISTRY` in `queries/__init__.py`.

### The proof slice: `campy/brain/thalamus/tools/lessons.py`

Every one of the file's ~41 Cypher lines moved into
`campy/brain/hippocampus/graph/queries/lessons.py` as 27 `NamedQuery` objects (a few 1:1;
plan/lesson writes decompose into more, smaller named steps than the original inline blocks
had). The tool functions call `gateway.run("lessons.…", …)` instead of building Cypher
strings. A module-level `_gateway(db)` helper wraps whatever `db` a caller passes (a
`KuzuClient`, or already a `GraphGateway`) — this keeps every public function's signature
exactly `async def x(params: dict, db: KuzuClient, config: dict)`, unchanged, because ~14
tool modules and the daemon dispatch depend on that shape (changing it is B315's job, not
this card's).

Two internal helpers changed shape to fit the chokepoint: `_plan_feedback_from_similarity`
became `async` (it wasn't before) so its one Cypher read could go through `gateway.run()`
like everything else in the file — its sole caller, `quests.py`'s `register_plan`, already
awaits everything else in its own async body, so this was a one-line `await` addition at
that call site. `_synthesize_lesson`'s per-artifact-table read loop (`Decision`,
`Constraint`, `Requirement`) became three separate static named queries instead of one
f-string-templated `MATCH (a:{table})` — table names aren't parameterizable in Cypher, and a
templated table name is exactly the kind of call-site interpolation `NamedQuery`'s
bare-brace check exists to catch.

**A behavior-preservation subtlety worth recording:** several reads in this file previously
called the raw synchronous `KuzuClient.execute()` and drained a `has_next()`/`get_next()`
cursor by hand — a different, lower-level path than `execute_read()`'s materialized,
column-aliased dict rows. Routing every read through the gateway means every read now goes
through `execute_read()` uniformly. That's a genuine, deliberate call-path change (not just a
textual relocation), so the pre-existing hand-rolled test doubles that mocked the raw
`execute()`/cursor shape directly (`tests/test_scene_graph_priors.py`'s `_DB`,
`tests/test_lesson_artifact.py`'s domain-recall test) were updated to expose an async
`execute_read` returning the same fixture data as materialized dict rows instead — the
tool's externally observable return values are unchanged; only the internal double's shape
is. Fakes that never actually reach these particular reads in their exercised paths
(`tests/test_plan_tools.py`'s `MockDB`, `tests/test_recall_contract.py`'s
`RecallContractDB`) needed no change: the calls they'd otherwise miss are already
inside this file's existing best-effort `try`/`except` blocks, so an unimplemented method on
an old-style fake is swallowed exactly as an empty/no-match result already was.

### The ratchet: `scripts/check_cypher_ratchet.py` + `scripts/cypher_baseline.json`

Counts, over `campy/**` and `scripts/**` (deliberately **not** `tests/**` — fakes, mocks, and
real-`KuzuClient` integration tests legitimately contain Cypher text and aren't part of the
"500 call sites to migrate" problem):

1. Lines matching `MATCH `/`CREATE `/`MERGE ` outside the allowlist.
2. `GraphGateway.execute_raw(` call sites, everywhere (allowlisted or not — the escape hatch
   is debt wherever it's used).

Both counts are compared against the checked-in baseline (`scripts/cypher_baseline.json`);
the script exits non-zero if *either* increased, prints the offending files, and only
rewrites the baseline when run with `--update` — so lowering the bar is always a deliberate,
reviewable commit, never a silent side effect of `--update` being run by habit. Wired as
`make check-cypher` and as a step in `.github/workflows/tests.yml` (alongside B293's
generated-tools-drift check, the closest existing precedent for "a non-pytest script that
must pass in CI").

**Allowlist, with reasons (per Task 3 — neither of these gets migrated):**

- `campy/brain/hippocampus/schema.py` — its Cypher is DDL (`CREATE NODE TABLE`, `ALTER
  TABLE`), which is inherently engine-specific and correctly lives next to the engine
  adapter, not behind a portability seam meant for application-level queries.
- `campy/brain/hippocampus/graph/kuzu_client.py` — the one file that imports `kuzu`. Its
  Cypher is engine plumbing (`CALL CREATE_VECTOR_INDEX`, `CALL QUERY_FTS_INDEX`, schema
  introspection) that `GraphGateway` itself is built on top of; routing it back through the
  gateway would be circular.
- `campy/brain/hippocampus/graph/queries/**` — this is where migrated Cypher is supposed to
  live; counting it as debt would be counting the fix as the problem.

The line-based counting is deliberately blunt (matching the card's own original
measurement methodology) — it will count an English-language comment that happens to
contain the word "Create" as a line. That's fine for the ratchet's job (a monotonic
direction signal across the whole tree); it is *not* the mechanism that proves `lessons.py`
itself is fully migrated. That's `tests/test_graph_gateway.py`'s
`test_lessons_module_calls_no_raw_kuzu_execute_methods`, which greps for the precise thing
that actually matters — no remaining `db.execute(`/`db.execute_write(`/`db.execute_read(`
call sites in that file.

### What this card does not do

- Does not migrate the other ~32 files with inline Cypher — follow-up cards, one module at a
  time; the ratchet enforces the count can only go down from here.
- Does not migrate `schema.py`'s DDL (allowlisted by design — see above).
- Does not add a second storage backend — the portability seam exists; no adapter is built.
- Does not change any tool function's `(params, db, config)` signature — that's B315.
- Does not inject any tenant/workspace-visibility predicate yet — that's B316, which depends
  on this seam existing (`GraphGateway.run()` is the one place such a predicate could be
  added later without touching every call site again).

## B319 — Backup and Restore for Earned Memory

B313 split Campy's facts into `earned` (Campy is the only place it lives — losing it loses it
forever) and `projected` (a rebuildable mirror of something owned elsewhere). Before this
card, nothing backed that claim up: `campy/cli/graph_io.py` was a developer JSONL dump/restore
tool with no scheduling, retention, or verified restore. "We have an export script" is not a
disaster-recovery story.

### Commands (`campy/cli/backup.py`)

```
campy backup create   [--workspace ID|--all] [--out DIR] [--include-projected] [--db-path PATH]
campy backup list     [--workspace ID] [--out DIR]
campy backup verify   SNAPSHOT [--out DIR]
campy backup prune    [--keep-daily N --keep-weekly N] [--workspace ID] [--out DIR] [--dry-run]
campy restore         SNAPSHOT [--workspace ID] [--force] [--yes] [--db-path PATH] [--out DIR]
```

`--db-path`/`--out` are testability/override escape hatches (matching `graph_io.py`'s existing
`--db-path`/`--db` convention) — omitted, `create`/`restore` use `campy.paths.get_database_path()`
and `campy.paths.get_backup_root()` (`~/.campy/backups/`) exactly as an installed user would.

### Snapshot format: the existing JSONL dump, not a database-directory copy

A snapshot is `export_graph_dump()`'s output (`campy/brain/hippocampus/graph/export.py`,
already built for B313) plus an extended `manifest.json` — never a copy of the Kùzu database
file itself. A file copy would be faster, but it is opaque and version-locked to the pinned
Kùzu 0.11.3, which defeats the portability B314's `GraphGateway` seam is buying. Default
excludes `authority='projected'` rows (`export_graph_dump(..., include_projected=False)`,
reused as-is from B313 — not reimplemented); `--include-projected` includes them.

On a graph of ~50 node rows / a handful of rel rows (this card's test fixtures — the repo has
no larger seeded graph available in this sandbox to time against), dump+manifest+checksum and
restore+`init_schema()` each complete in well under a second. See the PR description for the
actual numbers measured in CI; if dump/restore ever proves unacceptably slow on a large
production graph, the answer is to report that with numbers, not to silently switch to a file
copy — this card did not need to make that call.

### Manifest — what proves a snapshot is what it claims to be

`export_graph_dump()`'s own manifest (`format_version`, `engine`, `embedding_dim`,
per-table `node_tables`/`rel_tables` row counts, `exported_at`) is extended with:

| Field | Purpose |
|---|---|
| `schema_version` | compared against `schema.SCHEMA_VERSION` on restore (see below) |
| `campy_version` | `importlib.metadata.version("hippocampy")`, best-effort |
| `embedding_model` | the *configured* model at backup time — without this, a restore onto a differently-configured install silently produces a graph whose vectors don't match the running model, and retrieval degrades with no error anywhere |
| `workspace_id` | which workspace this snapshot belongs to (see below) |
| `payload_checksum` | sha256 over every `nodes/*.jsonl` + `rels/*.jsonl` file's bytes, in sorted-path order |

`payload_checksum` is computed after the JSONL files are written and stored in the same
`manifest.json` `export_graph_dump()` already writes — `create_snapshot()`
(`campy/cli/backup.py`) reads that file back, merges in the fields above, and rewrites it,
rather than adding a second manifest file or a parallel export path.

### `schema.SCHEMA_VERSION` — the field restore refuses to go forward on

`campy/brain/hippocampus/schema.py` gained a single hand-maintained integer,
`SCHEMA_VERSION = 1`, bumped whenever a new `_MIGRATIONS` entry (or NODE_TABLES/REL_TABLES DDL
change) lands. This is the first release tracking the concept explicitly — no attempt was made
to retroactively number every migration back to B12. A snapshot manifest with no
`schema_version` key at all (anything backed up before B319) reads as version `0`, i.e. "older
than anything," which is always safe to restore.

`restore_snapshot()` refuses outright (`BackupError`, nothing touched) when a snapshot's
`schema_version` is *newer* than the running code's `SCHEMA_VERSION` — a forward restore would
silently drop columns the current code doesn't know to write back. Older is fine: restore
proceeds, and `init_schema()` runs afterward so `_MIGRATIONS` brings the resulting database's
columns up to date. In practice `_ensure_graph_schema()` (inside `import_graph_dump()`) already
creates every table from the *current* `NODE_TABLES` DDL regardless of the snapshot's vintage —
an older snapshot's JSONL rows just have fewer keys, which insert as NULLs for the newer
columns — so `init_schema()`'s post-restore call is a defensive, idempotent belt-and-suspenders
step for the case where `restore` targets a pre-existing (not freshly wiped) database file with
a stale on-disk schema, rather than the only thing making a fresh restore schema-current.

### `backup verify` — restores into a throwaway database, never the live one

`verify_snapshot(snapshot_dir)` takes **no live-database argument at all** — there is nothing
in its body that can reach `campy.paths.get_database_path()` or any path a caller doesn't
explicitly hand it. That is what makes "verify never touches the live database" true by
construction, not by discipline. Steps:

1. Recompute the payload checksum and compare against the manifest.
2. Restore into a private `tempfile.mkdtemp()` database.
3. Re-derive per-table counts from the restored database (by calling `export_graph_dump()`
   again against a scratch directory — reusing its existing counting Cypher rather than
   hand-writing new counting queries, which would grow B314's inline-Cypher ratchet for no
   reason) and assert they match what the snapshot's own JSONL files should actually produce.
   That is deliberately *not* a blind comparison against the manifest's raw counts:
   `import_graph_dump()`'s documented behavior (B313) is that a relationship row whose
   endpoint was a `projected` node omitted from the dump fails its `MATCH` and is silently
   skipped — expected, not corruption. `_expected_counts_from_dump()` re-derives the
   restorable rel count directly from which node primary keys are actually present in the
   dump, so that documented exclusion doesn't fail verification while a genuine import
   discrepancy still would.
4. Run one real recall query against the restored graph
   (`campy.brain.hippocampus.graph.queries.backup.BACKUP_QUERIES` —
   `backup.recall_sample`, a `UNION ALL` lexical existence check across live Concept/
   Decision/Lesson rows, reached through `GraphGateway.run()`) and assert it returns rows.
5. Compare the manifest's `embedding_model` against the currently configured one —
   mismatch is appended to a `warnings` list, never to `errors`; `verify_snapshot()`'s `ok`
   key is unaffected by it. Restoring onto a different model is legitimate (a migration in
   progress), it just means vectors need rebuilding afterward.

The `backup.recall_sample` query lives in `campy/brain/hippocampus/graph/queries/backup.py` —
the B314-allowlisted `graph/queries/` directory — specifically so this module needn't add any
new inline Cypher of its own and the B314 ratchet (`scripts/check_cypher_ratchet.py`) stays
unchanged by this card.

### `restore` — the dangerous one

- Refuses a non-empty target database without `--force`, changing nothing.
- With `--force` and a non-empty target, `restore_snapshot()` takes an automatic pre-restore
  snapshot of *whatever is currently at the target path* before touching anything — a normal
  snapshot via the same `create_snapshot()` path (so it is itself independently restorable and
  verifiable, and participates in ordinary `backup prune` retention) — and returns its
  directory so the CLI can print it before doing anything destructive. The CLI's confirmation
  prompt (`--yes` to skip) fires after this, on top of it, not instead of it.
- Refuses a snapshot whose `schema_version` is newer than the running code's
  `SCHEMA_VERSION` (see above).
- After import, calls `init_schema()` with the snapshot's recorded `embedding_model` (falling
  back to the currently configured one) so `_MIGRATIONS` runs regardless of whether it's
  strictly needed for a freshly-wiped target.

### Workspace awareness, from the start (composes with B316, doesn't block on it)

Every function below `create_snapshot()`/`verify_snapshot()`/`restore_snapshot()`/
`prune_workspace()` already takes `workspace_id`/`workspace_root` as a plain parameter.
Snapshot layout is `<backup_root>/<workspace_id>/<timestamp>/`, so a restore can never land in
the wrong workspace's directory by construction. The only function that knows there is
currently exactly one workspace is `_list_workspace_ids()` (`campy/cli/backup.py`), which
today returns `["local"]` — a single-database install has one implicit workspace. When B316's
per-workspace router lands, this is the one function that changes (to walk the router's
workspace root and return real ids); nothing else in this module needs a rewrite.

### Dedup via hard links, not a duplicate-tracking manifest field

`create_snapshot()` compares a fresh dump's `payload_checksum` against the immediately
preceding snapshot in the same workspace. On a match, the new snapshot's `nodes/*.jsonl` /
`rels/*.jsonl` files are replaced with hard links to the prior snapshot's byte-identical files
(`_hardlink_dedupe()`), falling back to a plain copy if the filesystem doesn't support hard
links. This was chosen over a "pointer" manifest field (`duplicate_of: <other-snapshot>`)
specifically so every snapshot directory stays fully self-contained and independently
restorable/prunable: pruning the *original* snapshot a later one was hard-linked from has no
effect on the later one (the OS keeps the shared blocks alive as long as any directory entry
still references them), so `backup prune`'s retention math needs no special-casing for dedup at
all. `manifest["deduplicated_from"]` still records which prior snapshot the content matched,
for operator visibility — it just isn't load-bearing for restore.

### `backup prune` — minimal daily/weekly retention

`prune_workspace()` always keeps the single most recent snapshot regardless of
`--keep-daily`/`--keep-weekly` (there must always be at least one restorable point), then keeps
the most recent snapshot per calendar day up to `--keep-daily` distinct days, then the most
recent snapshot per ISO week up to `--keep-weekly` additional distinct weeks, deleting
everything else. `--dry-run` reports the same decision without deleting.

### Scheduling — minimal, per the card's own instruction not to build a scheduler

The card asks for a daily `campy backup create --all` wired into the platform service Campy
already installs (`campy/cli/launchd.py` on macOS; "whatever the Linux equivalent is" in
`campy/cli/install.py`). Reading `campy/cli/install.py`'s `DaemonSetup` confirms there is, in
fact, no Linux equivalent today — `DaemonSetup.setup()` explicitly no-ops off of macOS
(`"launchd only available on macOS ... Start manually: campy start"`); there is no systemd unit
or cron entry this card could extend. Rather than inventing a new Linux service-management
mechanism as a side effect of a backup card, B319 ships the `campy backup` commands themselves
(schedulable by whatever mechanism a given install already uses — cron, systemd timer, launchd,
a CI job) and leaves wiring an actual daily launchd/systemd entry as follow-up work once B319's
commands exist to schedule. See the PR description for this discrepancy between the card and
the code it described.

### What this card does not do

- No continuous point-in-time recovery — snapshot-based only. Real PITR needs a write-ahead
  log Campy does not have.
- No remote/offsite backup targets (S3 et al.) — local directory only, on the assumption that a
  customer's existing backup tooling picks up `~/.campy/backups/` from there.
- No encryption at rest.
- No backup of `~/.campy/config.toml`, triggers, or the activity log — graph only.
- No actual daily launchd/systemd job wired up yet (see "Scheduling" above) — the commands
  exist; scheduling them is follow-up work.

## B315 — AuthContext: Principal Derivation and Threading

### Why

Before this card, Campy had no concept of *who* is asking. `campy/brain_daemon.py`'s
`_dispatch` routed every JSON-RPC call as `handler(params, self.db, self.config)` — one
global `self.db`, no caller identity, no scoping. Correct for local single-user Campy,
insufficient the moment more than one principal shares a deployment: if an agent can pass a
`workspace_id` argument, an agent can read another tenant's memory — confused-deputy, one
prompt injection away from being exercised by an LLM agent.

**The rule:** tenant and workspace are derived from the transport credential, never from
request params. See docs/ecosystem-rules.md's "Principal derivation rule" section for the
full non-negotiable statement — this section covers the implementation.

**Framing:** local Campy is single-tenant cloud with auth stubbed. `LocalSingleUserResolver`
returns a real `Principal` (tenant `local`, workspace `local`, every known scope), never
`None`. Handlers never branch on "are we local?" — the multi-tenant dispatch path is
exercised by every local test run, not only in production.

### The types (`campy/brain/auth.py`)

- **`Principal`** — frozen dataclass: `subject_id`, `tenant_id`, `workspace_id`, `scopes`
  (`frozenset[str]`), `client` (observability only — `"claude-code"`, `"agentcore"`, …),
  `session_id`, `derived_from` (`"local-single-user" | "oidc" | "iam"` — during an incident,
  the difference between "we trusted a token" and "we trusted a request body"). Scope
  vocabulary: `memory.read`, `memory.write`, `memory.admin`, `visibility.override`
  (`KNOWN_SCOPES`). `Principal.require(scope)` raises `PermissionError` if the scope isn't
  held, returns `None` otherwise.
- **`TransportContext`** — frozen dataclass carrying only what the *transport* knows:
  `transport` (`"unix-socket" | "http" | "stdio"`), `peer_credential` (opaque,
  transport-verified identity string — `None` locally, a verified SigV4 ARN or OIDC subject
  over HTTP), `headers` (HTTP only). Deliberately has **no field a client could populate via
  `params`** — enforced structurally by `TRANSPORT_CONTEXT_FIELDS` and asserted in
  `tests/test_auth_context.py`. Constructed once per connection, strictly before any
  request body is parsed: `brain_daemon.py::_handle_connection` for the Unix socket,
  `web/server.py::mcp_post` for the streamable-HTTP transport (B325).
- **`PrincipalResolver`** (`Protocol`) — `async resolve(transport_ctx) -> Principal`. Never
  sees `params`.
- **`LocalSingleUserResolver`** — the local-mode implementation described above.
- **`IAMPrincipalResolver`** (B325) — verifies a SigV4-signed request by replaying its
  exact signed headers against AWS STS `GetCallerIdentity` (the same "IAM auth via STS"
  pattern HashiCorp Vault's `aws` auth method uses), then maps the caller ARN to
  `subject_id`, with `tenant_id`/`workspace_id` from a configured map or a
  Gateway-forwarded header (never from `params`). `boto3` is an optional import, mirroring
  `campy/brain/llm/bedrock.py`'s pattern exactly.

### Threading `principal` to handlers (Task 3 — incremental adoption)

The tool convention is uniform: `async def name(params, db, config) -> dict`, across ~14
modules in `campy/brain/thalamus/tools/`. Rewriting every handler's signature in one commit
is a large mechanical diff with real regression risk, so adoption is **incremental, via
signature inspection**:

```python
_WANTS_PRINCIPAL = {
    name for name, fn in TOOL_HANDLERS.items()
    if "principal" in inspect.signature(fn).parameters
}
```

computed once at import in `campy/brain_daemon.py`. A handler opts in by adding `*,
principal: Principal | None = None` to its signature. **Gotcha not anticipated by the
original card**: most `TOOL_HANDLERS` entries are wrapped by
`campy/brain/thalamus/tools/_shared.py::_with_phase()`, whose wrapper signature is
`(params=None, db=None, config=None, **kw)` — `inspect.signature()` on the *wrapper* would
see `**kw`, never the real `principal` parameter underneath. Fixed by setting
`wrapper.__wrapped__ = fn` (the same mechanism `functools.wraps` uses), which makes
`inspect.signature()` follow through to the real handler by default. Without this, the
signature-inspection adoption mechanism the card specifies would silently never detect any
converted handler.

`scripts/check_principal_ratchet.py` + `scripts/principal_baseline.json` (same shape as
B314's Cypher ratchet) count handlers **not** declaring `principal`, fail if the count rises
above baseline (currently 57 of 59 — `notify_turn` and `upsert_lesson` are the two converted
in this card). Wired as `make check-principal`. Follow-up cards drive it to zero, at which
point the inspection branch is deleted and the parameter becomes required.

### The two converted capture paths

`campy/brain/thalamus/tools/capture.py::notify_turn` and
`campy/brain/thalamus/tools/lessons.py::upsert_lesson` — B312's two named primary-capture-path
write sites — now accept `principal` and use it for B312's `source` field:
`f"{principal.client}:{principal.subject_id}"`, replacing the previous guessed
`"agent:<agent_source>"` / `"user:direct"` convention when a principal is present (falls
back to the old convention when it isn't — the ~57 not-yet-converted call sites still work
unchanged). This is what makes B312 and B315 compose: facts become attributable to a
transport-verified principal instead of a caller-declared string.

**A real conflict the card didn't anticipate, and how it was resolved:** both handlers used
to read an optional `workspace_id` from `params` (default `"local"`) purely as a B320
content-hash discriminator — never for DB routing, since B316 hadn't landed yet when B320
wrote it. That is now exactly the shape of an attack the forbidden-key guard exists to
close: a client-supplied `workspace_id`. Per the card's own instruction ("check whether any
current tool legitimately accepts one of these names before adding the guard"), this was
resolved by **removing the request-param path entirely** rather than renaming it: both
handlers now derive `workspace_id` for the content hash from `principal.workspace_id`
(falling back to `"local"` only when no principal was threaded in). This is strictly more
correct than the pre-B315 behavior — the discriminator now comes from a transport-verified
identity instead of an unverified request field — and it means B320's content-hash identity
and B316's DB-routing key are, from day one, the same value: `principal.workspace_id`, never
`params["workspace_id"]`. `tests/test_idempotent_writes.py::test_upsert_lesson_workspace_differs_no_dedupe`
was updated to exercise this through two `Principal`s instead of two request bodies — the
B320 property it tests (same text, different workspace, no false dedupe) is unchanged.

### The forbidden-key guard (Task 5)

In `campy.brain_daemon.route_tool_call` — the single chokepoint both the Unix-socket
dispatcher and the streamable-HTTP transport call through (see "Transports" below) — before
invoking a handler, reject any request whose `params` contain `tenant_id`, `workspace_id`,
`subject_id`, `principal`, or `scopes` (`FORBIDDEN_PARAM_KEYS`, defined once in
`campy/brain/auth.py`). Returns JSON-RPC `-32602` naming the offending key; logs at WARNING
with the rejecting principal's `subject_id`. This is belt-and-braces on top of
`TransportContext`'s structural separation — it is what turns "an agent tried to escalate"
from a silent no-op into a logged, visible failure.

### What this card does not do

- Does not build OIDC, IAM, or Cognito resolvers beyond `IAMPrincipalResolver` (B325) —
  Protocol + local + IAM only; OIDC config is accepted, the resolver is a follow-up.
- Does not open more than one database — B316's job.
- Does not add visibility (`private`/`team`/`org`) fields or filtering — separate card.
- Does not convert the other ~57 handlers — the ratchet enforces direction only.
- Does not add authentication to the Unix socket transport itself (filesystem permissions
  remain the access control there, as before).

## B325 — Remote MCP Server Surface with Pluggable Auth

### Why

B315/B324's identity and provider seams make Campy *deployable* into a customer's AWS account.
Before this card, nothing made it *reachable*: a container running Campy that no remote agent
can call is not a service. AWS Bedrock AgentCore Gateway (the immediate consumer) reaches
governed tools through a shared, IAM-authenticated MCP tool plane; Campy needed to register there
as a target.

**The generic surface, not an AgentCore adapter.** Every serious agent framework speaks MCP —
one streamable-HTTP transport serves AgentCore, Strands, LangGraph, CrewAI, and the existing
local harnesses. This matches the project's stated positioning (works across harnesses, across
providers, local or cloud) — an AWS-specific integration would have contradicted it directly.

### Task 0 finding — `/mcp` already existed, outside `campy/`

The card's own investigation section listed three possible outcomes and asked that the actual
one be reported rather than assumed. The actual outcome: **`POST /mcp` already existed**, in
`web/server.py` (outside `campy/`, in the Memory Control Panel's FastAPI app — B3's "MCP-over-SSE"
work had already been upgraded to streamable HTTP per `docs/transport-audit.md`, predating this
card). It was bound to `127.0.0.1` only by `campy/brain_daemon.py::_start_web_server`'s
hardcoded `host="127.0.0.1"  # NEVER 0.0.0.0 — local-only by design` — i.e. the surface existed
but was unreachable from outside the local machine, and had no bind-address configuration at
all, let alone a guard.

**Decision: extend the existing surface rather than add a parallel one** — Task 1's "reuse
`TOOL_HANDLERS` unchanged, do not fork the tool list per transport" would otherwise be violated
immediately by building a second `/mcp`.

**A real gap this surfaced**: `web/server.py::_dispatch_mcp` (the HTTP dispatcher) called
`TOOL_HANDLERS[name]` **directly**, bypassing `campy_daemon.py::_dispatch` (the Unix-socket
dispatcher) entirely — exactly the "IPC Dispatch Divergence" `docs/transport-audit.md` had
already flagged as a documented future risk, now realized: the HTTP path never ran B315's
forbidden-key guard or principal threading at all before this card.

### Task 1 — the shared dispatch chokepoint: `route_tool_call()`

Rather than duplicating B315's guard logic into `_dispatch_mcp` (the divergence-widening
option `docs/transport-audit.md` warned against), the guard + handler-invocation logic was
extracted out of `campy.brain_daemon.BrainDaemon._dispatch` into a module-level function:

```python
async def route_tool_call(method, params, db, config, principal) -> Any:
    ...  # forbidden-key guard, then _WANTS_PRINCIPAL-conditional handler call
```

Both `BrainDaemon._dispatch` (Unix socket) and `web/server.py::_dispatch_mcp` (streamable HTTP)
now call through this one function. `ForbiddenParamError` / `UnknownMethodError` are raised by
`route_tool_call()` and translated into each transport's own error envelope (JSON-RPC `-32602`
/ `-32601` on the socket path; the equivalent MCP `tools/call` error shape over HTTP) — so
B315's guard, and (once B316 lands) workspace routing, apply identically regardless of which
transport a request arrived on, closing the divergence rather than adding a second copy of it.

Protocol version: HTTP already advertised `"2025-03-26"` (streamable HTTP) before this card; the
Unix-socket path keeps advertising `"2024-11-05"` unchanged — the card's own guidance ("if any
pinned client breaks, keep the old version for stdio and advertise the new one only on HTTP")
turned out to already be satisfied by the pre-existing code, so no version-string change was
needed.

### Task 2 — the bind guard (`campy.brain_daemon._enforce_bind_guard`)

**The single most important property in this card**: binding `[server].bind_host` to any
non-loopback address while `[server].auth = "none"` is a **hard startup failure**. Checked
synchronously in `BrainDaemon.start()`, before the IPC socket server, the background tasks, or
the web/MCP server are ever created — an uncaught `BindGuardError` propagates out of `main()`
and exits the process. This ordering matters: `_start_web_server` runs as a background asyncio
task with a crash-and-restart wrapper (`_restart_on_failure`) — if the guard lived *inside* that
task instead, a misconfiguration would become an infinite crash-restart loop (a message logged
every few seconds), not the hard failure the card requires. `tests/test_bind_guard.py` proves
nothing is bound (not merely that a message was logged) by asserting the code path that would
call `asyncio.start_server`/uvicorn is never reached when the guard fires, across `0.0.0.0`,
`::`, and a concrete LAN address.

`bind_host` defaults to `127.0.0.1` (`campy/brain/brainstem/config.py`'s `_DEFAULT_CONFIG`) —
an existing local install sees no behavioral change. `auth` defaults to `"none"`.

### Task 3 — `IAMPrincipalResolver`

Implements B315's `PrincipalResolver` Protocol. Verifies a SigV4-signed request by replaying its
exact signed headers (`Authorization`, `X-Amz-Date`, `X-Amz-Security-Token`) against AWS STS
`GetCallerIdentity` — the same "IAM auth via STS" pattern HashiCorp Vault's `aws` auth method
uses: a SigV4 signature is only valid for the exact request it was computed over, so a
successful STS call with the caller's own headers proves the caller holds the named credentials
without Campy ever handling a raw AWS secret key. Returns the caller ARN as `subject_id`;
`tenant_id`/`workspace_id` come from a configured map keyed by ARN, or an HTTP header the
Gateway forwards as a session attribute (a transport-level credential, per B315's rule — not the
JSON-RPC body). `boto3` is an optional import (mirrors `campy/brain/llm/bedrock.py`'s pattern
exactly) — `tests/test_remote_mcp.py::test_module_imports_without_boto3_installed` proves every
non-IAM mode imports and starts with `boto3` absent, in a subprocess so faking its absence can't
corrupt the already-imported module objects the rest of the test suite shares.

### Task 4b — the actual deployment topology is Lambda-fronted, not a direct Gateway target

See `docs/deployment-agentcore.md` for the full writeup. Short version: the evaluating
platform's own architecture policy registers Campy behind `AgentCore agent → Gateway (AWS_IAM)
→ Lambda (thin adapter) → Campy HTTP MCP surface`, not a direct `mcp.mcp_server` Gateway target
— a **policy** decision (the provider supports both; they picked Lambda). Tasks 1–3 remain the
prerequisite either way: the Lambda still needs an HTTP surface to proxy to (Kùzu is
single-process-writer, so the Lambda cannot open the database file directly), and
`IAMPrincipalResolver` is what verifies its calls. Two items are recorded as open in that doc
rather than guessed at: identity does not currently propagate through the platform's Gateway (no
`metadata_configuration` set), so B315's transport-derived-workspace rule cannot fully hold
behind it yet; and the Gateway target's specific IAM policy / network path is pending the
platform team.

### Files

- `web/server.py` — `create_app()` gained `principal_resolver` and (B316) `router` kwargs;
  `_dispatch_mcp` threads `principal` and routes through `route_tool_call()`; `mcp_post` builds
  `TransportContext` from HTTP headers before the body is parsed.
- `campy/brain_daemon.py` — `route_tool_call`, `ForbiddenParamError`, `UnknownMethodError`,
  `_enforce_bind_guard`, `BindGuardError`, `_build_http_principal_resolver`; `start()` runs the
  guard synchronously before anything else; `_start_web_server` reads `[server].bind_host`.
  `_dispatch` no longer inlines the guard/dispatch logic — it calls `route_tool_call()`.
- `campy/brain/auth.py` — `IAMPrincipalResolver`, `IAMConfigError`,
  `_sts_get_caller_identity_verifier`.
- `campy/brain/brainstem/config.py` — `_DEFAULT_CONFIG["server"]` (`bind_host`, `auth`).
- `campy/cli/smoke_test.py` — `check_remote_mcp_surface()`.
- `docs/deployment-agentcore.md` — new.
- `tests/test_bind_guard.py`, `tests/test_remote_mcp.py` — new.

### What this card does not do

- Does not build an AgentCore-specific adapter — generic MCP; AgentCore Gateway is one consumer,
  reached via the Lambda topology in `docs/deployment-agentcore.md`.
- Does not build the Lambda proxy itself — a separate, small follow-up card once the platform
  answers on identity propagation.
- Does not implement the signed-token workspace fallback — recorded as an open decision only.
- Does not implement OIDC (the config accepts the value; `_build_http_principal_resolver` fails
  loudly rather than silently degrading if `auth = "oidc"` is actually selected before a
  resolver exists).
- Does not add TLS termination, rate limiting, quotas, or per-tenant throttling.
- Does not change the default bind address or local behavior in any way — `tests/test_web.py`'s
  existing suite (updated only for `_dispatch_mcp`'s new required `principal` parameter) passes
  unmodified otherwise.
- Does not finish the Gateway registration doc — blocked on the platform team, marked pending.

## B316 — Workspace Router: One Database Per Workspace

### Why

Before this card, `campy/brain_daemon.py` opened exactly one database for the process life
(`self.db = KuzuClient(str(DB_PATH))`). For a multi-tenant deployment, the isolation model has
to be physical, not predicate-based: with ~500 Cypher call sites (B314), a shared graph plus a
`tenant_id` filter is not auditable — nothing proves every query carries it. **Database per
workspace** makes isolation provable by construction: a routing bug is loud (wrong directory,
missing data) rather than silent (one dropped `WHERE` leaking another tenant's memory). It also
turns Kùzu's single-writer-per-database constraint into per-workspace parallelism instead of a
global bottleneck.

**Sharding boundary rule**: shard where traversal does not need to cross. Agents working in one
workspace never traverse into another; cross-workspace knowledge is a separate, deliberately
promoted store, not an accidental traversal.

### `WorkspaceRouter` (`campy/brain/hippocampus/graph/router.py`)

LRU-bounded cache of `KuzuClient` instances, one per workspace:

- **`get(workspace_id)`** / **`release(workspace_id)`** — a matched pair. `get()` returns a
  client (opening it, and running `schema_init()`, on first access) and increments a per-
  workspace borrow count; `release()` decrements it. This borrow accounting is what makes "a
  busy client is not evicted" enforceable — `campy.brain_daemon.BrainDaemon._dispatch` and
  `web/server.py::_dispatch_mcp` both call `get()`/`release()` around exactly one request's
  handler invocation, in a `try`/`finally`.
- **First access to a new workspace** is guarded by a per-workspace `asyncio.Lock` (a dict of
  locks keyed by workspace_id — never a global lock, which would serialize unrelated
  workspaces' first access against each other). Ten concurrent `get()` calls for the same new
  workspace run `schema_init()` exactly once.
- **`register(workspace_id, client)`** — pre-seeds the cache with an already-open client,
  without going through `get()`'s creation path. Exists for exactly one caller:
  `BrainDaemon.start()` wires its pre-existing `self.db` (opened at `__init__`, before a router
  exists) in as the `"local"` workspace client via `register("local", self.db)`. Without this,
  `get("local")` would open a *second* `kuzu.Database` handle on the identical directory —
  Kùzu is single-process-writer, so two live handles on one path is a hazard the router exists
  to prevent, not create.
- **Eviction** is LRU, skipping any workspace with a nonzero borrow count. If every open client
  is busy when `max_open` is exceeded, the router logs at WARNING and exceeds the bound rather
  than blocking a caller or closing something in use.
- **`close_all()`** (async) / **`close_all_sync()`** — the latter exists because
  `BrainDaemon.shutdown()` runs from a signal handler and cannot `await`.

### Path safety: `_workspace_dir()`

`workspace_id` is treated as untrusted input for filesystem purposes — principals are minted
from external identity systems in cloud deployments, so this module never trusts a
`workspace_id` string enough to interpolate it into a path without validating it first.

**Allowlist regex, not a blocklist**: `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. A blocklist of "bad"
characters loses — there is always one more way to spell `..`. The allowlist makes traversal
structurally impossible: every character in `../../etc`, `a/b`, `..`, an empty string, a
200-char id, or an id containing a null byte falls outside the allowed set, so `fullmatch()`
rejects all of them uniformly, with nothing disk-side created before the rejection. A sha256
digest (first 16 hex chars) is appended to the directory name for every *non-local* workspace —
this is a different safeguard than the regex: the regex prevents traversal, the digest prevents
case-insensitive-filesystem collisions (`Foo` and `foo` are different workspace ids that could
otherwise collide as directory names). A final `is_relative_to(root)`-equivalent check backstops
both — belt and braces, because this is the one place in the module where a bug is a security
bug (path traversal) rather than an availability bug.

**`"local"` is special-cased explicitly**, not left to the digest happening to match: it
resolves to `local_db_path` — the exact pre-existing `DB_PATH`, passed in by
`BrainDaemon.start()` — so an existing local install keeps its memory with zero migration.
`campy/paths.py::get_workspace_root()` (`= get_database_path().parent`) is what
`WorkspaceRouter` is rooted at, so the "local" workspace and every other workspace are always
siblings under the same directory.

### Task 3 — the write lock, keyed per `(loop, db_path)`

`campy/brain/hippocampus/graph/kuzu_client.py::_get_write_lock()` used to key on `id(loop)`
alone — correct with one database (every write anywhere correctly serialized against every
other write), wrong with N per-workspace databases (it would serialize every write across every
tenant, destroying the entire benefit of sharding). Changed the key to `(id(loop), db_path)`,
**preserving the pre-existing weakref-to-loop staleness check exactly** — a stale entry (loop
garbage-collected, id() address reused by CPython) is still detected and replaced, just scoped
per-workspace now instead of globally. `KuzuClient.__init__` gained `self.db_path = db_path`
(the constructor already took `db_path` as a parameter; it just hadn't stored it) so
`execute_write()` and `rebuild_vector_index()` can pass it to `_get_write_lock()`.

**Card fact-check** (see the PR): the card asks to "run the existing kuzu_client lock tests
unmodified (grep tests/ for them first)." No dedicated test file or test function for this
locking behavior exists anywhere in `tests/` — confirmed by grepping for `_get_write_lock`,
`_write_locks`, `weakref`, `loop_ref`, and `stale.*lock` across the whole directory (zero hits
before this card). `tests/test_workspace_router.py` adds new, direct tests for both the
staleness behavior and the per-`db_path` keying instead of "running something unmodified",
since there was nothing pre-existing to run.

### Task 4 — daemon wiring, backward-compatibly

`BrainDaemon._dispatch` resolves `db = await self._router.get(principal.workspace_id)` (never
from `params`) instead of always using `self.db`, releasing it in a `finally` block.
`web/server.py::_dispatch_mcp` does the same when a router is passed to `create_app()` (from
`BrainDaemon._start_web_server`) — B325's `route_tool_call()` chokepoint means this workspace
routing applies identically on both transports rather than needing to be implemented twice.
Both fall back to a fixed `db` when no router exists (a `BrainDaemon`/`create_app()` constructed
directly in a test, without calling `start()`), matching pre-B316 behavior exactly.

**Four background tasks intentionally still operate on `self.db` (the local/default workspace)
only**, per the card's own scope: the Gated Consolidation Loop worker (`_loop_worker`),
background sweep (`_background_sweep`), trigger manifest compilation
(`_compile_trigger_manifest`), and file-bridge regen (`_file_bridge_regen`). Making sweep/loop
workspace-aware is a real follow-up card, not a small one — a per-workspace consolidation
scheduler needs its own design.

`BrainDaemon.shutdown()` (runs from a signal handler, cannot `await`) calls
`self._router.close_all_sync()`, which closes `self.db` exactly once (it was registered into
the router, not a second handle) rather than calling `self.db.close()` directly and separately.

### What this card does not do

- Does not make sweep/consolidation, the loop worker, trigger compile, or file-bridge regen
  workspace-aware — they stay on the default workspace; follow-up card.
- Does not implement S3 cold storage / dormant-workspace eviction to object storage.
- Does not implement cross-workspace promotion (the shared knowledge tier).
- Does not add per-workspace quotas, backup, or PITR.
- Does not change how `workspace_id` is *derived* — that is B315's job and stays there; this
  card only consumes `principal.workspace_id`.

## B321 — Cross-Session Continuity for an App

**Positioning, stated first because it was misdiagnosed once already:** this card is
additive to an evaluating platform's own git-workspace design, never a substitute for it. That
design (real git branches per session, cloned with a genuine merge base) answers "what changed
in the files, and how do I reconcile it." B321 answers a different question — "what did an
earlier session on this same App decide, try, and learn." A diff carries neither a decision
nor its reason; this card exists because that design's follow-on work ("shared ancestry,
divergence reads, rebase") is Proposed but unbuilt, and their own review names the gap directly:
sessions on the same App today have "no visibility between concurrent sessions."

**Campy provides no mutual exclusion, locking, or collision prevention of any kind — this
card is purely advisory and pull-only.** A factual audit of the target platform's live system
(cited in backlog/B321.md) found the hazard the original card assumed — two sessions
overwriting the same file — does not exist there: each session gets its own workspace
directory, the shared root's read bit is stripped, and an OS-level sandbox confines each build
subprocess to its own workspace, all verified in production. The actual gap is the opposite of
collision: isolation.
Nothing here claims a resource, gates a write, or warns about "in progress" work — the wording
denylist enforced by `tests/test_app_continuity.py` (`do not`, `already claimed`, `in progress`,
`owned by`, `locked`) exists specifically so an advisory section can never accidentally read
like a guarantee it isn't.

### The join key

The unit of continuity is the **App**, not the session and not the file. Two new nullable
`Session` columns, added via the existing `_MIGRATIONS` additive path (never redefining
`Session`'s base DDL, matching B323's `Workspace.branch_name`/`active` precedent):

| Column | Meaning |
|---|---|
| `external_app_id` | the platform's App id, an opaque `<prefix>_<kebab-name>` string (e.g. `APP_notes-service`) |
| `external_session_id` | the platform's own session id, for correlation |

Both are `NULL` on every pre-B321 row and on every local-Campy session going forward — local
Campy has no App concept, and this card must not (and does not) change its behavior at all.
"Iteration" has no identity of its own upstream (`iteration_id == session.id`), so continuity
is modeled as **App → many Sessions**, ordered by `started_at`, never a separate Iteration
concept. App-slug rename instability (a pre-lock rename mints a different `app_id` for what a
human considers the same App) is a known, explicitly deferred hazard — nothing here reconciles
it; a rename simply starts a new, disconnected continuity chain.

### The continuity query — `app_continuity()`

`campy/brain/thalamus/tools/context_tools.py::app_continuity(db, *, external_app_id,
exclude_session, limit_sessions=5, since_days=30)`. `exclude_session` is a required
keyword-only argument with no default — Python itself raises `TypeError` if a caller omits
it, which is exactly the contract this card wants: a session must never see its own work
reported back as "earlier work" (an agent that sees its own last turn described as history
learns to ignore the whole section). Bounded on both axes — at most `limit_sessions` prior
sessions, newest first, and a `since_days` floor on `started_at` — this is a briefing, not an
archive dump.

Per prior session, returns **decisions, constraints, lessons, and Plan outcomes** — never bare
`Concept` rows (the card: "prefer lessons and decisions over raw concepts"). Each item carries
B312 provenance (`source`, `source_version`, `observed_at`, `evidence_ref`) and B313
`authority` (`authority_of()`, NULL-safe). The joins are all pre-existing relationship tables —
`ESTABLISHED_IN` (Decision/Constraint → Session), `LEARNED` (Session → Lesson), `PLANNED_IN`
(Plan → Session) — no new relationship tables were added; this card is a read path over facts
the graph already captures.

Six `NamedQuery` entries in `campy/brain/hippocampus/graph/queries/continuity.py` (B314's
chokepoint — no raw Cypher in `context_tools.py`, `bundle_compiler.py`, or `capture.py`):
`app_continuity.prior_sessions`, `.decisions_for_sessions`, `.constraints_for_sessions`,
`.lessons_for_sessions`, `.plans_for_sessions` (the four fact queries each `UNWIND` a single
`$session_ids` list rather than one round trip per session), and
`.session_external_app_id` (the one-row lookup the bundle stage uses to decide whether to run
the rest at all) plus `.set_session_external_ids` (the capture-side write, below).

### Surfacing — `bundle_compiler._stage_app_continuity`

A new Stage 7, following the file's existing `_stage_*` convention exactly, with one
deliberate difference from every stage before it: **this is an exact-id join, not a similarity
match** — the `0.30` distance floor (`_stage_exact_facts`, `_stage_semantic_context`, etc.)
does not apply, because there is no query embedding involved at all, only `session_id →
Session.external_app_id → app_continuity()`.

Two B305/B318 conventions this stage follows precisely:

- **Omit when empty, not present-and-empty.** No `external_app_id` on the calling session
  (the common local-Campy case), or an `external_app_id` with no prior sessions in the window,
  returns `None` from the stage function — the `"app_continuity"` key is simply absent from
  the compiled bundle's `sections`, exactly like every other stage's "nothing matched" case.
- **Fails open.** Any exception — a schema that predates this card's migration, a query
  timeout, a malformed `db` — is caught and logged; the section is dropped, and the overall
  `compile_bundle()` call never raises because of it (B318's contract; verified directly with
  a `db` double whose `execute_read`/`execute_write` always raise).

Wording (`_format_continuity_text`) is retrospective and advisory only, matching the card's
worked example ("Session 3 days ago (`agent:build-worker`) — decided Postgres over Mongo for
the task store; lesson: the Stripe webhook needs an idempotency key"): a relative-time phrase,
an optional `(source)` parenthetical, then up to one decision highlight and one lesson
highlight (falling back to a constraint or plan-outcome highlight only when neither exists).
`tests/test_app_continuity.py::TestDenylistWording` asserts the generated scaffolding — not
the underlying fact text, which callers control — never contains `do not`, `already claimed`,
`in progress`, `owned by`, or `locked`, across every highlight-selection branch.

### Capture-side wiring — which of the three options applies

The card's Task 5 asks a client to pass `external_app_id`/`external_session_id` into a capture
call and names three options in preference order. **Option 1 applies**: `capture.py`'s
`notify_turn` reads both as ordinary keys off its `params` dict, exactly like `role` and
`content`. This is deliberately not the `workspace_id` pattern — B315 forbids `workspace_id`
from request params specifically because it is a *security boundary* (it selects which
per-tenant database a request routes to, B316); an App id is not that. It is an opaque label
the caller attaches to its own `Session` row, so it is fine as a normal tool-call parameter.
The write goes through `app_continuity.set_session_external_ids`
(`GraphGateway`/`NamedQuery`, not raw Cypher), and uses `COALESCE(s.external_app_id,
$external_app_id)` rather than an unconditional `SET` — a later turn can fill in an App id an
earlier turn omitted, but a value already recorded is never overwritten by a subsequent call
that supplies a different or absent one.

### Verified acceptance criteria

`tests/test_app_continuity.py` (25 tests, real Kùzu via `KuzuClient` + `init_schema`, same
pattern as `tests/test_idempotent_writes.py`) covers, directly: two sessions sharing an App —
the second sees the first's decisions/lessons, never its own; `exclude_session` omitted raises
`TypeError`; a different `external_app_id` sees nothing; `external_app_id` NULL behaves exactly
as today (section absent, nothing errors); `limit_sessions` and `since_days` both measurably
bound the result; the bundle section is absent — key missing, not empty — with no prior work;
every returned item carries provenance and `authority`; a broken `db` fails the whole stage
(and a full `compile_bundle()` call) open rather than raising; and two independent `KuzuClient`
databases sharing an `external_app_id` string never leak into each other (the workspace
isolation acceptance criterion — trivially true under B316's per-workspace routing, asserted
directly rather than only by architectural argument).

### What this card does not do

- Does not detect, warn about, or prevent file collisions of any kind — there is no collision
  to prevent on the platform this card targets (see the audit findings above).
- Does not lock, lease, claim, or gate anything. Nothing here is enforceable; it is a briefing
  an agent is free to ignore.
- Does not implement, replace, or reimplement the platform's own git-native workspace seeding,
  divergence reads, or rebase affordance.
- Does not model Iteration as a concept separate from Session — upstream does not either.
- Does not fix App-slug rename instability — recorded above as a known, deferred hazard.
- Does not push or notify. Pull-only: surfaced the next time a session on the same App calls
  `compile_context`/`ask` and a bundle gets compiled.

## Brain Daemon Memory Behavior (B311, B342, B353–B358)

`brain_daemon.py`'s memory footprint was investigated across two related but distinct problems, and the
distinction matters for anyone reading this section: B311 is about *transient spikes during write-heavy
bursts*; B342/B353 is about *steady-state baseline size and slow growth over long uptime*. Both are open
investigation cards (`backlog/B311.md`, `backlog/B342.md`) with far more detail than belongs here — this
section records the parts of the finding that should shape how anyone reads this daemon's memory
behavior going forward, not the full investigation trail.

**RSS is not a reliable signal on macOS for this process — this is the single most important finding.**
`ps -o rss=`, `resource.getrusage().ru_maxrss`, and `psutil`'s `rss`/`uss` fields all measure only
*uncompressed resident* pages. macOS's memory compressor can swap/compress a process's pages under
system-wide memory pressure, which makes RSS drop by hundreds of MB while the process's actual memory
burden (what `vmmap -summary`'s "Physical footprint" reports, resident + compressed/swapped) is
unchanged or still climbing. B342 spent several investigation rounds confirming this is not occasional
noise: it is the dominant behavior of this process's memory profile. **Any future memory diagnostic,
watchdog, or investigation for this daemon must use `vmmap`'s physical footprint, never RSS.**

**The growth mechanism (B342) — two separable findings, not one.** Isolated, controlled testing found the
footprint grows slowly with no observed plateau over a 2-hour, 1200-cycle stress run — real, but its
*severity* dropped substantially (roughly halved total growth) once B355's embedding swap and the
KuzuClient prepared-statement caching fix landed, without either change targeting this specifically. This
is a Python-level-leak-shaped question with a non-leak answer: `gc.get_objects()` counts stay flat
throughout, ruling out an object leak. Separately, and initially conflated with the growth question
itself: **the specific "swap accumulates and never comes back down" symptom driving most of the alarming
footprint numbers throughout this investigation is macOS's memory compressor reacting to genuine
system-wide memory pressure, confirmed directly** — instrumenting for system-wide free memory
(`vm_stat`/`top`'s `PhysMem` line) alongside the daemon's own `vmmap` readings caught system-wide
compressor usage jumping in the *exact same cycles* the daemon's own swapped bytes appeared, then both
freezing together even as system memory kept fluctuating afterward — the compressor's actual designed
behavior (compress once under a pressure spike, stay compressed until the app touches that memory again),
not a leak. **This is not a Campy code defect** — there is no code fix for an OS compressor doing its job
correctly. The one real lever is the one already being pulled: shrink the daemon's own resident footprint
so there is less of it for any OS to ever consider reclaiming. Full trail: `backlog/B342.md`'s dated
rounds from 2026-08-24/25, especially the final "Root Cause Found" section.

**Two independent mitigations now run in production, addressing two different aspects of this
finding — see `brain_daemon.py` for both:**

1. **Periodic self-restart** (`_periodic_restart`, `[daemon] restart_interval_hours`, default 24h):
   time-based, same pattern gunicorn/uWSGI use for exactly this class of problem (`max_requests` worker
   recycling). Bounds the worst case regardless of root cause — KuzuDB is the durable source of truth
   (see CLAUDE.md's "No Shadow Stores" rule, detailed in `docs/ecosystem-rules.md`), so a restart loses
   no real state.
2. **Footprint-aware watchdog** (`_periodic_footprint_watchdog`, `[watchdog]` section, B354): reacts to
   actual growth rather than only a clock, using `vmmap` physical footprint (never RSS, per the finding
   above) measured relative to this process's own startup baseline — not a hardcoded absolute number,
   which would break the moment the baseline itself changes (exactly what would have happened had an
   earlier, externally-proposed fixed-350MB design shipped before the baseline reduction below).

**Baseline reduction (B355):** the embedding backend (see the Bedrock/embeddings decision section above)
moved from PyTorch/`sentence-transformers` to `fastembed`/ONNX Runtime, same model, verified near-perfect
output parity (cosine similarity 1.000000 across 200 real test sentences, 100% top-10 retrieval
agreement). This was the highest-leverage single change for the daemon's *perceived* weight, but be
precise about the number: an initial measurement (the embedding module tested in complete isolation)
reported 228MB and was wrong as a whole-daemon claim — it never loaded `spacy`, whose own ML backend
(`thinc`) imports `torch` unconditionally at Python import time, independent of the embedding backend.
The real, live daemon's fresh-start baseline is **~1.2GB**. A fair comparison (spaCy loaded first, then
each embedding backend layered on top of that same starting point) confirms the embedding backend's own
contribution genuinely dropped ~6.5x (1.22GB -> 186MB); the best estimate for the full daemon's baseline
before B355 (extrapolated, not directly re-measured) is ~2.2GB, putting the real whole-daemon improvement
around 45-50% — real, but not the dramatic number first reported. See `backlog/B355.md`'s own correction
note for the full measurement trail.

**What this does not claim:** the swap-symptom's cause is now understood (macOS's compressor under system
pressure, above), but the underlying *resident* growth's exact allocator-level mechanism (why the
`asyncio.to_thread` executor handoff specifically correlates with it) is not — and neither mitigation
eliminates that underlying growth, they bound its consequences. If the daemon's memory behavior is ever
revisited, start from `backlog/B342.md` and `backlog/B353.md` rather than re-deriving the RSS-vs-footprint
distinction from scratch.

### Cross-Platform Memory Diagnosis (macOS Findings vs. What Generalizes)

All of the above was investigated and confirmed on macOS. Anyone diagnosing this daemon's memory behavior
on Windows, Linux, or in a cloud/container deployment needs to know which parts of the finding travel and
which don't — conflating them wastes time chasing a macOS-specific mechanism that doesn't exist elsewhere,
or worse, misses a platform-specific failure mode that's *more* severe than anything seen on macOS.

**What generalizes (platform-independent):**
- The underlying claim that matters most: **`brain_daemon.py` has real, non-zero, slow resident-memory
  growth under sustained use, not fully root-caused, currently mitigated (not eliminated) by periodic
  restart + a footprint-aware watchdog.** This is a property of the daemon's own allocation behavior and
  is not macOS-specific — expect it on every platform until the underlying mechanism is actually found.
- **Never trust the platform's "simple" resident-memory number in isolation** — macOS's RSS specifically
  is proven unreliable here (see above), and the general principle — *a process's naively-reported
  resident memory can look fine while the OS is quietly reclaiming/compressing/paging its less-active
  pages under system pressure* — is a real category of behavior on every OS, not a macOS quirk. What
  differs is which metric plays the "RSS lied" role and which plays the "physical footprint told the
  truth" role on each platform (below).
- **Restart-based mitigation (`_periodic_restart`) and the footprint-relative-to-baseline watchdog design
  are platform-agnostic by construction** — both already avoid the mistake of hardcoding a macOS-specific
  absolute threshold or relying on a macOS-specific metric name. No changes needed for other platforms,
  but the watchdog's `[watchdog]` thresholds were calibrated against macOS `vmmap` readings and have not
  been validated against any other platform's equivalent metric — re-derive them per platform rather than
  assuming the same numbers apply.

**What is macOS-specific and will NOT exist on other platforms:**
- The exact mechanism found here — macOS's *memory compressor* (WKdm/lz4-based, introduced OS X
  Mavericks) transparently compressing a process's inactive pages in RAM under system-wide pressure — is
  a macOS subsystem. It has *analogs* elsewhere (below) but not an identical implementation, and the
  specific "sticky ratchet" behavior documented in `backlog/B342.md` (compress once under a pressure
  spike, stay compressed until the app re-touches that memory, independent of whether pressure later
  eases) is a macOS compressor design detail, not guaranteed to hold for Linux's zswap or Windows' memory
  compression.
- Every diagnostic tool used throughout this investigation is macOS-only: `vmmap`, `footprint`,
  `malloc_history`, `heap`, `MallocStackLogging`. **None of these exist on Linux or Windows.** An agent
  reaching for these on another platform will get a command-not-found, not a wrong answer — a useful
  tell that macOS-specific tooling has leaked into a cross-platform debugging session.

**Platform-specific equivalents, for whoever picks this up on another OS:**

| Concern | macOS (used here) | Linux | Windows |
|---|---|---|---|
| "Real" memory footprint (not naive RSS) | `vmmap -summary` Physical footprint | `/proc/[pid]/status` `VmRSS` + `VmSwap` combined; `smem -P`; for containers, the cgroup's `memory.current`/`memory.stat` (`docker stats`, `kubectl top pod`) is more authoritative than any in-container process view | Sysinternals **VMMap** or **RAMMap**; Task Manager's "Memory (active private working set)" column, not bare "Memory" |
| Per-category allocation breakdown | `footprint --sample` (dirty/swapped/clean/regions) | `pmap -x <pid>`; `/proc/[pid]/smaps_rollup`; `valgrind --tool=massif` for allocation-site attribution | Sysinternals **VMMap**'s category view; ETW heap-tracing for allocation-site attribution |
| Native allocation call-stack tracing | `MallocStackLogging` + `malloc_history`/`heap` | `valgrind --tool=massif`, `heaptrack`, or `perf record` + `perf report` (no sudo/root needed for the process-owner case, unlike macOS's `task_for_pid` gate) | Sysinternals **VMMap** (heap snapshots) or Visual Studio's native memory profiler |
| OS-level compression/paging signal | `footprint`'s per-category `swapped` column; `vm_stat`'s compressor pages | `zswap`/`zram` stats under `/sys/kernel/debug/zswap/` if enabled (**not enabled by default on most distros** — plain swap-to-disk or no swap at all is more common, especially in containers); `vmstat` for swap activity | Task Manager's "Compressed" memory figure (Windows 10+ has its own memory compression, conceptually similar to macOS's); `RAMMap`'s "Standby"/"Modified" breakdown |
| System-wide memory pressure (the actual driver found here) | `top -l 1` `PhysMem:` line; `vm_stat`'s free/compressor pages | `free -h`; `/proc/meminfo`'s `MemAvailable`; **for containers, the container's own cgroup limit, not host-wide free memory, is what matters** — check `memory.max`/`memory.current` under the container's cgroup, not `free -h` on the host | Task Manager's overall memory graph; `Get-Counter '\Memory\Available MBytes'` |

**The one asymmetry that matters most for a cloud/container deployment, stated plainly: macOS's
compressor is a *graceful* response to pressure — it degrades performance, it does not kill the process.
Many container runtimes and Kubernetes are configured with a hard memory limit and no swap at all, so the
exact same underlying resident-memory growth this section describes can manifest as a sudden, hard
`OOMKilled` event instead of a gentle compression curve.** This makes the underlying resident-footprint-
reduction work (B355, the prepared-statement cache, and whatever eventually root-causes the growth itself)
*more* consequential in a constrained cloud deployment than it was on this macOS development machine, not
less — there is no graceful degradation to fall back on if a container's memory limit is set tight and
swap is disabled. Anyone deploying via the AWS/multi-tenant topology (`docs/ARCHITECTURE.md`'s Deployment
Model / B312-B326) should set container memory limits with real headroom above the observed baseline
(currently ~1.2GB fresh-start, see B355 above) and monitor for `OOMKilled` restarts specifically, not just
CPU/latency metrics — an OOM-killed container looks like a crash, not a slow leak, and would not surface
the same way `vmmap`-based diagnosis did here.
