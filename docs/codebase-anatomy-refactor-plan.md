# Codebase Anatomy Refactor Plan

Status: proposed v0.2 migration  
Audience: maintainers, contributors, and coding agents  
Primary references: `docs/ARCHITECTURE.md`, `docs/ecosystem-rules.md`

## Purpose

This plan describes how to reorganize Campy's memory-engine code around functional brain regions when the project is ready for a deeper architecture refactor.

The goal is contributor clarity. A human or agent should be able to answer:

- Where does capture or ingestion code go?
- Where does consolidation logic live?
- Where do retrieval tools and context bundle logic belong?
- Which modules are allowed to touch storage?
- Which code must remain isolated from external agent runtimes?

This is a navigation and boundary refactor, not a behavior rewrite. The first successful version should preserve runtime behavior while making the repository easier to understand.

## Timing

Do not begin the file-moving migration until the install path is stable and Campy has been used successfully in real local workflows.

Recommended readiness gate:

- `campy install-plugin --target codex` works from source and installed package modes.
- The daemon starts reliably through the supported install path.
- Codex, Claude Code, and at least one GUI-style adapter path have been smoke tested.
- The current skill/plugin cleanup work has settled.
- No major adapter registration or packaging card is mid-flight.

The refactor should be treated as a v0.2 architecture milestone, not as a quick cleanup.

## Non-Goals

- Do not redesign the Gated Consolidation Loop.
- Do not change MCP tool contracts.
- Do not change Kuzu schema semantics.
- Do not merge Campy with ARC or benchmark runtime code.
- Do not introduce new durable memory stores.
- Do not remove old import paths until compatibility has been available for at least one migration window.

## Target Shape

Six functional brain regions handle memory capture, consolidation, storage, retrieval, and procedural learning.

```text
campy/
  brain/
    brainstem/
    sensory_cortex/
    temporal_lobe/
    hippocampus/
    thalamus/
    basal_ganglia/
  adapters/
  cli/
  data/
```

## Region Responsibilities

| Region | Responsibility | Initial Contents |
|---|---|---|
| `brainstem/` | Daemon lifecycle, status, telemetry, config, maintenance sweeps | daemon startup, activity log, observability, config, phase/status helpers, sweeps |
| `sensory_cortex/` | Capture, ingestion, parsing, normalization, local deterministic NLP | capture connectors, ingestion entrypoints, tabular ingestion, spaCy parsing wrappers |
| `temporal_lobe/` | Consolidation, classification, entity routing, salience, anomaly handling | Gated Consolidation Loop steps, dictionary routing, memory routing, anomaly detection |
| `hippocampus/` | Durable graph memory, schema, quest identity, embeddings, storage facade | schema, Kuzu client abstraction, embeddings, quest state, semantic quest routing |
| `thalamus/` | Retrieval routing, tool surface, graph traversal, context bundles, working context formatting | MCP tool implementations, tool schemas, `current_truth`, `compile_context`, formatters, retrieval decision helpers |
| `basal_ganglia/` | Procedural learning, action selection, reward prediction, exploration policy | frustration cluster detection, procedure synthesis, maturity lifecycle, Go/No-Go gating |

Future split candidates:

- `prefrontal_cortex/`: split from `thalamus/` if working memory, File Bridge, trigger manifests, and context projection become large enough to deserve a separate home.
- `amygdala/`: split from `temporal_lobe/` if salience, valence, behavioral guards, and anomaly code grow into an independent subsystem.

## Current-To-Target Mapping

This mapping is intentionally approximate. Verify imports and tests before moving each file.

