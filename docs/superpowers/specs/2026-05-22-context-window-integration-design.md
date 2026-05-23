# Campy Context Window Integration — "The Layer Cake"

## Context

Campy has a sophisticated memory system (KuzuDB graph, Gated Consolidation Loop, 28 MCP tools, compile_context bundle compiler) but agents rarely use it. The root problem: agents never call Campy on their own. The memory system waits to be queried, and nobody queries it.

Matt Pocock's skills (mattpocock/skills) solve the process discipline problem — they force agents through structured workflows that read domain glossaries, write ADRs, and manage handoffs. But his skills store state in flat markdown files that are brittle, static, and don't scale.

This design bridges the gap: Campy provides the memory infrastructure, Matt's skills (and Campy-native skills) provide the process discipline, and four integration layers ensure the right information reaches the context window at the right time — without the agent needing to decide to ask.

### Cognitive Model

| Human System | Agent Equivalent | Role |
|---|---|---|
| Prefrontal Cortex | Agent (LLM) | Reasoning, decision-making, attention |
| Working Memory | Context Window | Holds active information for current task |
| Long-Term Memory | Campy (KuzuDB graph) | Stores persistent knowledge, patterns, procedures |
| Hippocampus | This integration layer | Moves information between LTM and working memory |

## Architecture: Four Layers

Each layer is independent and delivers standalone value. They compound when combined.

### Layer 1: File Bridge — "Semantic Memory"

**Purpose:** Campy daemon generates and maintains standard files that skills and agents expect, populated from the graph. Bidirectional sync keeps files and graph consistent.

**Files generated per project:**

| File | Source in Graph | Consumed By | Auto-loaded? |
|---|---|---|---|
| `CONTEXT.md` | Concept nodes with domain term gist classes + relationships | Matt's `/grill-with-docs` | No — read on demand by skills |
| `docs/adr/NNNN-slug.md` | Decision nodes with confidence > 0.8 | Matt's `/grill-with-docs`, `/improve-codebase-architecture` | No — read on demand |
| `CLAUDE.md` (one-line pointer) | N/A | Claude Code | Yes — must stay under ~20 tokens |
| `AGENTS.md` (one-line pointer) | N/A | Codex | Yes — must stay lean |
| `GEMINI.md` (one-line pointer) | N/A | Gemini CLI | Yes — must stay lean |

**Critical constraint:** Auto-loaded config files (CLAUDE.md, AGENTS.md, GEMINI.md) must contain only pointers, never substantive content. They burn context budget on every turn. Example pointer: `"This project uses Campy for memory. Call memory_decision before architectural decisions."`

**Regeneration:** Event-driven. Specific triggers:
- **Graph change:** When the GCL writes new Decision, Lesson, or domain Concept nodes, the daemon marks affected projects' files as stale. Regeneration happens within the next sweep cycle (default 300s) or immediately if the change crosses a significance threshold (e.g., new GlobalConstraint).
- **New session:** Detected via the first `notify_turn` call from a previously-unseen session ID. Triggers immediate regeneration for that project.
- **Manual:** `campy context regen [--project PATH]` CLI command. Always available.

**Bidirectional sync:** File watcher detects manual edits to CONTEXT.md or ADR files and ingests changes back through the GCL. The graph is always the source of truth; file edits are treated as new input to the consolidation pipeline.

**What this solves:** When an agent runs `/grill-with-docs`, it reads CONTEXT.md and gets graph-backed domain knowledge automatically. Matt's skill works verbatim. No agent cooperation needed.

### Layer 2: Associative Hooks — "Reflexive Memory"

**Purpose:** Pattern-matched hooks that fire when the agent's current context matches stored patterns in the graph. Catches the agent before it repeats a known mistake or misses a required procedure.

**Architecture:**

```
Graph (source of truth)
  Procedure/Lesson nodes carry trigger metadata:
    - pattern: regex matching tool input or output
    - hook_type: PreToolUse or PostToolUse
    - tool: Bash, Edit, Write, etc.
    - project_scope: optional project filter

Daemon (compiler)
  Generates a "trigger manifest" — a local file of patterns + context snippets
  Regenerated event-driven (graph changes, new triggers learned)

Hook script (runtime)
  Reads trigger manifest (fast local file grep, no daemon IPC)
  If pattern matches → outputs additionalContext with fix/warning/procedure
  If no match → exits silently (zero overhead)
```

**Trigger types:**

| Type | Hook Point | Example |
|---|---|---|
| Action trigger | PreToolUse (Bash) | `docker run\|build` → inject OD container procedure with required env vars |
| Error trigger | PostToolUse (Bash) | `no AWS credentials` → inject SSO refresh procedure |
| Domain trigger | PreToolUse (Edit/Write) | Editing `auth/**` → inject auth-related decisions and constraints |
| Mistake trigger | PreToolUse (Bash) | `git push --force` → inject lesson about lost work |