| Current Path | Target Region | Notes |
|---|---|---|
| `brain_daemon.py` | `brainstem/` | Runtime entrypoint may remain as a thin root shim for compatibility. |
| `campy/brain_daemon.py` | `brainstem/` | Package entrypoint should delegate to region implementation. |
| `mcp_engine/activity_log.py` | `brainstem/` | Operator-facing activity feed. |
| `mcp_engine/config.py` | `brainstem/` | Runtime config loading. |
| `mcp_engine/observability.py` | `brainstem/` | Telemetry and operational visibility. |
| `mcp_engine/rest_api.py` | `brainstem/` | Local status/control APIs; loopback only. |
| `mcp_engine/phase.py` | `brainstem/` | Lifecycle/phase helpers. |
| `mcp_engine/sweep.py` | `brainstem/` | Background maintenance. Could later move to `basal_ganglia/`. |
| `mcp_engine/sweep_patterns.py` | `brainstem/` | Sweep support until salience/procedure split is clearer. |
| `mcp_engine/capture.py` | `sensory_cortex/` | Durable transcript capture fallback. |
| `mcp_engine/ingest.py` | `sensory_cortex/` | Data ingestion entrypoint. |
| `mcp_engine/tabular_ingest.py` | `sensory_cortex/` | Tabular ingestion pipeline. |
| `mcp_engine/tabular_store.py` | `sensory_cortex/` | Per-dataset SQLite storage for ingested tabular data; document as not durable agent memory. |
| `mcp_engine/loop/step1_ner.py` | `sensory_cortex/` or `temporal_lobe/loop/` | Prefer keeping loop steps together initially; extract parser services only if useful. |
| `mcp_engine/loop/*` | `temporal_lobe/loop/` | Keep the Gated Consolidation Loop coherent during first migration. |
| `mcp_engine/dictionary.py` | `temporal_lobe/` | Domain dictionary and entity routing support. |
| `mcp_engine/memory_router.py` | `temporal_lobe/` | Routes incoming data to graph/tabular/document pipelines. |
| `mcp_engine/warm_frontier.py` | `temporal_lobe/` | Passive pre-activation/salience until an `amygdala/` split is justified. |
| `mcp_engine/schema.py` | `hippocampus/` | Kuzu schema DDL. |
| `mcp_engine/graph/kuzu_client.py` | `hippocampus/graph/` | Only module that imports Kuzu directly. |
| `mcp_engine/graph/embeddings.py` | `hippocampus/graph/` | Embedding wrapper tied to graph storage. |
| `mcp_engine/quest.py` | `hippocampus/` | Quest identity and durable project context. |
| `mcp_engine/hippocampus.py` | `hippocampus/` | Preserve semantic quest routing meaning; avoid reducing this to DB plumbing only. |
| `mcp_engine/tools/` | `thalamus/tools/` | MCP tool implementations. |
| `mcp_engine/tool_schemas.py` | `thalamus/` | Canonical tool schemas; maintain stable public contracts. |
| `mcp_engine/bundle_compiler.py` | `thalamus/` | Heterogeneous context retrieval. |
| `mcp_engine/memory_decision.py` | `thalamus/` | Recall routing decision helper. |
| `mcp_engine/formatters/` | `thalamus/formatters/` | Agent-specific context bundle output shapes. |
| `mcp_engine/analogical.py` | `thalamus/` | Retrieval flavor; may later move if plan/lesson logic grows. |
| `mcp_engine/working_memory.py` | `thalamus/` initially | Candidate for future `prefrontal_cortex/`. |
| `mcp_engine/file_bridge.py` | `thalamus/` initially | Candidate for future `prefrontal_cortex/`; enforce path safety tests. |
| `mcp_engine/trigger_manifest.py` | `thalamus/` initially | Candidate for future `prefrontal_cortex/` or `basal_ganglia/`. |
| `mcp_engine/wiki_projection.py` | `thalamus/` initially | Context/output projection from graph state. |

## Repository Firewalls

These rules should be documented and enforced with tests before any file moves.

### Campy And Agent Runtime Boundary

Production code under `campy/` and `mcp_engine/` must not import from:

- `agents/`
- `benchmarks/`
- sibling ARC runtime repositories

Agent runtime and benchmark code must communicate with Campy through:

- MCP tool contracts
- `BrainClientProtocol`
- documented adapter interfaces

Tests may use explicit fixtures or integration probes, but production imports should stay clean.

### Storage Boundary

KuzuDB remains the single source of truth for durable memory state.

Rules:

- Only the graph storage facade may import or call Kuzu directly.
- Do not add durable shadow stores for agent memory state.
- SQLite tabular stores are allowed only as per-dataset backing stores for ingested tabular data, with graph metadata/facts remaining discoverable through Campy.
- In-memory structures are allowed only as caches over graph-backed state.

### Transport Boundary

MCP adapter transport must remain stdio/Unix-domain-socket based.

Local UI/status services may bind to `127.0.0.1` only. They must never bind to `0.0.0.0` or expose external network surfaces.

### File Safety Boundary

Any code that writes files, especially context projection code, must:

- canonicalize paths with `resolve()` or equivalent
- reject directory traversal
- reject symlink escapes
- restrict writes to intended project or runtime directories
- use allowlisted file types where practical

## Migration Strategy

## Orchestrated Subagent Execution Model

This refactor is intentionally shaped so lower-cost coding subagents can do most of the mechanical work while a senior/orchestrator agent owns architecture decisions, sequencing, and final review.

The orchestrator should not hand a subagent the entire migration. Each subagent gets one bounded packet with:

- a small file set
- a target region
- explicit allowed edits
- explicit forbidden edits
- required tests
- a short handoff report

The orchestrator is responsible for:

- choosing the next packet
- resolving ambiguous region ownership
- reviewing public API and tool-contract changes
- deciding whether a compatibility shim is acceptable
- deciding when to pause the migration
- running broader integration tests after packet completion
- updating this plan if reality diverges from the intended mapping

Subagents are responsible for:

- moving or preparing only the files named in their packet
- preserving behavior
- keeping old imports working unless told otherwise
- running packet-level tests
- reporting exact files touched, tests run, and unresolved questions

Subagents should not:

- redesign behavior
- change MCP tool names, schemas, or output contracts
- change Kuzu schema semantics
- remove compatibility shims
- modify unrelated folders
- "clean up" opportunistically outside their packet
- make product naming decisions
- silence failing tests without explaining the failure

## Subagent Handoff Contract

Every subagent should end with this short report:

```markdown
## Packet Result

Packet: <id and name>
Status: complete | partial | blocked

Files changed:
- <path>

Behavior changes:
- None
- Or list intentional changes

Compatibility:
- Old import paths preserved: yes | no | n/a
- Public tool contracts changed: no | yes, explain

Tests run:
- <command> -> pass | fail

Open questions:
- <question or "None">

Notes for orchestrator:
- <anything the next packet needs to know>
```

The orchestrator should reject or rework packets that do not include this information.

## Subagent Packet Template

Use this template when creating a work item for a subagent:

```markdown
# Refactor Packet <id>: <name>

## Goal

<One sentence describing the desired repository state after this packet.>

## Files In Scope

- <path>

## Files Out Of Scope

- Everything not listed above unless needed for imports/tests.

## Allowed Edits

- Move the scoped files to <target package>.
- Add compatibility shims at old paths.
- Update imports needed for the scoped files and their direct tests.
- Add or update focused tests for the moved behavior.

## Forbidden Edits

- Do not change behavior.
- Do not change MCP tool names or schemas.
- Do not change Kuzu schema semantics.
- Do not remove compatibility shims.
- Do not rewrite unrelated modules.

## Required Checks

- `python -m compileall <changed package roots>`
- `<focused pytest command>`
- `rg "<old path or import>" <relevant dirs>`

## Handoff

Return the Subagent Handoff Contract exactly.
```

### Phase 0: Stabilize Before Moving

Goal: confirm the project is ready.

Tasks:

- Verify install flow from source mode.
- Verify installed-package or pipx mode.
- Verify daemon startup and activity feed.
- Verify plugin skill installation and archive behavior.
- Run focused adapter smoke tests.
- Record the current baseline test command and result.

Exit criteria:

- Maintainer agrees install/use is stable enough for an architecture-only migration.
- No urgent packaging or adapter registration work is blocked on current paths.

Orchestrator-only phase:

- Do not delegate the readiness decision.
- Subagents may run smoke checks and report results, but the orchestrator decides whether migration starts.