**Performance:** The hot path is a grep against a local file. Zero daemon round-trip. The daemon only compiles the manifest; it is not in the per-tool-call critical path.

**How triggers are created:**
- Manual: `campy trigger add --pattern "docker run" --procedure "OD Container Setup"`
- Learned: GCL + offline sweep discover patterns and create trigger candidates (marked confidence_low for review)
- From skills: `/campy-learn` walks the user through defining a trigger

**Trigger lifecycle:** Triggers participate in Campy's existing decay model. Active triggers strengthen with successful fires (pathway_strength increases). Triggers that never fire decay via Ebbinghaus curves and are archived. Archived triggers can be resurrected if similar patterns re-emerge.

**Cross-agent support:** Hooks are a Claude Code feature. For Codex/Gemini CLI, Layer 2 degrades to stronger system prompt instructions and MCP tool descriptions until those platforms add hook equivalents. The trigger manifest format is universal; only hook registration differs per agent.

### Layer 3: Anticipatory Engine — "Prospective Memory"

**Purpose:** Background system that discovers patterns in the graph and proactively enriches the context window before problems occur. Not deterministic rules — uses dual-mode pattern discovery (online + offline) to find both known and novel patterns.

**Dual-mode architecture:**

**Online mode (GCL extension — real-time recognition):**
- New Step 4b in the Gated Consolidation Loop: "Associative Pattern Check"
- When the GCL processes a turn containing an error, failure, or significant action:
  1. Check embedding similarity against stored Lessons/Procedures (piggybacks on existing Step 5)
  2. If similarity > threshold, check temporal and sequence context against stored patterns
  3. If match: mark pattern as "active" and write context enrichment to Layer 2's trigger manifest
- Cost: near-zero — additional graph queries during existing GCL processing, no extra LLM calls

**Offline mode (background sweep — retrospective discovery):**
- Runs on the existing sweep cycle or a separate, less frequent cycle (hourly)
- Specialized graph queries per pattern type:
  - **Temporal:** Find (event_type, error_type) pairs where time deltas cluster around a consistent value
  - **Sequence:** Find action chains where the same sequence precedes failures >N times
  - **Frequency:** Find error nodes where occurrence rate is increasing over recent sessions
  - **Analogy:** Find patterns in project A that match emerging patterns in project B
- Candidate patterns are batched and sent to a single lightweight LLM call (local Ollama or Haiku) for validation
- Validated patterns become Lesson/Procedure nodes with trigger metadata, feeding back into online mode

**Feedback loop:**
```
Online (GCL) recognizes known patterns in real-time
    → fires trigger → enriches context window
Offline (sweep) discovers new patterns in retrospect
    → creates new Lesson/Procedure nodes with trigger metadata
Online (GCL) now recognizes newly-discovered patterns too
    → cycle continues — the system gets smarter over time
```

**Temporal properties on Procedure/Lesson nodes:**
- `temporal_event`: what starts the clock (e.g., "sso_credential_export")
- `temporal_threshold`: seconds until the pattern typically manifests (e.g., 28800 for 8h)
- `temporal_confidence`: learned from past accuracy (strengthens/weakens with outcomes)

**Delivery:** Layer 3 does not have its own delivery mechanism. It writes enrichments to Layer 2's trigger manifest or Layer 1's context files. The layers compose — Layer 3 discovers, Layers 1 and 2 deliver.

**Cost model:**
- Online: near-zero (graph queries during existing GCL)
- Offline: one batched LLM call per sweep cycle (~500-2000 tokens per hour)

**Build phases for Layer 3:**
- V1: Time-based patterns (the SSO case)
- V2: Sequence and frequency patterns
- V3: Cross-project analogy patterns

### Layer 4: Process Skills — "Deliberate Recall"

**Purpose:** User or agent-invoked deep retrieval for complex queries. Two skill sets work together: Matt's skills (installed verbatim, upstream updates preserved) and Campy-native skills that complement them.

**Matt's skills (verbatim, enhanced by other layers):**

| Skill | Campy Enhancement |
|---|---|
| `/grill-with-docs` | Reads Campy-generated CONTEXT.md (Layer 1) |
| `/handoff` | Writes to /tmp as usual; Layer 2 hook captures and stores to graph |
| `/diagnose` | Layer 2 injects relevant past errors/lessons during debug phases |
| `/to-prd` | PRD output ingested by Campy through passive ingestion |
| `/to-issues` | Issues get ingested, relationships built in graph |
| `/improve-codebase-architecture` | Reads Campy-generated ADRs (Layer 1) |
| `/tdd` | Test results and patterns fed through GCL |