### Phase 1: Documentation First

Goal: teach the new anatomy before moving code.

Tasks:

- Add `docs/codebase-anatomy.md`.
- Include the five-region table.
- Include "where do I put my change?" guidance.
- Link it from `docs/ARCHITECTURE.md`.
- Link it from `docs/ecosystem-rules.md`.
- Add a short pointer from `README.md`, `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` if appropriate.

Exit criteria:

- Contributors can understand the target structure without reading migration diffs.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `DOC-1` | subagent | Draft `docs/codebase-anatomy.md` from this plan | No code changes. |
| `DOC-2` | subagent | Add short links from contributor-facing docs | Touch only docs named by orchestrator. |
| `DOC-REVIEW` | orchestrator | Review language for contributor clarity | Remove over-formal wording and stale paths. |

### Phase 2: Boundary Tests

Goal: prevent accidental architecture drift before files start moving.

Suggested tests:

- No production Campy module imports `agents` or `benchmarks`.
- No production agent/benchmark module imports internal `mcp_engine` or `campy.brain` modules except approved protocol modules.
- Only the storage facade imports `kuzu`.
- No production code binds a server to `0.0.0.0`.
- File projection code rejects path traversal and symlink escape cases.

Exit criteria:

- Boundary tests fail on intentional violations.
- Existing test suite passes with no file moves.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `BOUNDARY-1` | subagent | Add AST test for forbidden production imports between Campy and agent/benchmark code | Keep allowlist small and explicit. |
| `BOUNDARY-2` | subagent | Add Kuzu import isolation test | Allowed path should be current facade first, then updated during migration. |
| `BOUNDARY-3` | subagent | Add loopback binding check for `0.0.0.0` | Allowlist only documented test fixtures if needed. |
| `BOUNDARY-4` | subagent | Add path traversal/symlink tests for file projection code | May require orchestrator if current code lacks a clean helper seam. |
| `BOUNDARY-REVIEW` | orchestrator | Confirm tests enforce architecture without blocking legitimate tests | Review allowlists carefully. |

### Phase 3: Create Region Packages With Compatibility Shims

Goal: introduce the package skeleton without breaking current imports.

Tasks:

- Create `campy/brain/__init__.py`.
- Create region packages:
  - `campy/brain/brainstem/`
  - `campy/brain/sensory_cortex/`
  - `campy/brain/temporal_lobe/`
  - `campy/brain/hippocampus/`
  - `campy/brain/thalamus/`
- Add short `README.md` files inside each region.
- Do not move runtime code yet unless a tiny pilot module is chosen.

Exit criteria:

- Package skeleton imports cleanly.
- Docs and tests recognize the region layout.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `SKELETON-1` | subagent | Create `campy/brain/` packages and minimal READMEs | No runtime moves. |
| `SKELETON-2` | subagent | Add package import smoke test | Test package importability only. |
| `SKELETON-REVIEW` | orchestrator | Validate region descriptions against architecture docs | Resolve naming questions before file moves. |

### Phase 4: Move Brainstem First

Goal: migrate low-risk operational code before memory semantics.

Candidate moves:

- `mcp_engine/activity_log.py`
- `mcp_engine/config.py`
- `mcp_engine/observability.py`
- `mcp_engine/phase.py`
- `mcp_engine/sweep.py`
- `mcp_engine/rest_api.py`

Approach:

- Move implementation files into `campy/brain/brainstem/`.
- Leave old `mcp_engine/*` modules as compatibility shims importing from new locations.
- Update internal imports gradually to new paths.
- Keep public CLI and daemon entrypoints stable.

Exit criteria:

- Tests pass.
- Daemon startup still works.
- Activity feed still writes expected events.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `BRAINSTEM-1` | subagent | Move `activity_log.py`, `observability.py`, and direct tests | Low-risk telemetry packet. |
| `BRAINSTEM-2` | subagent | Move `config.py` and `phase.py` | Watch import cycles. |
| `BRAINSTEM-3` | subagent | Move `sweep.py` and `sweep_patterns.py` | Keep behavior and schedules unchanged. |
| `BRAINSTEM-4` | subagent | Move `rest_api.py` | Verify loopback-only binding rule. |
| `BRAINSTEM-REVIEW` | orchestrator | Run daemon/activity smoke and inspect compatibility shims | Decide if root daemon shims need adjustment. |

### Phase 5: Move Sensory Cortex

Goal: isolate intake and normalization.

Candidate moves:

- `mcp_engine/capture.py`
- `mcp_engine/ingest.py`
- `mcp_engine/tabular_ingest.py`
- `mcp_engine/tabular_store.py`

Approach:

- Keep ingestion behavior unchanged.
- Document that tabular SQLite files are dataset backing stores, not durable agent memory truth.
- Ensure `notify_turn` still routes through the same MCP contract.

Exit criteria:

- Passive ingestion tests pass.
- Durable capture tests pass.
- Tabular ingestion tests pass.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `SENSORY-1` | subagent | Move `capture.py` and capture tests | Preserve durable capture semantics. |
| `SENSORY-2` | subagent | Move `ingest.py` | Confirm `notify_turn` path still works. |
| `SENSORY-3` | subagent | Move `tabular_ingest.py` and `tabular_store.py` | Document SQLite role as dataset backing store only. |
| `SENSORY-REVIEW` | orchestrator | Run ingestion/capture integration checks | Confirm no new durable shadow memory path was introduced. |

### Phase 6: Move Hippocampus

Goal: make durable graph ownership obvious.

Candidate moves:

- `mcp_engine/schema.py`
- `mcp_engine/graph/kuzu_client.py`
- `mcp_engine/graph/embeddings.py`
- `mcp_engine/quest.py`
- `mcp_engine/hippocampus.py`

Approach:

- Keep Kuzu-specific syntax isolated to the graph facade.
- Preserve `mcp_engine/hippocampus.py` semantic quest routing meaning in docs.
- Update tests to assert only the graph facade imports `kuzu`.

Exit criteria:

- Schema initialization works.
- Quest routing works.
- Retrieval tests still pass against the moved graph facade.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `HIPPOCAMPUS-1` | subagent | Move `graph/kuzu_client.py` and `graph/embeddings.py` | Highest care packet; preserve Kuzu facade contract. |
| `HIPPOCAMPUS-2` | subagent | Move `schema.py` | Run schema-focused tests. |
| `HIPPOCAMPUS-3` | subagent | Move `quest.py` and `hippocampus.py` | Preserve semantic quest routing behavior. |
| `HIPPOCAMPUS-REVIEW` | orchestrator | Run storage/retrieval smoke and inspect Kuzu import isolation | Decide whether any old graph paths remain canonical temporarily. |

### Phase 7: Move Temporal Lobe

Goal: group consolidation and classification.

Candidate moves:

- `mcp_engine/loop/`
- `mcp_engine/dictionary.py`
- `mcp_engine/memory_router.py`
- `mcp_engine/warm_frontier.py`

Approach:

- Move the loop as a whole.
- Avoid splitting individual loop steps into separate regions during the first migration.
- Keep old loop import paths as compatibility shims.

Exit criteria:

- `notify_turn` write flow still runs all expected loop steps.
- Gated Consolidation Loop tests pass.
- Anomaly detection and associative trigger tests pass.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `TEMPORAL-1` | subagent | Move `dictionary.py`, `memory_router.py`, and direct tests | Preparatory routing packet. |
| `TEMPORAL-2` | subagent | Move `loop/step1*`, `step2*`, `step3*` | Keep loop package coherent; no algorithm changes. |
| `TEMPORAL-3` | subagent | Move `loop/step4*`, `step5*`, `step6*`, `step7*` | Preserve confidence gates and arbitration behavior. |
| `TEMPORAL-4` | subagent | Move `loop/anomaly_detection.py` and `warm_frontier.py` | Keep salience/anomaly behavior in temporal lobe for now. |
| `TEMPORAL-REVIEW` | orchestrator | Run full write-flow tests and inspect loop imports | This is a high-risk review checkpoint. |