**Campy-native skills:**

| Skill | What It Does |
|---|---|
| `/campy-brief` | Deep compile_context at session start. Pulls from all graph sources, formatted for active agent type. "Brief me on this repo/branch." |
| `/campy-handoff` | Extends Matt's `/handoff` — writes handoff state to graph with full relational context. Receiving agent gets graph-derived situational awareness. |
| `/campy-recall` | Explicit deep retrieval wrapping memory_decision → appropriate recall tool. For "what did we decide about X?" |
| `/campy-learn` | Teach Campy a new pattern from a recent experience. Creates Procedure/Lesson nodes with trigger and temporal metadata. |

**Skill interaction with layers:**
- Skills can explicitly call Campy MCP tools (compile_context, recall_procedures, etc.)
- Layer 1 provides the files skills expect (CONTEXT.md, ADRs)
- Layer 2 provides automatic context injection while skills are running
- Layer 3 discovers patterns that skills can later leverage

## Build Sequence

| Phase | Layers | What Ships | Value Delivered |
|---|---|---|---|
| **Phase 1** | Layer 1 + Layer 4 (skills) | File Bridge + install Matt's skills + Campy-native skills | `/grill-with-docs` gets graph-backed CONTEXT.md. `/campy-brief` and `/campy-learn` give explicit memory tools. Immediate fix for "agent never calls Campy." |
| **Phase 2** | Layer 2 | Trigger manifest + hook generation + hook script | Reflexive memory — agent gets warnings before repeating mistakes, procedures injected before risky actions. The docker/SSO example works automatically. |
| **Phase 3** | Layer 3 (online) | GCL Step 4b — associative pattern check | Real-time pattern recognition during ingestion. Known patterns fire automatically. |
| **Phase 4** | Layer 3 (offline) | Sweep-based pattern discovery agents | Retrospective pattern discovery. Campy learns new patterns without being told. The system gets smarter over time. |

Each phase delivers standalone value. Dependencies flow downward (Phase N+1 benefits from Phase N infrastructure) but each phase works without later phases.

## Verification Plan

**Phase 1:**
- Install Matt's skills via `npx skills@latest add mattpocock/skills --yes --global`
- Run `campy context regen` and verify CONTEXT.md is generated from graph
- Invoke `/grill-with-docs` and confirm it reads the Campy-generated CONTEXT.md
- Edit CONTEXT.md manually, verify changes are ingested back to graph
- Run `/campy-brief` and confirm compile_context output appears in context window
- Test across agents: verify CLAUDE.md, AGENTS.md, GEMINI.md pointers are generated

**Phase 2:**
- Create a test trigger: `campy trigger add --pattern "echo test" --procedure "Test Procedure"`
- Verify trigger manifest is generated at expected location
- Run `echo test` in Claude Code and verify additionalContext injection
- Test trigger lifecycle: verify decay, archive, and manual removal
- Test cross-project scoping: trigger only fires in specified project

**Phase 3:**
- Process a turn containing an error that matches a stored Lesson
- Verify GCL Step 4b recognizes the pattern and updates trigger manifest
- Verify the next tool call in the session receives the injected context
- Measure latency impact of Step 4b on GCL processing time

**Phase 4:**
- Seed the graph with a temporal pattern (3+ instances of error at ~8h intervals)
- Run the offline sweep and verify the pattern is discovered
- Verify the discovered pattern creates a new trigger in the manifest
- Test the feedback loop: online mode recognizes the newly-discovered pattern

## Open Questions

1. **Trigger manifest format:** YAML, JSON, or a custom binary format optimized for grep performance? Recommendation: JSON for programmatic access from hook scripts; YAML as human-readable alternative.
2. **Hook script language:** Shell script (portable) vs. Python (richer, can call Campy SDK directly)? Recommendation: Shell script for the hot path (grep + output), with Python fallback for complex pattern matching.
3. **Offline sweep frequency:** Use existing 300s sweep or a separate, less frequent cycle? Recommendation: Separate hourly cycle — pattern discovery is expensive and doesn't need real-time freshness.
4. **Cross-agent hook parity:** When Codex/Gemini add hooks, how quickly can we generate adapters? The trigger manifest is agent-agnostic; only the hook registration format differs.
5. **Token budget for Layer 2 injections:** Hard cap per injection? Per turn? Configurable? Recommendation: configurable per-injection cap (default 500 tokens), with a per-turn aggregate cap (default 1000 tokens).
6. **Trigger manifest location:** `~/.campy/triggers/<project-hash>.json` — one manifest per project, co-located with other Campy runtime files.
7. **Hook script location:** `~/.campy/hooks/associative-hook.sh` — single script shared across projects, reads the project-specific manifest based on CWD.