### Phase 8: Move Thalamus

Goal: group retrieval and output routing.

Candidate moves:

- `mcp_engine/tools/`
- `mcp_engine/tool_schemas.py`
- `mcp_engine/bundle_compiler.py`
- `mcp_engine/memory_decision.py`
- `mcp_engine/formatters/`
- `mcp_engine/analogical.py`
- `mcp_engine/working_memory.py`
- `mcp_engine/file_bridge.py`
- `mcp_engine/trigger_manifest.py`
- `mcp_engine/wiki_projection.py`

Approach:

- Preserve MCP tool names and schemas exactly.
- Keep `plugin/skills/recall/SKILL.md` aligned with tool names.
- Consider deferring `file_bridge.py`, `working_memory.py`, and `trigger_manifest.py` if their path safety or hook integration makes the move too noisy.

Exit criteria:

- MCP tool catalog tests pass.
- `compile_context`, `current_truth`, and `explore_graph` behavior is unchanged.
- File Bridge and trigger manifest tests pass.

Suggested subagent packets:

| Packet | Owner | Scope | Notes |
|---|---|---|---|
| `THALAMUS-1` | subagent | Move `tool_schemas.py` only | Public contract packet; orchestrator review required. |
| `THALAMUS-2` | subagent | Move `tools/` package | Preserve MCP names and handlers. |
| `THALAMUS-3` | subagent | Move `bundle_compiler.py`, `memory_decision.py`, and `formatters/` | Verify bundle output snapshots if present. |
| `THALAMUS-4` | subagent | Move `analogical.py` and retrieval-adjacent helpers | Keep retrieval behavior unchanged. |
| `THALAMUS-5` | subagent | Move `working_memory.py`, `file_bridge.py`, `trigger_manifest.py`, and `wiki_projection.py` only if orchestrator approves | Defer if path/hook surface is noisy. |
| `THALAMUS-REVIEW` | orchestrator | Run MCP tool smoke tests and inspect tool catalog diffs | Any public contract change blocks the packet. |

### Phase 9: Remove Compatibility Shims Later

Goal: clean up old paths after downstream references have migrated.

Do not remove shims in the same PR that moves major modules.

Tasks:

- Search docs, skills, backlog plans, and tests for old paths.
- Update examples and contributor references.
- Mark old paths deprecated for one release or migration window.
- Remove shims only after the project has run successfully with new imports.

Exit criteria:

- No production imports use old paths.
- Docs no longer teach old paths as canonical.

Orchestrator-heavy phase:

- Subagents may search and update old references.
- The orchestrator decides when compatibility shims can be removed.
- Do not remove shims while any supported package release, adapter, or docs page still points to old paths.

## Suggested Boundary Test Sketches

### No Campy-To-Agent Imports

```python
def test_campy_production_code_does_not_import_agent_runtime():
    forbidden = ("agents", "benchmarks")
    # Parse Python AST under campy/ and mcp_engine/.
    # Fail if any production module imports a forbidden package.
```

### Kuzu Import Isolation

```python
def test_only_graph_facade_imports_kuzu():
    allowed = {"campy/brain/hippocampus/graph/kuzu_client.py"}
    # Parse Python AST for import kuzu / from kuzu import.
    # Fail outside the allowed facade.
```

### No External Listen Bindings

```python
def test_no_external_server_bindings():
    # Search production code for 0.0.0.0 and reject unless explicitly allowlisted.
```

### Path Projection Safety

```python
def test_file_bridge_rejects_directory_escape(tmp_path):
    # Attempt ../ escape and symlink escape against projection write helpers.
    # Assert the write is rejected before touching disk outside allowed root.
```

## PR Strategy

Prefer several small PRs over one giant move.

Recommended PR sequence:

1. `docs: add codebase anatomy map`
2. `test: enforce architecture boundaries`
3. `refactor: add brain region package skeleton`
4. `refactor: move brainstem modules`
5. `refactor: move sensory cortex modules`
6. `refactor: move hippocampus modules`
7. `refactor: move temporal lobe modules`
8. `refactor: move thalamus modules`
9. `chore: remove deprecated mcp_engine shims`

Each PR should include:

- A brief migration note.
- A list of moved files.
- Compatibility import status.
- Test commands run.
- Any known remaining old-path references.

## Orchestrator Review Gates

The orchestrator should pause for review at these gates before assigning the next packet.

| Gate | When | Required Review |
|---|---|---|
| `G0` | Before Phase 1 | Confirm install/use stability and migration timing. |
| `G1` | After documentation | Confirm the five-region map is clear and not overfitted. |
| `G2` | After boundary tests | Confirm tests enforce real boundaries without brittle false positives. |
| `G3` | After package skeleton | Confirm region package names and README responsibilities. |
| `G4` | After each region move | Run focused tests, inspect shims, review import graph. |
| `G5` | Before moving `tool_schemas.py` or `tools/` | Confirm no public MCP contract changes. |
| `G6` | Before removing compatibility shims | Confirm no supported docs, adapters, package data, or tests still depend on old paths. |

Use this review checklist at each gate:

- Did the packet stay inside scope?
- Are compatibility imports present where needed?
- Did any public tool name, schema, or response shape change?
- Did any module start importing across a forbidden boundary?
- Did any new storage path appear outside Kuzu-backed memory rules?
- Are test failures explained rather than hidden?
- Is the next packet still safe, or should the plan be updated?

## Ready-To-Use Subagent Prompts

These prompts are intentionally constrained. Paste one packet prompt into a subagent session and replace bracketed fields.

### Documentation Packet Prompt

```markdown
You are helping with the Campy codebase anatomy refactor.

Read:
- docs/codebase-anatomy-refactor-plan.md
- docs/ARCHITECTURE.md
- docs/ecosystem-rules.md

Packet: [DOC-1 or DOC-2]

Goal:
[specific packet goal]

Rules:
- Make documentation-only changes.
- Do not move code.
- Do not edit behavior.
- Keep wording contributor-friendly and practical.
- Prefer short navigation guidance over grand architecture language.

Required checks:
- `rg -n "codebase-anatomy|brainstem|sensory_cortex|temporal_lobe|hippocampus|thalamus" docs README.md AGENTS.md CLAUDE.md GEMINI.md`

Return the Subagent Handoff Contract from docs/codebase-anatomy-refactor-plan.md.
```

### Boundary Test Packet Prompt

```markdown
You are helping with the Campy codebase anatomy refactor.

Read:
- docs/codebase-anatomy-refactor-plan.md
- docs/ARCHITECTURE.md
- docs/ecosystem-rules.md

Packet: [BOUNDARY-*]

Goal:
[specific boundary test goal]

Rules:
- Add focused architecture tests only.
- Do not move runtime code.
- Keep allowlists explicit and small.
- Tests should parse/search production code, not rely on fragile incidental output.
- If the current code violates the proposed rule, report the violation instead of weakening the rule silently.

Required checks:
- `.venv/bin/pytest -q [new test file]`
- `rg -n "[forbidden pattern or target import]" [relevant dirs]`

Return the Subagent Handoff Contract from docs/codebase-anatomy-refactor-plan.md.
```

### Module Move Packet Prompt

```markdown
You are helping with the Campy codebase anatomy refactor.

Read:
- docs/codebase-anatomy-refactor-plan.md
- docs/ARCHITECTURE.md
- docs/ecosystem-rules.md

Packet: [REGION-ID]
Target region: [campy/brain/<region>/]

Files in scope:
- [file]

Goal:
Move only the scoped implementation files into the target region while preserving behavior and old import paths.

Allowed edits:
- Move scoped files into the target region.
- Add old-path compatibility shims that re-export the moved module contents.
- Update imports required by the moved files and their direct tests.
- Add or update focused tests only if needed.

Forbidden edits:
- Do not change behavior.
- Do not change MCP tool names, schemas, or return shapes.
- Do not change Kuzu schema semantics.
- Do not remove compatibility shims.
- Do not refactor unrelated modules.
- Do not update broad docs unless the packet explicitly says to.

Required checks:
- `python -m compileall campy mcp_engine`
- `.venv/bin/pytest -q [focused tests]`
- `rg -n "from mcp_engine|import mcp_engine|from campy.brain|import campy.brain" [relevant dirs]`

Return the Subagent Handoff Contract from docs/codebase-anatomy-refactor-plan.md.
```

### Reference Cleanup Packet Prompt

```markdown
You are helping with the Campy codebase anatomy refactor.

Read:
- docs/codebase-anatomy-refactor-plan.md

Packet: [CLEANUP-*]

Goal:
Update references from old module paths to new canonical paths after the orchestrator has approved compatibility-shim cleanup.

Rules:
- Do not remove shims unless explicitly asked.
- Do not rewrite historical backlog content unless the orchestrator says those docs are active guidance.
- Prefer adding "new path" notes over deleting useful historical context.
- Keep examples accurate.

Required checks:
- `rg -n "[old path]" docs tests campy mcp_engine adapters plugin skills`
- `.venv/bin/pytest -q [affected tests]`

Return the Subagent Handoff Contract from docs/codebase-anatomy-refactor-plan.md.
```

## Packet Sizing Rules

Lower-cost subagents are most useful when the packet is mechanical and bounded. Keep packet size small enough that the agent can finish with high confidence.

Good packet size:

- 1 to 5 implementation files
- 1 target region
- 1 focused test family
- no public contract changes
- no schema changes
- no cross-region design decisions

Too large for a subagent:

- moving all of `tools/` and changing tool schema registration at the same time
- moving loop steps and changing consolidation behavior
- moving storage code and changing schema initialization
- removing old paths while docs and adapters still reference them
- combining docs, imports, tests, and behavior cleanup in one pass

Escalate to the orchestrator when:

- import cycles appear
- a test failure suggests behavior changed
- a module clearly fits multiple regions
- a public import path is used by package entrypoints
- file safety code lacks a testable helper
- a compatibility shim would be misleading or unsafe

## Compatibility Shim Pattern

When moving a module, leave the old path as a thin compatibility shim unless the orchestrator explicitly says otherwise.

Preferred shape:

```python
"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.<region>.<module>
"""

from campy.brain.<region>.<module> import *  # noqa: F401,F403
```

Rules:

- Shims should contain no behavior.
- Shims should be temporary but may remain for one migration window.
- Shims should mention the canonical path.
- Do not stack shims through multiple old paths if a direct import is possible.

## Contributor Guidance To Add Later

Add this to `docs/codebase-anatomy.md` when the migration starts:

```text
When adding code, choose the folder by function:

- lifecycle/status/telemetry -> brainstem
- input capture/parsing -> sensory_cortex
- consolidation/classification/salience -> temporal_lobe
- graph schema/storage/quest identity -> hippocampus
- retrieval/tools/context bundles -> thalamus

Adapters should stay thin. They translate client-specific events into Campy protocol calls.
They should not own memory logic.
```

## Success Criteria

The refactor is successful when:

- New contributors can locate likely files from the anatomy table.
- Agents stop guessing between `mcp_engine`, `campy`, and adapter locations.
- Import boundary tests prevent Campy/agent coupling.
- MCP tool contracts are unchanged.
- Kuzu access remains isolated.
- Install and adapter smoke tests still pass.
- Old paths are either compatibility shims or fully removed after a deliberate migration window.

## Open Questions

- Should `working_memory.py`, `file_bridge.py`, and `trigger_manifest.py` remain in `thalamus/` initially, or should `prefrontal_cortex/` be introduced once those modules move?
- Should `sweep.py` remain in `brainstem/`, or does it deserve a future `basal_ganglia/` split with procedure learning and auto-skill compilation?
- Should `warm_frontier.py` remain in `temporal_lobe/`, or become the seed of a future `amygdala/` package for salience and valence?
- How long should compatibility imports from `mcp_engine.*` remain after the migration?
