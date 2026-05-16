# SideQuests Brain — Backlog

> M1–M8 are complete. This backlog tracks post-M8 work.

---

## Codex + GPT Desktop Bring-Up (Execution Order)

Validated 2026-03-24 against live code paths. This is the operational checklist to get Codex CLI and ChatGPT Desktop reliably running.

### P0 — Critical Blockers (Do First)

- [x] **Fix installer seed-path packaging bug** (blocks schema init in pip-installed environments)
  - `sidequests/cli/install.py` uses `PROJECT_ROOT/InvertorsDocs/GistSeedExamples.md` during schema init
  - Ensure seed examples are loadable in installed environments (wheel-safe resource loading)
- [x] **Fix launchd Python interpreter resolution on macOS** (pyenv wrapper can fail under launchd)
  - Harden interpreter resolution in `sidequests/cli/launchd.py`
  - Ensure daemon starts with a real executable path (not shell-wrapper-dependent)
- [x] **Force daemon reload during install/update** (prevents stale tool registry)
  - During install, unload/reload service so newly added MCP tools are actually available
  - Prevent "Unknown tool" failures caused by old daemon process state

### P1 — End-to-End Bring-Up Validation

- [x] **Run full clean-machine install validation for both targets**
  - All 7 installer steps passed on first run 2026-03-24
  - Two hardening fixes applied: Step 4 DB-lock graceful skip + Step 7 socket-poll retry
- [x] **Codex live verification** — verified 2026-03-24
  - `codex` CLI 0.116.0 installed at `/opt/homebrew/bin/codex`
  - `~/.codex/config.toml` written with `[mcp_servers.sidequests]` entry pointing to adapter
  - `tools/list` round-trip confirmed: adapter returns all 11 tools from Brain Daemon via Unix socket
- [x] **ChatGPT Desktop live verification**
  - SSE endpoint confirmed responding at `http://127.0.0.1:7799/sse`
  - `sidequests status` shows all 4 checks green: socket, 11 tools, schema, SSE
  - Manual step remaining: add connector in ChatGPT Desktop app UI

### P2 — Reliability / Data Safety

- [x] **Implement offline queue replay on daemon recovery**
  - Adapters already queue failed writes to `~/.sidequests/offline_queue.jsonl`
  - Add replay + clear-on-success behavior when daemon returns
- [x] **Increase install smoke-test readiness window**
  - Fixed 2026-03-24: replaced bare `time.sleep(3)` with `_wait_for_daemon(max_wait=20, interval=2)` polling loop
  - Companion fix: Step 4 (schema init) now skips gracefully when DB is locked by running daemon

### P3 — UX / Consumer Readiness (After Bring-Up)

- [x] **B14 Proactive Insight Surfacing**
  - Surface captured-insight feedback so memory activity is visible without explicit `current_truth` calls

### Deferred (Not Required for Codex + GPT Desktop Bring-Up)

- [x] **B2 `.mcpb` bundle** (Claude Desktop distribution)
- [ ] **B4 PyPI publish** (post-patent milestone)
  - Preflight complete 2026-03-24: fresh wheel + sdist build succeeded and `twine check` passed cleanly (`dist_preflight/sidequests_brain-0.1.0.tar.gz`, `dist_preflight/sidequests_brain-0.1.0-py3-none-any.whl`)
  - Install smoke: wheel installs and `sidequests --help` runs in clean Python 3.12 venv
  - Caveat: Python 3.14 clean environments fail compiling `kuzu==0.11.3` without `cmake` (use Python 3.12/3.13 for now)
- [ ] **B5 Smithery listing** (depends on distribution path)
  - Preflight note 2026-03-24: `@smithery/cli` v4.7.4 uses `smithery mcp publish` (no standalone `validate` command)
- [x] **B6 Claude Desktop adapter full pass** (not a blocker for current targets)

---

## Market Advantage

### Why SideQuests Wins Against Current Agent Memory

**The compaction problem is real.** Flat markdown files have a hard ceiling — they get too big,
the agent summarizes them (lossy), context is lost forever. This is a structural flaw, not a quirk.
Kùzu + Synaptic Pruning doesn't have this problem. Nodes decay gracefully and archive — they're
never deleted, never summarized into oblivion.

**The "grepping" problem is real.** Linear text search across thousands of files is slow, brittle,
and semantically blind. Graph-Native RAG with HNSW vector search + 1-2 hop traversal is
categorically better. This is a legitimate differentiation.

**The Cocktail Party Effect as continuous background monitoring.** The Brain listens passively via
`notify_turn` without triggering LLM inference on every message. That's a real cost advantage over
agents that use the LLM itself to decide what to remember. Power users in the OpenClaw/AutoGPT
space are explicitly asking for "always-on awareness with intelligent alerting" — this is it.

**Market validation is sound.** The top power users in the agent space are currently managing their
AI's memory using disorganized markdown files and jury-rigging dashboards just to stay sane. The
market is not saturated by a good solution. SideQuests is meaningfully better for structured,
long-term knowledge.

### The Competitive Gap to Close

SideQuests is genuinely better than markdown-file memory. The comparison is favorable.

Where it gets harder: the OpenClaw/AutoGPT crowd might not install a Python daemon + Kùzu + Ollama
to replace their markdown files. The B1 (`sidequests setup` CLI) and B2 (`.mcpb` bundle) backlog
items exist precisely because the install gap could kill adoption even if the technology is superior.

**The market is real. The technology is sound. The install story is the unlock.**

---

## P1 — Install / Setup Story (Blocking Usability)

### B1 · `sidequests setup` CLI
**Problem:** There is no automated path to register SideQuests with target AI clients; users must hand-edit JSON config files, which blocks adoption.

**What it does:** Make the system actually usable without manual JSON editing.

What it does:
- Detects which AI clients are installed (Claude Code, Claude Desktop, Codex, ChatGPT Desktop)
- For Claude Code: runs `claude mcp add sidequests -- python /path/to/adapters/claude_code/adapter.py`
- For Claude Desktop: writes adapter entry to `~/Library/Application Support/Claude/claude_desktop_config.json`
- Writes `~/Library/LaunchAgents/ai.sidequests.brain.plist` (macOS) and loads it via `launchctl`
- Runs smoke test: Ollama ping + Kùzu schema init + `tools/list` round-trip
- Prints a clear pass/fail report

Files to create:
- `sidequests/cli/setup.py` — main setup command
- `sidequests/cli/launchd.py` — plist generation + `launchctl load/unload`
- `sidequests/cli/smoke_test.py` — end-to-end validation
- Entry point in `pyproject.toml`: `sidequests = "sidequests.cli.main:app"`

Notes:
- Use `click` or `typer` for the CLI framework
- Must be idempotent — safe to run multiple times
- Windows: Windows Service via NSSM (deferred, Mac-first)
- Linux: `~/.config/systemd/user/sidequests-brain.service` (deferred)

**Acceptance Criteria (Evaluation):**
- `sidequests setup` runs on a clean machine and leaves all detected clients registered and functional.
- `tools/list` round-trip confirms daemon is reachable and all tools are surfaced after setup.
- Re-running is idempotent — no duplicate entries, no errors on a system already configured.
- Pass/fail report is human-readable and actionable for every step.

**Outcome:** Any developer can go from `pip install sidequests-brain` to first memory capture in under 5 minutes without touching a JSON file.

---

### B2 · `.mcpb` Bundle (One-Click Claude Desktop Install)
**Problem:** Non-technical Claude Desktop users cannot use a pip install + CLI setup flow; they need a native one-click install experience.

**What it does:** Package the entire system as a Desktop Extension so non-technical Claude Desktop users get a true one-click install.

What it does:
- Bundles adapter code + deps + launchd plist into a `.mcpb` (ZIP + manifest.json)
- User opens Claude Desktop > Settings > Extensions > install `.mcpb`
- Claude Desktop runs the bundle's lifecycle hooks → daemon starts, adapter registered

Files to create:
- `mcpb/manifest.json` — bundle manifest (name, description, version, entry point, permissions)
- `mcpb/install.sh` — lifecycle hook: installs launchd plist + loads daemon
- `mcpb/uninstall.sh` — teardown hook
- `Makefile` target: `make mcpb` → runs `mcpb pack` to produce `hippocampy.mcpb`

Dependencies:
- `mcpb` CLI: `npm install -g @anthropic-ai/mcpb`
- Requires B1 (launchd plist generation) as a dependency

Notes:
- The `.mcpb` adapter entry point is `adapters/claude_code/adapter.py` (same as manual install)
- Brain Daemon is started by the lifecycle hook, NOT by the `.mcpb` directly
- Target audience: non-technical Claude Desktop users

**Acceptance Criteria (Evaluation):**
- Double-clicking `hippocampy.mcpb` in Finder and confirming in Claude Desktop installs and registers the adapter with no terminal interaction.
- Brain Daemon starts and passes `sidequests status` health check after install.
- `make mcpb` produces a valid, installable bundle from a clean repo checkout.
- Uninstall removes all components cleanly (no orphaned plist or adapter entry).

**Outcome:** Non-technical Claude Desktop users can install SideQuests in one action with no developer tooling.

---

### B3 · ChatGPT Desktop SSE Endpoint
**Problem:** ChatGPT Desktop uses an SSE-based Connector model that is not compatible with the stdio or Unix-socket transports used by other adapters.

**What it does:** Add an SSE transport to the Brain Daemon's web server so ChatGPT Desktop can connect as a Connector.

What it does:
- FastAPI route: `GET /sse` — MCP-over-SSE transport, bound to `127.0.0.1` only
- ChatGPT Desktop user pastes `http://127.0.0.1:7799/sse` in Settings > Apps > Add Connector
- All 7 tools exposed identically to the stdio adapters

Files to modify:
- `web/server.py` — add `/sse` route implementing MCP SSE transport spec
- `adapters/chatgpt_desktop/adapter.py` — currently a stub, can be removed if SSE route handles it

Notes:
- SSE transport is already part of the MCP spec — use `mcp` Python SDK's SSE support
- Non-technical users still need the daemon running (B1 solves this); they just paste the URL once
- Recommend Claude Desktop (`.mcpb`, one-click) over ChatGPT Desktop for non-technical users

**Acceptance Criteria (Evaluation):**
- `GET /sse` responds at `http://127.0.0.1:7799/sse` and is rejected on any external interface.
- ChatGPT Desktop can add the connector and invoke at least `current_truth` and `notify_turn` successfully.
- All 7+ tools surfaced identically to stdio adapters — no tool registry divergence.
- SSE endpoint falls back gracefully and logs clearly when daemon is not running.

**Outcome:** ChatGPT Desktop users can connect SideQuests as a Connector by pasting one localhost URL.

---

## P2 — Distribution / Discoverability

### B4 · Publish to PyPI
**Problem:** SideQuests is not installable via standard Python tooling, blocking developer adoption and Smithery discoverability.

**What it does:** Make `pip install sidequests-brain` and `uvx sidequests-brain` work.

- Create `pyproject.toml` with proper metadata, entry points, and dependency declarations
- `sidequests setup` as the primary CLI entry point
- Test `uvx sidequests-brain setup` end-to-end

Notes:
- Only publish after provisional patent is filed (IP protection constraint)
- `uvx` is the target developer install story

**Acceptance Criteria (Evaluation):**
- `pip install sidequests-brain` in a clean Python 3.12/3.13 venv succeeds and `sidequests --help` runs.
- `uvx sidequests-brain setup` completes the full setup flow end-to-end.
- `twine check` passes on the published wheel and sdist with no warnings.
- Python 3.14 limitation is documented in the package README with mitigation steps.

**Outcome:** Any developer can install and set up SideQuests Brain with a single pip/uvx command.

---

### B5 · Smithery Listing
**Problem:** SideQuests is invisible in the MCP ecosystem discovery layer where developers browse and install servers.

**What it does:** List SideQuests on Smithery for discoverability.

- Create Smithery-compatible server definition
- Submit to `smithery.ai` registry
- Enables: `npx @smithery/cli install sidequests-brain --client claude`

Notes:
- Only publish after provisional patent is filed
- Requires B4 (PyPI) first

**Acceptance Criteria (Evaluation):**
- `npx @smithery/cli install sidequests-brain --client claude` completes successfully from a clean environment.
- Smithery listing includes correct tool surface, description, and setup instructions.
- `smithery mcp publish` succeeds without validation errors against the server definition.

**Outcome:** SideQuests appears in Smithery search results and is installable via the ecosystem's standard one-liner.

---

## P3 — Adapters (Deferred from M8)

### B6 · Claude Desktop Adapter (Full)
**Problem:** The Claude Desktop adapter path is referenced in architecture docs but only stubbed — Claude Desktop users cannot connect via the standard `claude_desktop_config.json` path.

**What it does:** Implement the full Claude Desktop adapter (effectively a rename of the Claude Code adapter with a different server name).

Files to create:
- `adapters/claude_desktop/adapter.py` — copy of Claude Code adapter with `serverInfo.name = "sidequests-brain-desktop"`

**Acceptance Criteria (Evaluation):**
- Claude Desktop can initialize the adapter and `tools/list` returns the full tool surface.
- No behavioral difference from the Claude Code adapter for `notify_turn`, `current_truth`, and `explore_graph`.
- `sidequests setup --target claude-desktop` registers the adapter in `claude_desktop_config.json`.

**Outcome:** Claude Desktop users have a first-class, dedicated adapter with the same capabilities as Claude Code.

---

### B7 · ChatGPT Desktop Adapter (Stub → Full)
**Problem:** `adapters/chatgpt_desktop/adapter.py` is a stub; it either needs to be fully implemented or explicitly retired in favour of the B3 SSE endpoint.

**What it does:** Resolve the stub — either promote to a full adapter or remove and document that the SSE Connector in B3 replaces this path.

`adapters/chatgpt_desktop/adapter.py` is a stub. If B3 (SSE endpoint) is built, this adapter may be unnecessary — the SSE route in `web/server.py` handles it. Decide after B3.

**Acceptance Criteria (Evaluation):**
- After B3 is built: stub is removed or marked deprecated with a comment pointing to the SSE Connector URL.
- If a full adapter is built instead: `tools/list` round-trip succeeds from ChatGPT Desktop.
- Either path is tested and no dead code remains.

**Outcome:** ChatGPT Desktop integration has exactly one clear, tested connection path with no ambiguous stubs.

---

### B8 · Gemini CLI Adapter — DONE
`adapters/gemini_cli/adapter.py` — completed 2026-03-18. Protocol version negotiation, `resources/list`, and full tool surface implemented. Requires `gemini trust` per project folder.

---

## P4 — Missing Tests

### B9 · `tests/test_adapters.py` — ✅ DONE (2026-03-24)
✅ Done (2026-03-24): `tests/test_adapters.py` now includes comprehensive adapter integration coverage for:
- Tool registration across all implemented adapters
- `handle_mcp_request` routing for all tools
- Offline queue behavior and recovery expectations
- Git context injection (`repo_root`, `git_branch`, `workspace_path`)

---

## P5 — New Capabilities (Post-M8 Research)

### B17 · Semantic Quest Routing ("The Hippocampus")
**Problem:** Git-only MainQuest identification breaks for desktop/non-dev flows and weakens cross-session continuity when git context is missing.

**What it does:** Replace git-only MainQuest identification with a semantic routing mechanism that works for desktop apps and non-dev users. Two-phase System 1/2 routing: git context as one high-confidence signal, content embedding similarity for the rest. Progressive consolidation (tentative → consolidated → locked) with prediction error reconsolidation.

New module: `mcp_engine/hippocampus.py`. New tool: `set_quest`. Schema changes: MainQuest gets `purpose_embedding`, `routing_method`; Session gets `routing_state`, `routing_confidence`. New relationship: `REROUTED_FROM`.

Architecture doc: `B17-B18-architecture.md`. Dependency: None (builds on existing quest infrastructure). Implement before B18.

**Acceptance Criteria (Evaluation):**
- New non-git sessions are routed to a stable MainQuest with explicit `routing_method` + `routing_confidence` recorded on Session.
- Git sessions still route deterministically by repo+branch and are not regressed by semantic routing.
- Repeated semantically similar sessions converge to the same MainQuest with measurable reduction in accidental quest fragmentation.
- Reroute events create auditable `REROUTED_FROM` provenance links.

**Outcome:** Quest identity is robust across dev and non-dev environments, enabling reliable continuity for B18 and cross-session recall.

IP claims: Semantic Quest Routing, Hippocampus Mechanism, Prediction Error Reconsolidation, Multi-Signal Routing Fusion.

---

### B18 · Context Window Awareness ("Working Memory")

**Problem:** `current_truth` re-injects the full relevant knowledge payload every turn, including nodes already in the LLM's context window. This is the biggest controllable source of RAG bloat — the same decisions and constraints get re-sent on every query, wasting tokens and quota.

**What it does:** Track which graph nodes are loaded in each LLM context window via `LOADED` edges. `current_truth` returns only what's missing (smart deduplication), not the full payload every time. Adds a `context_status` MCP tool for session token accounting.

Model each LLM session as a tracked working memory buffer. Track which graph nodes are loaded in each context window via `LOADED` edges. Smart deduplication in `current_truth` (demote, don't exclude already-loaded nodes). Token estimation, bloat detection, session handoff intelligence.

New module: `mcp_engine/working_memory.py`. New tool: `context_status`. Schema changes: Session gets `token_estimate`, `token_limit`, `loaded_node_count`; new `LOADED` relationship (multi-FROM).

Architecture doc: `B17-B18-architecture.md`. Dependency: B17 (shared Session schema changes, `notify_turn` rewire).

**Token efficiency angle (2026-03-27):** This is the real "Token Saver" — not NLP stop-word stripping (which destroys LLM reasoning), but *knowing what the LLM already knows*. The biggest context bloat comes from RAG injection re-sending the same decisions/constraints every turn. If the Brain tracks what's already loaded via `LOADED` edges, `current_truth` can return **only what's missing** instead of the full payload every time. This is where measurable token savings come from.

**Modes of operation:**
- **Default mode:** Demote already-loaded nodes (rank lower, still available if directly relevant)
- **Aggressive mode ("Token Saver"):** Strictly exclude already-loaded nodes from `current_truth` results unless they score above a high similarity threshold (e.g., >0.95). For rate-limit-constrained sessions (OpenClaw power users hitting TPM caps), this can cut RAG injection size significantly.

**Acceptance test (token savings):** Run a 50-turn OpenClaw session twice — once without working memory tracking, once with. Measure total `current_truth` response payload size across all turns. Target: 40%+ reduction in injected tokens by turn 30+ (when most relevant context has already been loaded).

**Design constraint (from graph schema review, 2026-03-22):** Session is a supernode risk — it accumulates `SENT_IN` (every message), `LOADED` (every injected node), `WORKING_ON`, `USED`, `IN_WORKSPACE`, `REROUTED_FROM`. Implementation must include a session edge pruning strategy: archive stale `LOADED` edges aggressively, keep session-centric traversals narrow and task-specific, never use Session as a general-purpose hop for exploratory queries.

**Acceptance Criteria (Evaluation):**
- A 50-turn scripted session with B18 active shows ≥40% reduction in `current_truth` payload size vs baseline by turn 30.
- `context_status` returns `tokens_injected_this_session`, `tokens_saved_by_dedup`, `dedup_hit_rate` with stable schema.
- Session supernode risk is addressed: stale `LOADED` edges are archived aggressively; session traversals remain narrow.
- Unit tests cover default dedup mode and aggressive Token Saver mode.

**Outcome:** RAG injection volume drops measurably as sessions progress, preserving token quota for reasoning rather than re-sending known context.

IP claims: Context Window as Working Memory Model, Smart Deduplication via Load Tracking, Session Handoff Intelligence, Bloat Detection via Token Estimation.

---

### B10 · `explore_graph` Tool (Directed Graph Traversal)

**Problem:** `current_truth` performs vector similarity search, but agents need structural navigation — "what are all Requirements under this SideQuest?" — which blind vector search cannot express reliably. There is no tool today for directed graph traversal from a known node.

**What it does:** Add an `explore_graph` MCP tool for directed traversal from a known node via named relationship types. Inspired by RLM / MIT paper (arXiv:2512.24601). The traversal API is constrained — no arbitrary Cypher, depth capped at 3 hops, read-only.

Inspired by RLM / MIT paper (arXiv:2512.24601). When `current_truth` returns insufficient context,
let the LLM issue a directed traversal query rather than a blind vector search.

What it does:
- New MCP tool: `explore_graph(start_node_id, relationship_type?, direction?, depth?)`
- Returns nodes reachable from a known node via named relationship (e.g., all ActionItems PART_OF a SideQuest)
- Constrained: no arbitrary Cypher, no code execution — fixed traversal API only
- Complements `current_truth` (vector) with structural graph navigation

Files to create/modify:
- `mcp_engine/tools.py` — add `explore_graph` handler
- `adapters/claude_code/adapter.py` — add tool schema
- `adapters/codex/adapter.py` — add tool schema
- `tests/test_explore_graph.py`

Notes:
- Depth capped at 3 hops max — prevent runaway traversal
- Read-only; uses adapter's `read_only=True` Kùzu connection
- Priority: medium — useful but `current_truth` covers most cases

**Acceptance Criteria (Evaluation):**
- `explore_graph(start_node_id, relationship_type="PART_OF", direction="in", depth=2)` returns correct nodes and edges.
- Depth > 3 is rejected with a clear error.
- Read-only constraint: no mutation possible through this tool.
- Tests cover traversal correctness, depth cap, and `REIFIED_AS` interaction.

**Outcome:** Agents can navigate the graph structurally, complementing vector similarity with relationship-based exploration.

---

### B11 · `Lesson` Artifact Node

**Problem:** When a Quest completes, the hardest obstacle overcome and the key insight gained are lost — they exist only in conversation history. Future quests (possibly months later) have no way to surface "what did we learn last time we hit this kind of problem?"

**What it does:** When `complete_quest` is called, synthesize a `Lesson` node capturing the hardest obstacle overcome. Extend `analogical_search` to include lesson embeddings so future quests surface similar lessons.

When a Quest completes, synthesize a Lesson node capturing the hardest obstacle overcome.
Feeds M8 analogical reasoning — future quests surface not just similar decisions but similar lessons learned.

Schema additions:
- `Lesson` node: `lesson_id`, `text_raw`, `embedding FLOAT[384]`, `embedding_model`, `embedding_dim`,
  `obstacle_summary`, `source_quest_id`, `confidence`, `pathway_strength`, `archived`, `created_at`
- Relationship: `(MainQuest)-[PRODUCED_LESSON]->(Lesson)`
- Vector index: `lesson_emb_idx` (HNSW, same pattern as other artifact tables)

Behavior:
- Triggered by `complete_quest` tool call
- Ollama synthesizes 1–2 sentence lesson from quest messages + confirmed artifacts
- Stored `confidence_low=true` initially (inferred, not confirmed)
- `analogical_search` extended to include `lesson_emb_idx` in `CROSS_QUEST_TABLES`
- User can edit/confirm via Memory Control Panel (M7)

Files to create/modify:
- `mcp_engine/schema.py` — add Lesson node + PRODUCED_LESSON relationship + HNSW index
- `mcp_engine/tools.py` — update `complete_quest` handler to trigger lesson synthesis
- `mcp_engine/analogical.py` — add `lesson_emb_idx` to `CROSS_QUEST_TABLES`
- `web/server.py` — surface Lesson nodes in Quests tab and Constraint Ledger export
- `tests/test_lesson.py`

Notes:
- Lesson synthesis is async (same pattern as Gated Consolidation Loop — fire and forget)
- Pairs directly with B10 (`explore_graph` can traverse PRODUCED_LESSON edges)

**Acceptance Criteria (Evaluation):**
- Calling `complete_quest` synthesizes a `Lesson` node linked via `PRODUCED_LESSON` edge.
- `analogical_search` returns lessons from completed quests when query matches.
- Lesson stored as `confidence_low=true` initially; visible in Memory Control Panel for user confirmation.
- Tests cover synthesis, HNSW index query, and cross-quest traversal.

**Outcome:** Lessons from completed work become searchable knowledge assets that surface during future similar problems.

---

### B12 · Memory-Based Anomaly Detection (IP Formalization)

**Problem:** The Brain's Step 4 Contradiction sense already detects when agent behavior conflicts with high-confidence GlobalConstraints, but this security property is not named, documented as a patent claim, or surfaced in the UI. The IP claim may be missed without explicit formalization.

**What it does:** Formalize the existing "Out-of-Band Behavioral Integrity Monitoring" principle as a named IP claim in the Inventor's Notebook. No new code required — the mechanism already exists. Add named claim to notebook, update Cocktail Party sensory table, and coordinate with patent attorney.

The Brain Daemon is architecturally out-of-band — a separate process that cannot be hijacked
by prompt injection in the LLM's context window. The Contradiction sense (Step 4) already
mechanically detects when agent behavior conflicts with high-confidence GlobalConstraints.
This formalizes that property as a named security principle.

Named principle: **Out-of-Band Behavioral Integrity Monitoring**
- Distinct from Cocktail Party Effect (which is about selective attention / memory formation)
- Same mechanism, different application domain: security monitoring vs. memory building
- GlobalConstraints decay at 0.999/day → effectively permanent policy baseline
- Contradiction sense fires when `notify_turn` content conflicts with a high-confidence GlobalConstraint

Scope (important for patent claim precision):
- Conversation-layer only — the Brain sees `notify_turn` content, not syscalls, filesystem, or network
- Detects: prompt injection attempts, goal hijacking, constraint override language in conversation
- Does NOT detect: actual OS-level actions taken by the agent after receiving injected instructions

Action items (no new code required — mechanically already implemented):
1. Write up as named IP claim in Inventor's Notebook canvas
2. Add "Anomaly / Security Sense" to the Cocktail Party Effect sensory table in the notebook
3. Add Section 5.5.D "Out-of-Band Security Monitoring" to notebook
4. Add Claim #7 to Section 5.7 Novelty in notebook
5. Flag to patent attorney as distinct claim from Cocktail Party Effect

Notes:
- No implementation work needed — Step 4 Contradiction sense + GlobalConstraint nodes already do this
- Memory Control Panel (M7) is the natural surface for displaying flagged anomalies
- Future: configurable alert threshold (e.g., only flag contradictions against nodes with pathway_strength > 0.8)

**Acceptance Criteria (Evaluation):**
- "Out-of-Band Behavioral Integrity Monitoring" is documented as a named IP claim in Section 5.5.D of the Inventor's Notebook.
- "Anomaly / Security Sense" row is added to the Cocktail Party Effect sensory table in the notebook.
- Patent attorney has been briefed and this claim is distinct from the Cocktail Party Effect claim.
- No regression to existing Step 4 Contradiction sense behavior.

**Outcome:** A distinct, named, documented IP claim that protects the out-of-band security monitoring property of the Brain architecture.

---

## P0 — Installation Experience (Critical — Blocking Adoption)

### B13 · Guided Installer with LLM Provider Choice — ✅ DONE (2026-03-24)
**What was built:**
- Single entry point: `sidequests install` with a multi-step guided flow.
- LLM Provider Choice: Integrated Ollama auto-install (macOS/Linux) and BYOK (OpenAI/Anthropic/Google) with real-time key validation.
- Linux support: Auto-install Ollama via `apt-get`, `dnf`, or `pacman`.
- Explicit reporting: Final pass/fail report with actionable fix hints for every failed step.
- LLM Connectivity check: Explicit verification of local/cloud API connectivity before proceeding.
- Automated client registration: Detects and configures Claude Code, Claude Desktop, Codex, and Gemini CLI.
- Idempotency: Safe to re-run; skips already completed or valid steps.
- Unified smoke test: Validates the entire stack (daemon, tools, schema, SSE) at the end of the run.

**Files modified:**
- `sidequests/cli/install.py`
- `tests/test_install.py`

---

### B19 · `sidequests uninstall` Command — ✅ DONE (2026-03-27)
**What was built:**
- New CLI command: `sidequests uninstall [--yes] [--keep-data|--delete-data] [--remove-ollama-model] [--ollama-model MODEL]`
- Confirmation prompt by default; `--yes` skips it for scripting.
- Step 1: Stops Brain Daemon — unloads/removes launchd plist (macOS) or disables systemd service (Linux).
- Step 2: Deregisters all AI client adapters:
  - Claude Code: `claude mcp remove` + cleans `~/.claude.json` + removes `hook_user_turn.py` from `~/.claude/settings.json`
  - Claude Desktop: removes entry from `claude_desktop_config.json`
  - Codex / Codex Desktop: removes `[mcp_servers.sidequests]` block from TOML configs
  - Gemini CLI: removes entry from `settings.json`
  - OpenClaw: runs `openclaw plugins remove sidequests-brain`, reverses `plugins.allow` and sandbox tool patches, restarts gateway
- Step 3: Optional data deletion — `--delete-data` removes `~/.sidequests/` entirely; default keeps data.
- Step 4: Optional Ollama model removal — `--remove-ollama-model` removes the specified model.
- Idempotent: safe to run when nothing is registered; every step gracefully skips if not present.
- Final pass/fail report printed after all steps.

**Files:** `sidequests/cli/uninstall.py`, `sidequests/cli/main.py`, `tests/test_uninstall.py`
**Validation:** `python3 -m pytest tests/test_uninstall.py tests/test_install.py tests/test_setup.py -q`
→ 88 passed, 1 warning (spaCy/Pydantic on Python 3.14)

---

## P6 — Consumer Readiness

### B14 · Proactive Insight Surfacing
The Brain currently ingests silently — no feedback loop tells the user what was captured. This is the
biggest consumer-readiness gap. Normal users need to feel the system is alive and working for them.

**What it does:**
- After the Loop processes a message and stores artifacts, surface a brief summary back to the user
- Options (not mutually exclusive, evaluate during implementation):
  - **System prompt injection:** Add a count/summary to the always-on fragment (e.g., `[SideQuest | 3 new insights captured]`)
  - **MCP resource:** Expose a `insights_since_last_check` resource the LLM can reference naturally
  - **Menu bar badge:** If native Mac wrapper is built (see parking lot), show a badge count
- Summary should be minimal — "Captured: 2 decisions, 1 constraint" not a full dump
- Must not add latency to the LLM session (fire-and-forget still applies)

**Why it matters:**
- Clay's invisible enrichment works because users see the *result* (better answers). SideQuest's
  enrichment is truly invisible — users have no signal the Brain is working until they ask `current_truth`
- Consumer trust requires visible value. "I'm listening and learning" needs proof.

**Files to modify:**
- `mcp_engine/tools.py` — new resource or tool for insight summary
- `adapters/claude_code/adapter.py` — surface insight count in system prompt or as a resource
- `mcp_engine/loop/step7_pathway.py` — emit summary event after pathway update

**Dependencies:** None — can be built independently of other backlog items.

**Problem:** Brain ingestion is completely silent — users have no signal the system is working, which destroys consumer trust.

**Acceptance Criteria (Evaluation):**
- After a Loop run that stores at least one artifact, the always-on system prompt fragment includes a non-zero insight count on the next turn.
- Surfacing adds zero latency to the LLM turn — event emission is fire-and-forget.
- Count resets to 0 after the user explicitly checks (via `current_truth` or an `insights_since_last_check` resource), not on every turn.
- Unit test mocks a step7 pathway update and verifies the summary event is emitted.

**Outcome:** Users see evidence the Brain is alive and capturing knowledge without having to ask.

---

### B15 · Deep-Link Handoff (Chat → Memory Control Panel)
When the LLM references graph data (via `current_truth` or after Brain captures something significant),
include a clickable localhost link to the relevant Memory Control Panel view.

**What it does:**
- `current_truth` responses include a `panel_url` field with a deep link to the relevant graph view
- LLM naturally includes the link in its response: `[View decision graph](http://127.0.0.1:7799/quests/abc123/decisions)`
- Memory Control Panel (M7) routes handle deep links to specific quests, nodes, or graph views

**Why it matters:**
- This is the Clay "Open in Clay" pattern — seamless transition from conversational to visual UI
- The Memory Control Panel already exists (M7). This just wires chat responses to it.
- Non-technical users get a "click to see more" experience instead of needing to know the URL

**Files to modify:**
- `mcp_engine/tools.py` — add `panel_url` to `current_truth` response schema
- `web/server.py` — ensure deep-link routes exist for quest/node/graph views
- Adapter system prompt — instruct LLM to surface links when relevant

**Problem:** Users cannot navigate from a chat answer backed by graph memory to the relevant Memory Control Panel view — the connection between conversation and visual memory is invisible.

**Acceptance Criteria (Evaluation):**
- `current_truth` response schema includes a `panel_url` field pointing to the relevant quest/node view.
- LLM trained by system prompt to surface the link naturally when citing recalled memory.
- Deep-link routes exist in `web/server.py` for at least quest, decision, and constraint views.
- Broken or stale node IDs produce a graceful 404 with helpful message, not a server error.

**Outcome:** Users can click from an LLM answer directly into the graph UI to explore supporting memory context.

**Dependencies:** M7 (Memory Control Panel) must have routable views.

---

### B16 · Task-Based Model Routing — ✅ DONE (2026-03-23)
**Commit:** `41556c6`
Allow different Loop steps to use different LLM providers/models, optimizing for cost and latency
per cognitive task. Inspired by OpenClaw power-user workflows (Matthew Berman "trifecta" pattern).

**What it does:**
- Extend `sidequests.toml` to support per-step LLM overrides:
  ```toml
  [llm]
  provider = "ollama"              # default for all steps
  model = "llama3.1:8b"

  [llm.step6_arbitration]          # override for contradiction arbitration
  provider = "anthropic"
  model = "claude-sonnet-4-6"

  [llm.quest_purpose]              # override for purpose synthesis
  provider = "openai"
  model = "gpt-4.1-mini"
  ```
- Steps without an override use the default `[llm]` block
- `LLMClient` resolves the correct provider/model per caller context

**Why it matters:**
- Step 2 System 2 disambiguation and Step 3b relation extraction are tractable for small local models
  (type context narrows the search space). No reason to burn cloud tokens on them.
- Step 6 contradiction arbitration is the hardest reasoning task — benefits most from frontier models.
- Power users (developers, researchers) will want this control. Consumer users never see it — defaults
  just work.

**Files to modify:**
- `sidequests.toml` — add per-step override schema
- `mcp_engine/llm/provider.py` — resolve per-step model from config
- `mcp_engine/loop/step2_gist.py`, `step3b_relations.py`, `step6_arbitration.py` — pass step identifier
  to `LLMClient`
- `tests/test_llm_routing.py` — verify correct model resolution per step

**Dependencies:** None — `LLMClient` already supports multiple providers. This is config + routing logic.

---

## P7 — OpenClaw Integration (Discovered 2026-03-21)

Issues found during live OpenClaw standalone install + plugin integration session.

### B20 · OpenClaw Extension: Plugin ID Mismatch
**Problem:** Manifest and package name divergence causes a persistent gateway warning that degrades developer confidence and may block future plugin operations.

**What it does:** Align `package.json` name and `openclaw.plugin.json` id so they match — both should be `sidequests-brain`.

The `openclaw.plugin.json` uses `id: "sidequests-brain"` but the npm `package.json` uses a different name (`openclaw-brain`). This causes a persistent config warning on every gateway startup:
```
plugin id mismatch (manifest uses "sidequests-brain", entry hints "openclaw-brain")
```

**Fix:** Align `package.json` `name` field with `openclaw.plugin.json` `id` field. Both should be `sidequests-brain`.

**Acceptance Criteria (Evaluation):**
- Gateway starts with no `plugin id mismatch` warning after the fix.
- `openclaw plugins list` shows `sidequests-brain` as the canonical plugin ID.
- Regression test confirms manifest ID and package name match in CI.

**Outcome:** Clean gateway startup with no spurious warnings; plugin identity is unambiguous.

---

### B21 · OpenClaw System Prompt + Tool Integration (LLM Workflow)

**Problem:** The SideQuests Brain plugin is registered in OpenClaw (`memory_recall`, `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops` all show as available), but the LLM is not being instructed to use these tools. Additionally, conversations are not being passively ingested into the graph — the LLM has no mechanism to forward turns to the Brain Daemon.

**What it does:** Inject a two-layer system prompt into every OpenClaw LLM session to activate passive ingestion and instruct the LLM to use Brain tools. Implement the OpenClaw adapter that captures user + assistant turns, wires all 5 tool schemas, and handles offline queue + replay.

**What This Solves:**
- Currently: Conversations flow through OpenClaw; SideQuests tools exist but are never called
- After B21: LLM automatically ingests turns + is instructed to call `memory_recall` for architectural questions + system prompt guides tool usage
- Expected outcome: SideQuests becomes the active memory layer for OpenClaw, not just an available-but-unused plugin

**Architecture (Context for Implementation):**

OpenClaw's system prompt injection works via a plugin hook system (similar to Claude Code). The SideQuests plugin must:

1. **Inject a system prompt fragment** into every OpenClaw LLM session (similar to Claude Code adapter's always-on fragment)
2. **Implement ingestion** via a new OpenClaw-specific adapter that captures user + assistant turns and forwards them to the Brain Daemon
3. **Define tool schemas** so OpenClaw knows which tools are available and when to call them (already partially done — tools are registered but LLM doesn't invoke them)
4. **Wire tool execution** so calls to `memory_recall`, `memory_store`, etc. route through the SideQuests plugin to the Brain Daemon and return results

**System Prompt Model (Two Layers):**

Layer 1 — Always-On Context (~50 tokens, every session):
```
[SideQuests Brain: Memory active | 3 artifacts captured last 3 turns]
Before answering questions about past decisions, architecture, or constraints:
→ Call memory_recall to check the graph
For stored facts: use memory_store
For analogical reasoning: use memory_search_analogies
Check memory_status to see what's been captured
```

Layer 2 — Onboarding Skill (first session only per OpenClaw agent):
```
SideQuests Brain is your persistent knowledge graph. One automatic duty:
- notify_turn: After EVERY response, forward your output to SideQuests (session_id + role="assistant" + full text)
  This is how the Brain learns what you've done. Response is instant, never blocks.

Two tools you control:
- memory_recall(query): Retrieve relevant decisions/constraints before answering architecture questions
- memory_search_analogies(query): Find similar problems from other projects/sessions
- memory_store(key, value): Save custom facts (e.g., "Database: PostgreSQL 16, on RDS")
Check memory_status for how much is captured.
```

**Files to Create/Modify:**

1. **New Plugin Adapter (adapter):**
   - `adapters/openclaw/adapter.py` — Main OpenClaw adapter
     - Implement `OpenClawAdapter` class (similar to Claude Code adapter)
     - Hook into OpenClaw's plugin lifecycle (startup/shutdown)
     - Implement system prompt injection via OpenClaw's config extension point
     - Implement `notify_turn` handler (forward both user + assistant turns)
     - Implement tool execution routing for all 5 tools
     - Include offline queue + replay on daemon recovery
     - Git context injection (if running in a dev environment, auto-detect MainQuest from git branch)

2. **OpenClaw Configuration Extension:**
   - `adapters/openclaw/openclaw.plugin.json` — Update manifest
     - Add `systemPrompt` contribution point (if OpenClaw supports it) or fallback to environment variable
     - Add version info
   - `adapters/openclaw/plugin-config.ts` — TypeScript config (if OpenClaw uses TypeScript plugins)
     - Define system prompt templates (Layer 1 + Layer 2)
     - Define onboarding logic (track `Session.onboarded` via persistent plugin state)

3. **Tool Schemas (in adapter):**
   - Define all 5 tool schemas matching the Brain Daemon's expectations:
     - `memory_recall(query: string, scope?: "branch" | "global")` — call `current_truth`
     - `memory_store(key: string, value: string)` — call `upsert_text_artifact`
     - `memory_search_analogies(query: string, scope?: "cross_quest")` — call `analogical_search`
     - `memory_status()` — call `context_status` (summary of captured artifacts)
     - `memory_open_loops()` — call `get_open_loops`

4. **Ingestion Flow:**
   - `adapters/openclaw/ingestion.py` — Session + turn capture
     - Detect OpenClaw session ID (from plugin context)
     - On each user turn: call `notify_turn(role="user", content=..., session_id=...)`
     - On each assistant turn: call `notify_turn(role="assistant", content=..., session_id=...)`
     - Handle offline queue if Brain Daemon is down
     - Parse git context if available (fallback to generic "openclaw-agent" MainQuest if no git)

5. **Tests:**
   - `tests/test_openclaw_adapter.py`
     - Tool registration and availability
     - System prompt injection (verify Layer 1 + Layer 2 are injected correctly)
     - Ingestion flow (user turn → `notify_turn` → daemon receives it)
     - Tool execution (call `memory_recall` → verify response maps to `current_truth` result)
     - Offline queue behavior (daemon down → queue → daemon up → replay)
     - Session lifecycle (new session → onboarding prompt on first turn, Layer 1 only on subsequent sessions)

**Technical Constraints:**

- **OpenClaw Plugin API:** Check OpenClaw's plugin documentation for:
  - System prompt injection API (how to inject text into the LLM's context)
  - Tool definition format (how to register tools for the LLM to call)
  - Session context API (how to get session ID, detect new sessions)
  - Event hooks (turn start/end, session start/end)
  - Persistent state storage (for `onboarded` flag)
- **No TCP/HTTP listening:** Use the existing Unix socket to the Brain Daemon (same as Claude Code + Codex)
- **Session ID handling:** OpenClaw sessions must be distinct from SideQuests sessions. Map OpenClaw session ID → SideQuests Session (create if doesn't exist)
- **Offline resilience:** Same pattern as other adapters — queue failed ingestion to `~/.sidequests/openclaw_queue.jsonl`, replay when daemon recovers

**Acceptance Criteria (Evaluation):**

1. ✅ **Tools are registered and visible:**
   - `@openclaw tools` lists 5 SideQuests tools (already true, but verify)
   
2. ✅ **System prompt injected:**
   - Launch OpenClaw TUI
   - In a session, ask "What are my recent decisions?" (generic question)
   - Verify the LLM calls `memory_recall` automatically
   
3. ✅ **Ingestion working:**
   - Make a user query in OpenClaw
   - Check Brain Daemon logs: `notify_turn` should be called with role="user" + content
   - Get an assistant response
   - Check Brain Daemon logs: `notify_turn` should be called with role="assistant" + content
   - Verify graph has new Message nodes in the Session
   
4. ✅ **Tool execution working:**
   - Store a fact: `@openclaw memory_store("key", "project uses Kùzu")`
   - Verify the plugin captures and forwards to Brain Daemon
   - Retrieve it: Ask "What database do we use?" → LLM calls `memory_recall` → result includes stored fact
   
5. ✅ **Cross-session recall:**
   - End OpenClaw session
   - Start a new OpenClaw session
   - Ask "What database do we use?"
   - Verify `memory_recall` returns the fact stored in the previous session (via graph, not session state)
   
6. ✅ **Offline resilience:**
   - Start OpenClaw with daemon running
   - Kill the daemon
   - Make a query that triggers ingestion
   - Verify offline queue is written to `~/.sidequests/openclaw_queue.jsonl`
   - Restart daemon
   - Verify queue is replayed and cleared
   
7. ✅ **Onboarding only on first encounter:**
   - First session with this OpenClaw agent → see full Layer 2 onboarding prompt
   - Second session → see only Layer 1 fragment, not onboarding

**Implementation Phases:**

Phase 1 (MVP): System prompt + ingestion + `memory_recall` tool
- Minimal: just "listen to turns" + "surface memory before answering"
- Validator: `@openclaw memory_recall("recent decisions")` returns results

Phase 2: Full tool surface + offline queue
- Add `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops`
- Add offline queue + replay

Phase 3: Onboarding skip logic
- Track `onboarded` in persistent plugin state
- Skip Layer 2 on subsequent sessions

**Dependencies:**
- None (all infrastructure exists)
- Requires: Brain Daemon running (already handled by B13 installer)
- Requires: OpenClaw API documentation (developer must read OpenClaw plugin spec)

**Related Backlog Items:**
- B13 (Installer) — must handle OpenClaw daemon setup
- B19 (Uninstall) — must clean up OpenClaw plugin registration (already implemented)
- B20 (Plugin ID mismatch) — must be fixed before B21 starts

**Priority:** HIGH — This is the unlock for OpenClaw power users. Without this, the plugin is "inert" (registered but unused). With this, OpenClaw becomes a fully memory-augmented agent.

**Effort Estimate:** 40–60 hours (depends on OpenClaw plugin API maturity; if API is well-documented and stable, closer to 40h; if undocumented, 60h+)

**Files:** `extensions/hippocampy/package.json`, `extensions/hippocampy/openclaw.plugin.json`

**Outcome:** OpenClaw becomes a fully memory-augmented agent — conversations are passively ingested, past decisions are surfaced before answering, and the Brain is the active knowledge layer rather than a registered-but-unused plugin.

---

### B61 · OpenClaw Extension: Tools Not Surfaced to Agent Without Manual Config
**Problem:** Plugin tools are registered at the gateway but blocked by the sandbox allowlist by default — users must manually edit `openclaw.json` to surface them, which kills first-run experience.

**What it does:** Patch the installer to automatically add SideQuests memory tools to the sandbox allowlist during OpenClaw setup.

`api.registerTool()` registers tools at the gateway level, but the sandbox tool policy uses an allowlist. Plugin-registered tools are blocked by default — the user must manually add them to `tools.sandbox.tools.allow` in `openclaw.json`.

**Fix:** The installer (`sidequests setup` / B1 / B13) must detect OpenClaw and automatically add the memory tools to the sandbox allowlist:
```json
"tools": {
  "sandbox": {
    "tools": {
      "allow": ["memory_recall", "memory_store", "memory_search_analogies", "memory_status", "memory_open_loops"]
    }
  }
}
```

**Files:** `sidequests/cli/setup.py` (or equivalent installer), `extensions/hippocampy/README.md` (document the manual step until installer handles it)

**Acceptance Criteria (Evaluation):**
- After `sidequests setup --target openclaw`, `openclaw sandbox explain` lists all SideQuests memory tools as allowed.
- Agent sessions invoke memory tools without any manual config edits.
- Installer is idempotent — re-running does not duplicate allowlist entries.

**Outcome:** First-run experience requires zero manual JSON editing to get tools surfaced to agents.

---

### B22 · OpenClaw Extension: `plugins.allow` Warning
**Problem:** Every OpenClaw startup emits a warning about an empty `plugins.allow` list, causing noise and eroding trust in the install state.

**What it does:** Patch the installer to explicitly add `sidequests-brain` to `plugins.allow` during setup.

OpenClaw warns on every startup that `plugins.allow` is empty and non-bundled plugins auto-load. The installer should set `plugins.allow` to explicitly trust the sidequests-brain plugin:
```json
"plugins": {
  "allow": ["sidequests-brain"]
}
```

**Fix:** Add to installer config step. Low priority — cosmetic warning, no functional impact.

**Files:** `sidequests/cli/setup.py`

**Acceptance Criteria (Evaluation):**
- After `sidequests setup --target openclaw`, gateway starts with no `plugins.allow` warning.
- Setting is idempotent — re-running setup does not duplicate the entry.
- Uninstall removes the entry cleanly.

**Outcome:** Clean gateway startup with explicit plugin trust declared.

---

### B23 · ~~OpenClaw Extension: SSE Connection Per Tool Call is Expensive~~ RESOLVED
~~The `BrainClient.callTool()` method opens a new SSE connection per call.~~

**Resolved 2026-03-21:** Upgraded to Streamable HTTP transport (MCP 2025-03-26). `POST /mcp` now returns results directly in the response body. Single HTTP round-trip per tool call. Commit: `feat: upgrade MCP transport from SSE to Streamable HTTP (2025-03-26)`

---

### B24 · OpenClaw Extension: Missing `memory_search`, `memory_get` Core Tool Aliases — ✅ DONE (2026-03-26)
The OpenClaw `coding` tools profile expects `memory_search` and `memory_get` (core memory tools from the default `memory-core` plugin). When sidequests-brain replaces `memory-core`, these were missing:
```
tools.profile (coding) allowlist contains unknown entries (apply_patch, memory_search, memory_get)
```

**Fix applied:** Registered `memory_search` and `memory_get` in the OpenClaw extension as direct aliases of `memory_recall` / `current_truth`, sharing the same parameter schema and execution path.

**Files:** `extensions/hippocampy/src/index.ts`, `tests/test_extension_aliases.py`
**Validation:** `python3 -m pytest tests/test_extension_aliases.py tests/test_hippocampus.py -q`

---

### B25 · OpenClaw Installer: `sidequests setup --target openclaw` — ✅ DONE (2026-03-26)
**What was built:**
- Added `openclaw` as a detected/installable target in `sidequests setup` and installer auto-detection.
- `sidequests setup --target openclaw` now:
  1. Detects the `openclaw` CLI in PATH
  2. Installs the local SideQuests extension via `openclaw plugins install <repo>/extensions/hippocampy`
  3. Patches `~/.openclaw/openclaw.json` to set `plugins.allow = ["sidequests-brain"]`
  4. Patches sandbox policy to include `tools.sandbox.tools.alsoAllow = ["group:plugins"]`
  5. Adds the explicit SideQuests memory tools to `tools.sandbox.tools.allow`
  6. Restarts the gateway via `openclaw gateway restart`
  7. Verifies tool surfacing via `openclaw sandbox explain`
- Installer path (`sidequests install`) now also auto-registers OpenClaw when detected.
- Added regression coverage for config patching, idempotency, OpenClaw registration orchestration, and detection.

**Files:** `sidequests/cli/setup.py`, `sidequests/cli/install.py`, `sidequests/cli/detect.py`, `sidequests/cli/main.py`, `tests/test_setup.py`, `tests/test_install.py`
**Validation:** `python3 -m pytest tests/test_setup.py tests/test_install.py -q`

---

### B26 · Document: OpenClaw Standalone Install Guide — ✅ DONE (2026-03-26)
Comprehensive install doc for OpenClaw standalone (not NemoClaw) with SideQuests Brain integration.

**What was added:**
- New repo doc: `docs/openclaw-install.md`
- Covers OpenClaw install via npm, Docker/OrbStack sandbox setup, Brain daemon startup, plugin install, gateway restart, verification, Discord notes, and troubleshooting
- Updated from the original standalone draft to reflect the current SideQuests plugin wiring:
  - plugin install path: `openclaw plugins install ./extensions/hippocampy`
  - explicit plugin trust via `plugins.allow`
  - critical tool surfacing fix via `tools.sandbox.tools.alsoAllow = ["group:plugins"]`
  - current 7-tool memory surface (`memory_recall`, `memory_search`, `memory_get`, `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops`)
  - Streamable HTTP daemon transport (`POST /mcp`)

**Reference:** `~/Desktop/B-openclaw-standalone-install.md` (used as source draft, then updated to match live repo/plugin state)

**Files:** `docs/openclaw-install.md`

---

### B41 · OpenClaw Integration: Ensure Brain Daemon Auto-Starts with Gateway Sessions — ✅ DONE (2026-03-27)
**Commit:** `3afd5837`

When OpenClaw gateway starts, the SideQuests memory plugin currently only pings the Brain Daemon and logs a warning if `http://127.0.0.1:7799` is unreachable. This is correct for health reporting, but it creates a poor first-run experience because memory tools silently fail until the daemon is started separately.

**Preferred fix:** Treat the Brain Daemon as a managed background service, not something spawned by the plugin. On macOS this should use the existing `launchd` path (`RunAtLoad` + `KeepAlive`) so the daemon is already running before OpenClaw starts, survives gateway restarts, and auto-recovers from crashes.

**Optional fallback:** Add an opt-in plugin behavior in `extensions/hippocampy/src/index.ts` `start()` that attempts to launch the daemon when `brain.ping()` fails. This should be disabled by default and only used as a convenience fallback, since plugin-managed process launch is more fragile (paths, env, permissions, duplicate daemon risk).

**Acceptance criteria:**
- `sidequests install` or `sidequests setup --target openclaw` configures the Brain Daemon as a persistent user service where supported
- After reboot/login, OpenClaw gateway sees the Brain Daemon as reachable without manual startup
- If the daemon crashes, service management restarts it independently of OpenClaw
- Plugin startup warning is updated to distinguish between "service not installed" and "daemon temporarily unreachable"
- If plugin auto-launch fallback is added, it is explicitly opt-in and avoids spawning duplicate daemon instances

**What was done:**
- `sidequests install` already configures launchd (`RunAtLoad + KeepAlive`) via `sidequests/cli/launchd.py` — launchd path was already correct.
- Added `isDaemonServiceInstalled()` to `extensions/hippocampy/src/index.ts` — checks plist presence (macOS) or systemd unit presence (Linux) at plugin startup.
- Plugin `start()` now emits one of three states:
  1. **Connected** — daemon reachable, silent success log
  2. **Service not installed** — first-run diagnostic, points to `sidequests install`
  3. **Service registered but unreachable** — transient failure, will auto-recover, points to `sidequests status`
- Added opt-in `autoLaunch` config (disabled by default) — spawns daemon if service not installed and config is set.
- Added 19-test suite `tests/test_b41_plugin_startup.py` covering all new paths.
- Updated `docs/openclaw-install.md` troubleshooting section 2 with clear distinction.
- Fixed orphaned `tests/test_mission_control_discord_adapter.py` (skipif guard, same pattern as other MC tests).
- Full suite: **677 passed, 11 skipped, 0 failures**.

**Files:** `extensions/hippocampy/src/index.ts`, `tests/test_b41_plugin_startup.py`, `docs/openclaw-install.md`, `tests/test_mission_control_discord_adapter.py`

---

### B28 · CRITICAL: `api.registerTool()` Does Not Surface Tools to Agent Sessions — ✅ FIXED (2026-03-22)
**GitHub Issue:** [#1](https://github.com/djs54/sidequests-brain/issues/1)

**Fix applied:**
1. Fixed `package.json` name from `@sidequests/openclaw-brain` → `@sidequests/sidequests-brain` to match `openclaw.plugin.json` manifest ID
2. Added `alsoAllow: ["group:plugins"]` to `tools` section in `~/.openclaw/openclaw.json`
3. Reinstalled plugin with `openclaw plugins install --force`

**Verified (2026-03-22 smoke test):** All 5 tools (`memory_recall`, `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops`) return valid results from agent sessions. Passive ingestion continues working.

**Files:** `extensions/hippocampy/package.json`, `extensions/hippocampy/src/index.ts`
**Priority:** P0 — ✅ resolved
**Depends on:** None

---

### B27 · Extension: Passive Ingestion Event API Validation
**Problem:** Passive ingestion reliability is unproven because hook names/payloads were assumed, not validated against the live OpenClaw event API.

**What it does:** Validate and lock the extension's ingestion hook contract.

The extension uses `api.on("llm_input")`, `api.on("llm_output")`, and `api.on("before_agent_start")` — these event names were assumed from the OpenClaw plugin docs. Need to verify:
1. Are these the correct event names in OpenClaw 2026.3.13?
2. Is the event payload shape correct (`event.prompt`, `event.assistantTexts`)?
3. Are hooks actually firing? (Gateway logs show "Connected" but no ingestion confirmation)

**Fix:** Test each event by adding temporary logging. Adapt event names/payloads to match actual API.

**Acceptance Criteria (Evaluation):**
- For one user+assistant turn in OpenClaw, both events fire and produce `notify_turn` calls with non-empty content.
- A compatibility table is documented in-code or docs for event name and payload fields used.
- If an expected hook is unavailable, fallback behavior is explicit and tested.
- Regression test fails when event payload shape changes silently.

**Outcome:** Ingestion becomes contract-tested instead of assumption-based, unblocking B29 with high confidence.

**Files:** `extensions/hippocampy/src/index.ts`

---

## P8 — Cross-Session Awareness (Discovered 2026-03-21)

The core value proposition of SideQuests Brain as a memory system for OpenClaw agents: multiple sessions of the same agent share a persistent knowledge graph, so they all know what the others have been doing.

### B29 · TEST CASE: Cross-Session Context Awareness
**Status:** FAILING (2026-03-21)  
**Priority:** P0 — this is the entire reason the Brain exists

**Problem:** New sessions can answer with stale/local memory instead of graph recall, breaking the core promise of shared persistent memory.

**What it does:** Define and enforce an end-to-end cross-session recall test that must pass before claiming OpenClaw memory continuity.

**Scenario:**
1. Agent session A (TUI) does significant work — tests memory system, finds bugs, upgrades MCP transport, delegates to Gemini, commits code
2. Agent session B (Discord) is asked "what are you working on?"
3. Session B should recall session A's work via the Brain's knowledge graph

**Expected:** Session B queries `current_truth` with the user's question and gets back recent decisions, actions, and context from session A's work — even though session B has no direct context of what session A did.

**Actual (2026-03-21):** Session B gave a stale answer based on yesterday's markdown memory files. It had no awareness of session A's Streamable HTTP upgrade, Gemini delegation, or test results. The Brain was passively ingesting both sessions, but session B never queried it.

**Root causes:**
1. Passive ingestion hooks (`llm_input`/`llm_output`) may not be firing for all sessions (needs B27 validation)
2. Even if ingestion works, the `before_agent_start` auto-recall hook may not inject enough context about cross-session work
3. The agent's system prompt doesn't instruct it to check the Brain when asked about recent work — it defaults to reading markdown memory files instead
4. `notify_turn` returns empty `quest_id` for non-git sessions, so cross-session work may not be linked to the same quest

**Acceptance Criteria (Evaluation):**
- [ ] Session A stores a decision via conversation (e.g., "We decided to use Streamable HTTP")
- [ ] Session B, started fresh with no shared context window, queries "What transport protocol did we choose?"
- [ ] Session B's `current_truth` returns the Streamable HTTP decision from session A
- [ ] Session B can give an informed answer without reading markdown files

**Depends on:** B28 (tool binding), B27 (hook validation), working quest routing for non-git sessions

**Outcome:** Cross-session recall becomes a hard gate, not a best-effort behavior.

**Files:** `extensions/hippocampy/src/index.ts` (hooks), `mcp_engine/tools.py` (current_truth), agent system prompt / SOUL.md

---

### B30 · Agent System Prompt: "Check the Brain First" — ✅ DONE (2026-03-22)
**What was done:**
- Added "🧠 SideQuests Brain — Active Memory System" section to AGENTS.md
- Documents when to use `memory_recall`, `memory_store`, `memory_status`, `memory_open_loops`
- Establishes Brain as primary source of truth, markdown files as backup
- Graceful fallback if Brain tools unavailable

**Files:** `~/.openclaw/workspace/AGENTS.md`

**Depends on:** B29 (cross-session test passing), B28 (tool binding working)

---

### B31 · Improvement: Recall Ranking Needs Recency Factor
**Problem:** Current ranking over-weights historical strength and can bury newly confirmed, highly relevant decisions.

**What it does:** Add a recency term to `current_truth` ranking so recently reinforced knowledge competes fairly with older high-strength nodes.

When recalling memories, old high-pathway-strength nodes dominate over recently stored, highly relevant ones. A "Redis caching decision" stored 5 minutes ago loses to a "JWT" concept from 2 days ago.

**Fix:** Add recency decay to the ranking formula in `current_truth`:
```python
from datetime import datetime, timezone
days_old = (datetime.now(timezone.utc) - node_created_at).total_seconds() / 86400
recency = 1.0 / (1 + days_old)
rank = (ps * conf * 0.4) + (similarity * 0.4) + (recency * 0.2)
```

**Acceptance Criteria (Evaluation):**
- A controlled test query where a recent node and older node have similar similarity now ranks the recent node first.
- Ranking remains stable for clearly dominant high-similarity results (no pathological recency overfit).
- Unit tests pin scoring behavior and weight math for reproducibility.

**Outcome:** Recall ranking better reflects "current truth now," not just historical prominence.

**Files:** `mcp_engine/tools.py` (`current_truth` function)

---

### B32 · Bug: Zero Edges in Knowledge Graph — ✅ FIXED (2026-03-22)
**Root causes fixed:**
1. Relations stored before concept nodes existed → deferred to after step 4-7 loop
2. `_store_relation` silently dropped noun-chunk endpoints → added `_ensure_concept_exists()`
3. `explore_graph` used `type(r)` which doesn't exist in Kuzu 0.11.3 → iterate specific rel types
4. `Session.content_embedding` missing from migrations → added

**Commit:** `51bb01d`

---

### B33 · Bug: Duplicate Concept Nodes — ✅ FIXED (2026-03-22)
**Fix:** `_store_concept` now checks for exact `text_raw` match (case-insensitive) before CREATE. Dedup hit returns existing concept_id + bumps last_accessed_at + upgrades pathway_strength/confidence_low if new observation is more confident. Falls through on DB error so creation still proceeds safely.
**Commit:** `3b8ae3d`
**Tests:** 496 passed, 4 skipped

---

### B34 · Bug: Junk Entities Still Leaking
**Problem:** Step 1 NER still admits low-value noise (markdown fragments, code tokens, generic terms), polluting graph quality and downstream retrieval.

**What it does:** Harden `_is_junk_entity()` filters for markdown artifacts, syntactic fragments, and code-shaped tokens while preserving legitimate short entities.

Despite earlier fixes (ISSUE-019, ISSUE-026), junk still enters the graph:
- `"### Open Loops"` — markdown heading
- `"to persist summaries"` — prepositional fragment
- `"last_loop_summary"` — code variable name
- `"constraints"` — generic word
- `"Project Setup:**"` — markdown bold markers

**Fix:** Extend `_is_junk_entity()` in `step1_ner.py`:
- Filter text starting with `#` (markdown)
- Filter fragments starting with prepositions
- Filter snake_case/camelCase strings
- Filter text containing `**` (markdown bold)
- Minimum 3 chars for single-word entities

**Acceptance Criteria (Evaluation):**
- All listed leak examples are rejected by tests.
- New filters do not regress known valid entities used in existing Step 1 fixtures.
- Junk rejection rate improves on sampled real transcripts without reducing high-confidence artifact yield.

**Outcome:** Cleaner concept graph with less noise propagation into Steps 2-7 and better retrieval precision.

**Files:** `mcp_engine/loop/step1_ner.py`

---

### B35 · Bug: `set_quest` Fails with Kuzu Schema Error — ✅ FIXED (2026-03-27)
`set_quest` tool was returning: `Binder exception: Cannot find property git_repo_root for q.`

**Root cause:** The migration guard `"property" in str(e).lower()` in `init_schema()` was too broad. Kuzu's "Cannot find property X" Binder exception (thrown at query time when a column is absent) also contains the word "property", causing ALTER TABLE failures on existing DBs to be silently swallowed — leaving `git_repo_root` and other B17 columns absent from the live `MainQuest` and `Session` tables.

**Fix:** Replaced exception-based detection with a pre-check using `CALL table_info(table)` to enumerate existing columns before attempting `ALTER TABLE`. If the column is already present → skip. If table_info itself raises → fall through to attempt ALTER (safe default, with duplicate-column guard still in place as backstop).

**Commit:** `bf28a65a` — `fix: B35 migration uses table_info pre-check to prevent silent column-missing failure`
**Tests:** 7 new tests in `TestMigrationColumnCheck` in `tests/test_schema.py`. Full suite: 658 passed, 6 skipped.
**Files:** `mcp_engine/schema.py`, `tests/test_schema.py`

---

### B36 · Audit All Adapters/Plugins for Streamable HTTP Transport
**Priority:** Medium  
**Status:** Not started

**Problem:** Transport behavior diverged across adapters and surfaces, increasing protocol drift risk and integration bugs.

**What it does:** Inventory, validate, and normalize transport paths with Streamable HTTP as primary where supported and explicit fallbacks where required.

The Brain Daemon's web endpoint was upgraded to Streamable HTTP (MCP 2025-03-26) with SSE as fallback. Need to audit all integration points to ensure they use the modern transport where possible.

**Current transport inventory:**

| Integration | Transport | Status |
|-------------|-----------|--------|
| OpenClaw extension | Streamable HTTP (POST /mcp → direct JSON) | ✅ Upgraded 2026-03-21 |
| Claude Code adapter | stdio → Unix socket IPC to daemon | ⚪ N/A (stdio, not HTTP) |
| Claude Desktop adapter | stdio → Unix socket IPC to daemon | ⚪ N/A (stdio, not HTTP) |
| Codex adapter | stdio → Unix socket IPC to daemon | ⚪ N/A (stdio, not HTTP) |
| Gemini CLI adapter | stdio → Unix socket IPC to daemon | ⚪ N/A (stdio, not HTTP) |
| ChatGPT Desktop | SSE (GET /sse) | 🟡 Should upgrade to Streamable HTTP |
| Brain Daemon IPC (`_dispatch`) | Unix socket, no `tools/call` wrapper | 🟡 Uses raw method names, not MCP `tools/call` |
| Plugin `.mcp.json` | SSE endpoint URL | 🟡 Should offer Streamable HTTP option |

**Action items:**
1. **ChatGPT Desktop:** Update `adapters/chatgpt_desktop/adapter.py` docs and test whether ChatGPT Desktop supports Streamable HTTP natively. If it does, update the instructions to use `POST /mcp` instead of `GET /sse`. Keep SSE fallback either way.
2. **Brain Daemon IPC dispatch:** The Unix socket `_dispatch` in `brain_daemon.py` uses raw method names (e.g., `method: "notify_turn"`) while the web `_dispatch_mcp` uses MCP protocol (`method: "tools/call"`, `params.name: "notify_turn"`). This divergence could cause bugs. Consider unifying both dispatch paths to use `tools/call` wrapping.
3. **Plugin `.mcp.json`:** Currently points to SSE endpoint. Add Streamable HTTP endpoint option for clients that support it.
4. **Smithery listing (B5):** When publishing, ensure the Smithery server definition advertises Streamable HTTP as the primary transport.

**Acceptance Criteria (Evaluation):**
- Each integration is marked as `validated` with tested transport and fallback behavior.
- No adapter/client path depends on deprecated SSE-only assumptions where Streamable HTTP is supported.
- IPC dispatch contract differences are either unified or explicitly documented with tests.

**Outcome:** One clear transport contract across ecosystem surfaces, reducing protocol mismatch incidents.

**Files:** `adapters/chatgpt_desktop/adapter.py`, `brain_daemon.py`, `.mcp.json`, `plugin/.mcp.json`, `smithery.yaml`

---

## B37: Token Budget & Graceful Rate Limiting
**Priority:** High | **Status:** Partially Complete (Phase 1+2 done, Phase 3 → B38)
**Problem:** Opus 4.6 rate limits are tight. Heartbeats + work sessions + conversation can blow past TPM limits, causing 429 errors with no graceful fallback. When limits hit, SideClaw goes completely dark — no context preservation, no handoff.
**Brainstorm areas:**
- **Sonnet/Opus task routing:** Which tasks genuinely need Opus (architecture, review, complex debugging) vs Sonnet (routine checks, heartbeats, simple edits, monitoring)? Can cron jobs specify model per task?
- **Token budget awareness:** Can we monitor remaining rate limit headroom and proactively downshift to Sonnet before hitting the wall?
- **Graceful degradation:** When approaching limits, flush critical context to SideQuests Brain / memory files so the next session (on any model) can pick up immediately
- **SideQuests as continuity layer:** If Brain has full context, hitting a rate limit becomes a non-event — spin up on Sonnet or wait for Opus cooldown, recall from Brain, continue seamlessly
- **Rate limit headers:** Anthropic returns `retry-after` and usage headers — can OpenClaw read these and auto-switch models?
- **Session cost tracking:** Use session_status to track token burn rate and alert before limits
**Goal:** Never go dark again. Rate limits should trigger a smooth handoff, not a crash.

---

## B38: Graceful Rate Limit Handoff via SideQuests Brain
**Priority:** High | **Status:** Backlog | **Depends on:** B28 (tool binding)
**Problem:** When Opus hits a rate limit mid-session, context is lost. Even with Sonnet fallback (B37), active working context that was never written to files disappears.
**Solution:** Use Brain as the continuity layer. When a session ends (gracefully or due to limit), flush working context to Brain + write a RESUME_POINT to memory files. Any new session can recall from Brain and continue seamlessly.
**Requirements:**
- B28 (tool binding) must work — Brain needs to be callable from within sessions
- Session startup flow: check Brain for RESUME_POINT before starting fresh
- Session end flow: flush working context, write handoff note
- Cron session prompts updated to include resume-from-Brain logic
**Goal:** Rate limits become non-events. Spin up on Sonnet, recall from Brain, keep going.

---

## B39: Mission Control — Thinking Tab (Brain Integration) — ✅ DONE (2026-03-22)
**Commit:** `2a702f5`
**What was built:**
- `web/server.py`: New `/api/thinking` endpoint — decisions (top 10 by strength), concepts (top 25), constraints (top 10), open_loops_count, stats summary
- `mission-control/server.py`: `brain_integrated = True`, new `_brain_thinking()` helper, real data wired to /thinking route
- `mission-control/templates/thinking.html`: Full live UI — stats bar (4 counters), decisions panel with strength %, constraints panel, concept tag cloud colored by strength tier (blue > 70%, grey > 40%, dim < 40%)
- "Coming Soon / Blocked on B28" placeholder replaced with real data display
- Brain offline state still shows proper error message

---

## B40: B28 Deep Dive — Explicit Tool Call Registration — ✅ RESOLVED (2026-03-22)
**Priority:** P0 | **Status:** Done — resolved as part of B28 fix

Root cause was the package name mismatch (`@sidequests/openclaw-brain` vs manifest ID `sidequests-brain`) combined with missing `group:plugins` allowlist entry. Once both were fixed and plugin reinstalled, all 5 tools surfaced correctly. The `registerTool()` pattern was correct all along — the plugin was simply failing to load due to the ID mismatch.

---

## P9 — Graph Shape Discipline (From Schema Review, 2026-03-22)

Source: `docs/graph-schema-review.md` — external graph architecture review.

### B42 · Document Concept→Artifact Retrieval Contract
**Problem:** Concept and artifact layers are both active, but retrieval semantics are under-specified outside core architecture notes.

**What it does:** Publish a formal retrieval contract defining layer precedence, return-shape rules, and traversal behavior across `Concept`, `REIFIED_AS`, and artifact nodes.

The `Concept → REIFIED_AS → Artifact` dual-layer design is intentional, but the retrieval contract is not documented outside CLAUDE.md. When does `current_truth` return Concepts vs artifact nodes vs both? How should callers interpret results when the same idea exists at both layers?

**What it does:**
- Document which layer `current_truth` searches (currently: artifact tables via `UNION ALL` across per-table HNSW indexes)
- Define the canonical rule: when should something stay a `Concept` vs when it should be promoted and primarily retrieved as an artifact?
- Clarify whether `explore_graph` should traverse through `REIFIED_AS` or start from artifact nodes directly
- Add this as a design doc section in `B17-B18-architecture.md` or a standalone `docs/retrieval-contract.md`

**Why it matters:** Without a documented contract, future retrieval work risks creating parallel truth layers where concept-layer and artifact-layer results compete in confusing ways.

**Acceptance Criteria (Evaluation):**
- Contract explicitly defines when `current_truth` returns artifact-only, concept-only, or mixed results.
- Contract includes at least 3 concrete examples mapping query intent to expected result shape.
- `explore_graph` interaction with `REIFIED_AS` is specified and test/doc references are linked.

**Outcome:** Retrieval behavior becomes predictable for adapters, tests, and future ranking work.

**Files:** `docs/retrieval-contract.md` or section in `B17-B18-architecture.md`
**Priority:** P3 — design documentation, no code change

---

### B43 · Extend `ESTABLISHED_IN` Provenance to Requirement and ActionItem — ✅ DONE (2026-03-22)

**What was done:**
- Discovered `ESTABLISHED_IN` edges were defined in schema but never written anywhere in code — fixed for all 4 artifact types
- `mcp_engine/schema.py`: Expanded `ESTABLISHED_IN` rel table FROM clause to include `Requirement` and `ActionItem`; added rel migration that DROP+RECREATEs the table on first startup (safe: zero edges existed)
- `mcp_engine/loop/orchestrator.py`: Added `session_id` parameter to `run_loop()` and `_reify_concept()`; `_reify_concept` now writes `(artifact)-[:ESTABLISHED_IN]->(Session)` after creating the artifact node — covers Decision, Constraint, Requirement, ActionItem
- `brain_daemon.py`: Pass `session_id` to `run_loop()` call in loop worker
- `mcp_engine/tools.py`: Added `ESTABLISHED_IN` to `_TRAVERSABLE_RELS` in `explore_graph`

**Bonus discovery:** `ESTABLISHED_IN` was never written before this commit — all 4 artifact types now have full session provenance from day one of B43.

**Files:** `mcp_engine/schema.py`, `mcp_engine/loop/orchestrator.py`, `brain_daemon.py`, `mcp_engine/tools.py`
**Priority:** P3 — ✅ resolved

---

## P10 — Efficiency & Token Management

### B44 · Token Efficiency as a Side Effect (Not a Feature)
**Problem:** Users hit token rate limits (TPM/RPM) on frontier models (Opus, GPT-4o) due to massive context payloads. The bloat comes from chat history + system prompt + RAG injection — not user prompts.

**What it does:** Documents the strategy for token efficiency — what to build (B18 smart dedup, B16 model routing, B37/B38 rate limit handoff), what explicitly NOT to build (NLP stop-word stripping, context compaction), and how to measure/market the results. No code; this is the architectural decision record for the token efficiency approach.

**What NOT to do:** NLP stop-word stripping ("Caveman Speak"). Stripping connective tissue destroys attention mechanisms LLMs rely on for reasoning. Saves ~5% tokens, costs ~20% reasoning accuracy. Never build this.

**What NOT to own:** Context history compaction (summarizing old messages). That's the host client's job (OpenClaw, Claude Code, etc.). SideQuests is a memory system, not a context window proxy. Don't reach into another system's history.

**What SideQuests DOES own — token savings that come for free from good memory:**
1. **Smart Deduplication (B18):** `current_truth` returns only what's missing from the context window, not the full knowledge dump every turn. This is where the real savings are — RAG injection is the biggest controllable source of bloat.
2. **Task-Based Model Routing (B16):** Route low-reasoning tasks to cheap/local models, preserve frontier quotas for hard problems.
3. **Graceful Rate Limit Handoff (B37/B38):** When limits hit, flush context to Brain and resume on a different model without losing state.

**Marketing note:** Don't brand "Token Saver Mode" as a standalone feature — it invites unfavorable benchmarking. Instead, token efficiency is a bullet point under B18 working memory. "SideQuests reduces redundant context injection by 40%+" is more defensible than "saves tokens."

**Depends on:** B18 (working memory tracking), B16 (model routing), B37/B38 (rate limit handling)
**Measurement:** See B45 (Token Efficiency Measurement & Visualization)

**Acceptance Criteria (Evaluation):**
- This card's strategy decisions are documented and referenced in B18, B45 implementation plans.
- NLP stop-word stripping is explicitly rejected in code review / implementation guidance.
- Token efficiency marketing language is aligned with B45 empirical claims.

**Outcome:** The team has a shared, documented strategy for token efficiency that prevents re-litigating these decisions in future sessions.

---

### B45 · Token Efficiency Measurement & Visualization
**Problem:** We claim B18 (working memory) reduces redundant context injection, B16 (model routing) preserves frontier quotas, and B37/B38 (rate limit handoff) prevents data loss. But we have no way to prove it with numbers or show users the value.

**What it does:** Implement measurement and visualization in three layers.

**What it does — three layers:**

**Layer 1: Before/After Benchmark (Dev-facing, build first)**
- Instrument `current_truth` to log: query, result count, total token estimate of response payload, how many results were excluded by dedup
- Run a scripted 50-turn session against a known corpus twice:
  - **Baseline:** `current_truth` with no `LOADED` tracking (returns everything relevant every time)
  - **With B18:** `current_truth` with working memory dedup active
- Output: CSV with per-turn token counts, cumulative totals, dedup hit rate
- Target metric: 40%+ reduction in cumulative injected tokens by turn 30

**Layer 2: Live Session Metrics (User-facing, `context_status` tool)**
- Extend the existing `context_status` MCP tool to return:
  - `tokens_injected_this_session` — total tokens sent via `current_truth` responses
  - `tokens_saved_by_dedup` — tokens that would have been sent without working memory tracking
  - `dedup_hit_rate` — % of candidate results excluded because already loaded
  - `model_routing_savings` — count of tasks routed to local model instead of frontier (B16)
- LLM can surface this naturally: "This session, the Brain saved ~4,200 tokens by not re-sending context you already have."

**Layer 3: Mission Control Visualization (Dashboard, depends on M7)**
- New panel in Memory Control Panel: "Token Efficiency"
- **Per-session view:** Line chart showing tokens injected per turn (baseline projection vs actual with dedup)
- **Cumulative view:** Running total of tokens saved across all sessions
- **Model routing view:** Pie chart of tasks routed to frontier vs local models (B16)
- **Rate limit events:** Timeline showing when rate limits were hit and how handoff preserved context (B37/B38)

**Files to create/modify:**
- `mcp_engine/tools.py` — instrument `current_truth` with token counting + dedup tracking
- `mcp_engine/working_memory.py` — expose savings metrics
- `tests/test_token_efficiency.py` — scripted benchmark harness (Layer 1)
- `web/server.py` + `web/static/` — Token Efficiency panel (Layer 3)
- `mission-control/` — integrate efficiency metrics into Mission Control dashboard

**Depends on:** B18 (working memory tracking must exist to measure), B16 (model routing for routing metrics), B37/B38 (rate limit events for timeline)
**Priority:** P5 — measurement. Build Layer 1 alongside B18 implementation. Layers 2-3 after B18 is proven.

**Acceptance Criteria (Evaluation):**
- Layer 1 emits reproducible CSV/JSON metrics with baseline vs dedup runs and a computed savings delta.
- `context_status` exposes live savings counters with stable schema and tests.
- Dashboard renders per-session and cumulative efficiency views from real telemetry (not mocked-only paths).

**Outcome:** Token-efficiency claims are empirically defensible and visible to both developers and end users.

---

## P11 — Benchmark Program (Memory Wall Validation)

Purpose: Produce defensible, reproducible evidence that SideQuests improves long-horizon agent behavior versus baseline agent memory. This section converts benchmark ideas into executable cards with strict local setup, criteria, and outcomes.

### B46 · Benchmark Source Verification + Dataset Pinning
**Priority:** P0 | **Status:** Not started

**Problem:** Public benchmark names and claims evolve quickly. Before building adapters, we need a reproducible source-of-truth lockfile for benchmark versions, task counts, license terms, and local run commands.

**What it does:** Produce three output artifacts — a canonical links/citations doc (`benchmark_sources.md`), a pinned lockfile with commit hashes and checksums (`benchmark_lock.json`), and a per-benchmark local setup matrix (`setup_matrix.md`). Any benchmark with unstable artifacts is labeled `experimental` with a fallback plan.

**Scope:** Verify and pin the benchmark artifacts for:
- SWE-CI
- LoCoBench
- MemoryArena (if public release is incomplete, mark as experimental)
- AMA-Bench
- Autonomous Research Simulation harness (local custom benchmark)

**Deliverables:**
- `benchmarks/benchmark_sources.md` — canonical links, paper/repo citations, release dates, and license terms
- `benchmarks/benchmark_lock.json` — pinned commit hashes/tags, dataset checksums, expected task counts
- `benchmarks/setup_matrix.md` — exact local requirements per benchmark (Python version, Docker, disk estimate, env vars)

**Acceptance Criteria (Evaluation):**
1. Each benchmark has a verified upstream source and pinned version/commit.
2. Each dataset artifact has checksum + local cache path documented.
3. Any benchmark with unstable or unavailable artifacts is explicitly labeled `experimental` with fallback plan.
4. Re-running verification on a fresh machine reproduces the same lockfile.

**Outcome:** Benchmark work is reproducible and auditable; no ambiguous “latest repo” dependencies.

---

### B47 · Local Benchmark Runner Infrastructure (Unified Harness)
**Priority:** P0 | **Status:** Not started | **Depends on:** B46

**Problem:** Each benchmark has different invocation semantics; without a unifying runner we cannot execute A/B tests consistently.

**What it does:**
- Build a local benchmark runner with a normalized interface:
  - `baseline` mode (no SideQuests memory retrieval)
  - `augmented` mode (SideQuests memory retrieval + passive ingestion)
- Standardize outputs to JSONL + CSV for cross-benchmark comparison.

**Files to create/modify:**
- `benchmarks/runner.py` — unified CLI entrypoint
- `benchmarks/config.py` — benchmark config schema + validation
- `benchmarks/results_schema.json` — standard result format
- `benchmarks/README.md` — local execution instructions

**Local Setup Requirements (must be automated):**
- Python venv + pinned deps
- Docker availability check for benchmarks requiring containerized execution
- Local cache directories for datasets
- Provider/env validation (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, local Ollama, etc.)

**Acceptance Criteria (Evaluation):**
1. One command can run any configured benchmark in `baseline` or `augmented` mode.
2. Runner emits normalized metrics files under `benchmarks/results/<run_id>/`.
3. Failed preflight checks stop execution with actionable errors.
4. Dry-run mode validates setup without spending model tokens.

**Outcome:** Consistent local benchmark execution pipeline across all benchmark families.

---

### B48 · SideQuests A/B Evaluation Contract (Protocol-Correct)
**Priority:** P0 | **Status:** Not started | **Depends on:** B47

**Problem:** Prior harness drafts used a non-existent daemon protocol (`action: retrieve`). SideQuests uses MCP/JSON-RPC semantics and existing tool surface.

**What it does:** Define and enforce the exact A/B evaluation contract that future benchmark cards must follow — correct tool names, MCP request shapes, session management, and diff semantics between baseline and augmented runs.

**Contract to enforce:**
- Ingestion:
  - `notify_turn(role="user"|"assistant", content, session_id)`
- Retrieval (before decision or architecture responses):
  - `current_truth(query, session_id, scope, limit)`
- Optional metrics/context APIs where available:
  - `context_status`, `diff_since`, `get_open_loops`

**A/B Modes:**
- `baseline`: do not call `current_truth`; keep all else identical
- `augmented`: call `current_truth` according to retrieval policy and record injected payload size

**Files to create/modify:**
- `benchmarks/adapters/sidequests_adapter.py` — protocol-correct adapter
- `benchmarks/policies/retrieval_policy.py` — when to call retrieval
- `tests/test_benchmark_adapter_contract.py`

**Acceptance Criteria (Evaluation):**
1. Adapter never uses ad-hoc socket message shapes; only supported MCP/JSON-RPC tool calls.
2. Every augmented run logs retrieval invocations and payload token estimates.
3. Baseline and augmented runs are identical except for memory calls.
4. Contract tests fail if a non-existent tool/method name is used.

**Outcome:** Benchmark comparisons isolate SideQuests memory effects without protocol drift.

---

### B49 · SWE-CI Evaluation Card (Maintainability Under Evolution)
**Priority:** P1 | **Status:** Not started | **Depends on:** B46, B47, B48

**Problem:** We lack evidence that SideQuests improves agent-proposed code quality under forward evolution — the most common real-world failure mode.

**What it does:** Run controlled SWE-CI A/B evaluation to measure whether memory-augmented agents produce code changes that remain valid as target repositories evolve.

**Benchmark intent:** Validate whether code changes proposed by the agent remain valid under future repository evolution (not just immediate test pass).

**Local Requirements:**
- Docker installed/running
- SWE-CI dataset + pinned commit pairs
- Python environment for harness orchestration

**Evaluation Criteria to run:**
- Per task, execute base→target evolution workflow and run target test suite
- Track:
  - `pass_rate_target_tests`
  - `future_breakage_count`
  - `repair_iterations`
  - `technical_debt_events` (lint/test regressions introduced by agent)

**Question templates (used in runs):**
- “Implement change required by target commit while preserving existing behavior.”
- “Update affected modules and ensure target tests pass without breaking prior constraints.”

**Acceptance Criteria (Evaluation):**
1. End-to-end SWE-CI subset run completes locally with reproducible results.
2. Baseline vs augmented comparison exported with identical task set and seeds.
3. Report includes confidence intervals and per-repo breakdown.

**Outcome:** Evidence for SideQuests impact on software evolution stability.

---

### B50 · LoCoBench Evaluation Card (Long-Context Degradation)
**Priority:** P1 | **Status:** Not started | **Depends on:** B46, B47, B48

**Problem:** We lack quantified evidence that graph-backed retrieval mitigates the long-context quality collapse that affects all frontier models above 50K tokens.

**What it does:** Run LoCoBench A/B evaluation across short/medium/long context bands to measure whether SideQuests memory retrieval reduces success-rate degradation at scale.

**Benchmark intent:** Measure quality degradation as context length scales; validate whether graph-backed retrieval mitigates long-context collapse.

**Local Requirements:**
- LoCoBench harness + pinned scenario pack
- Config for local model endpoints/API keys
- Sufficient disk/compute for large-context scenarios

**Evaluation Criteria to run:**
- Scenario families:
  - architectural understanding
  - cross-file refactor consistency
  - multi-session continuity
- Context bands:
  - short (e.g., 10K–50K)
  - medium (50K–200K)
  - long (200K+)
- Track:
  - `task_success_rate`
  - `architectural_coherence_proxy`
  - `memory_retention_proxy`
  - `token_cost_per_success`

**Question templates (used in runs):**
- “Given this codebase history, apply the requested refactor across all affected files consistently.”
- “Resume the session and enforce previously established constraints while implementing the new change.”

**Acceptance Criteria (Evaluation):**
1. LoCoBench runs complete in all three context bands.
2. Augmented mode shows equal or better success at medium/long bands.
3. Token-to-success efficiency is reported for baseline and augmented.

**Outcome:** Quantified long-context resilience attributable to memory retrieval policy.

---

### B51 · AMA-Bench + MemoryArena Card (Causality and Interdependent State)
**Priority:** P1 | **Status:** Not started | **Depends on:** B46, B47, B48

**Problem:** Vector-similarity retrieval with no causal awareness cannot correctly answer “what must be true first” questions — we need evidence graph memory changes this.

**What it does:** Run AMA-Bench (and MemoryArena if available) A/B evaluation to measure whether graph-backed memory reduces causal precondition violations and state-dependency errors.

**Benchmark intent:** Test whether SideQuests preserves causal state and dependency chains across long-horizon trajectories containing machine-generated artifacts (JSON, tables, code).

**Local Requirements:**
- AMA-Bench dataset (real + synthetic trajectories) pinned
- MemoryArena artifacts if available; otherwise run as `experimental` with custom scenario pack

**Evaluation Criteria to run:**
- Causal precondition correctness:
  - agent answers must respect prior required steps/constraints
- Interdependent task completion:
  - downstream tasks must use upstream outcomes correctly
- Track:
  - `causal_qa_accuracy`
  - `state_dependency_violation_rate`
  - `cross-session_recall_accuracy`

**Question templates (used in runs):**
- “What must be true before executing step N?”
- “Which earlier decision invalidates this current action?”
- “Given prior trajectory artifacts, choose the valid next action and justify dependency links.”

**Acceptance Criteria (Evaluation):**
1. Causal QA is executed against pinned trajectory sets.
2. Reports include explicit dependency-violation examples.
3. Augmented mode reduces dependency violations versus baseline.

**Outcome:** Direct evidence that graph memory helps causal reasoning beyond similarity retrieval.

---

### B52 · Autonomous Research Simulation Harness (Hypothesis Regression Rate)
**Priority:** P0 | **Status:** Not started | **Depends on:** B47, B48

**Problem:** Need a practical overnight stress test aligned with SideQuests mission: avoid repeating failed hypotheses when filesystem state is reset between iterations.

**Critical safety correction:** Do NOT run branch churn in the main repo. Use an ephemeral git worktree or temporary clone per benchmark run to avoid destructive side effects.

**What it does:**
- Build local simulation loop for repeated propose→execute→observe cycles
- Run A/B:
  - baseline (no memory retrieval)
  - augmented (retrieve prior failures/constraints via `current_truth`)
- Core metric:
  - `hypothesis_regression_rate` (repeating previously failed experiments)

**Files to create/modify:**
- `benchmarks/autoresearch/harness.py`
- `benchmarks/autoresearch/mock_target/train.py` (deterministic toy target)
- `benchmarks/autoresearch/README.md`
- `tests/test_autoresearch_harness.py`

**Evaluation Criteria to run:**
- For each iteration:
  - proposed hypothesis
  - execution success/failure
  - whether hypothesis repeats known failure
  - retrieval payload size and key constraints returned
- Aggregate:
  - `hypothesis_regression_rate`
  - `successes_per_100_iterations`
  - `mean_iterations_to_stable_success`

**Acceptance Criteria (Evaluation):**
1. Harness runs fully local with deterministic seed.
2. Safe isolation confirmed (no edits outside ephemeral benchmark workspace).
3. Baseline reproduces repeated-failure behavior in mock scenario.
4. Augmented mode materially lowers `hypothesis_regression_rate`.
5. Run report includes side-by-side plots and raw JSONL logs.

**Outcome:** Practical, product-aligned proof that SideQuests reduces repeated failure loops in autonomous workflows.

---

### B53 · Benchmark Report Pack + Go/No-Go Thresholds
**Priority:** P1 | **Status:** Not started | **Depends on:** B49, B50, B51, B52

**Problem:** Raw benchmark outputs are not enough for roadmap decisions or external claims.

**What it does:**
- Produce a single report pack with:
  - methods
  - datasets/versions
  - A/B metrics
  - failure analysis
  - claim-safe summary language
- Define explicit thresholds for product claims and launch readiness.

**Files to create/modify:**
- `benchmarks/reports/summary_template.md`
- `benchmarks/reports/generate_report.py`
- `docs/benchmark-results.md`

**Go/No-Go Thresholds (initial):**
- `hypothesis_regression_rate` reduction >= 30% on B52
- token-to-success efficiency improvement >= 20% on long-context tasks (B50)
- causal dependency violation reduction >= 20% (B51)
- no statistically significant regression on correctness in any benchmark family

**Acceptance Criteria (Evaluation):**
1. Report is reproducible from raw run artifacts.
2. Every claim traces to a metric + run ID.
3. Result narrative clearly separates proven gains vs experimental signals.

**Outcome:** Decision-grade evidence for roadmap prioritization, demos, and investor-safe messaging.

---

## P12 — ARC-AGI-3 Track (Interactive + Offline Submission Readiness)

Purpose: Define a contest-safe and scientifically valid path to evaluate SideQuests on ARC-style interactive reasoning tasks, then package a compliant offline submission path if rules allow.

### B54 · ARC-AGI-3 Rules + Interface Verification (Blocker)
**Priority:** P0 | **Status:** Not started

**Problem:** Prior notes assume specific contest constraints and environment APIs. These must be verified before implementation to avoid building against incorrect requirements.

**What it does:** Produce a verified, dated rules snapshot and interface contract as a hard prerequisite for all ARC implementation cards.

**What to verify (authoritative sources only):**
1. Prize track rules and eligibility conditions (open-source requirements, runtime budget, internet constraints, licensing)
2. Official submission format and scoring protocol
3. Official runtime environment constraints (CPU/GPU, memory, wall-clock limits)
4. Official ARC interactive environment API (Gym-compatible or custom adapter)

**Deliverables:**
- `benchmarks/arc3/rules_snapshot.md` — dated summary with source links
- `benchmarks/arc3/rules_checklist.md` — machine-checkable compliance list
- `benchmarks/arc3/interface_contract.md` — actual observation/action schema and episode lifecycle

**Acceptance Criteria (Evaluation):**
1. Every rule claim is linked to a primary source.
2. API assumptions are replaced by a verified interface contract.
3. Compliance checklist can be run before each benchmark/submission run.

**Outcome:** ARC work proceeds on verified constraints, not assumptions.

---

### B55 · ARC Interactive Adapter (Protocol-Correct SideQuests Bridge)
**Priority:** P0 | **Status:** Not started | **Depends on:** B54, B48

**Problem:** Example code used placeholder env/tool protocol. Need a production adapter that bridges ARC interactive episodes to SideQuests tools correctly.

**What it does:**
- Build `ARC3Adapter` that:
  - normalizes environment observations/actions to a stable schema
  - sends passive ingestion via `notify_turn`
  - retrieves memory via `current_truth` using `session_id`
  - logs step-level telemetry for reproducibility

**Files to create/modify:**
- `benchmarks/arc3/adapter.py`
- `benchmarks/arc3/schema.py`
- `tests/test_arc3_adapter_contract.py`

**Acceptance Criteria (Evaluation):**
1. Adapter uses only supported SideQuests MCP tool calls.
2. One episode replay yields deterministic action/observation logs.
3. Contract tests fail on unsupported method names or malformed payloads.

**Outcome:** Reliable, protocol-safe ARC↔SideQuests integration layer.

---

### B56 · Spatial State-to-Text/State Serializer for Causal Memory
**Priority:** P1 | **Status:** Not started | **Depends on:** B55

**Problem:** ARC environments are spatial and stateful; raw arrays are hard for memory extraction and causal audit.

**What it does:**
- Implement serializer that converts raw grid/state transitions into structured and text forms:
  - machine form (JSON delta)
  - human/LLM form (compact causal narration)
- Preserve exact reversible provenance to avoid hallucinated deltas.

**Files to create/modify:**
- `benchmarks/arc3/state_serializer.py`
- `benchmarks/arc3/prompts/state_to_text.md`
- `tests/test_arc3_state_serializer.py`

**Evaluation Criteria:**
- Delta fidelity: reconstructed after-state from before-state + delta must match ground truth
- Compression: serialized representation remains token-efficient
- Causal clarity: includes action, changed objects, and reward/error signals

**Acceptance Criteria (Evaluation):**
1. Serializer round-trip accuracy >= 99% on fixture set.
2. Every step log includes action, delta, reward, done flag.
3. Token footprint per step is reported and bounded by configured threshold.

**Outcome:** ARC transitions become memory-usable causal artifacts for SideQuests.

---

### B57 · ARC A/B Harness (Baseline vs SideQuests-Augmented)
**Priority:** P0 | **Status:** Not started | **Depends on:** B55, B56

**Problem:** Need controlled A/B evaluation to test whether SideQuests reduces repeated mistakes and improves solve rate in interactive tasks.

**What it does:**
- Build local ARC harness with two modes:
  - `baseline`: no retrieval from SideQuests
  - `augmented`: retrieval policy enabled + passive ingestion enabled
- Run fixed puzzle suite with fixed seeds.

**Files to create/modify:**
- `benchmarks/arc3/harness.py`
- `benchmarks/arc3/tasks_manifest.json`
- `tests/test_arc3_harness.py`

**Metrics:**
- `puzzles_solved_rate`
- `median_steps_to_solve`
- `repeated_invalid_action_rate`
- `causal_regression_rate` (repeating previously failed strategy under same puzzle state class)
- `token_cost_per_solved_puzzle`

**Acceptance Criteria (Evaluation):**
1. Fixed-seed A/B run is reproducible.
2. Baseline and augmented differ only by memory retrieval policy.
3. Results export includes per-puzzle traces and aggregate metrics.

**Outcome:** Defensible evidence of SideQuests impact on interactive causal reasoning.

---

### B58 · Offline Model Strategy Card (Allowed Models + Resource Budget)
**Priority:** P0 | **Status:** Not started | **Depends on:** B54

**Problem:** Model selection for ARC submissions must satisfy contest rules and runtime limits. “Best model” claims must be budget-aware and reproducible.

**What it does:**
- Define approved local model matrix (open weights only if required by rules)
- Benchmark candidate models under runtime/memory budget
- Select primary + fallback models for submission runs

**Files to create/modify:**
- `benchmarks/arc3/model_matrix.md`
- `benchmarks/arc3/model_budget.yaml`
- `benchmarks/arc3/model_eval.py`

**Evaluation Criteria:**
- solve quality on calibration task set
- latency per step
- memory/VRAM footprint
- stability under long episodes

**Acceptance Criteria (Evaluation):**
1. At least 3 candidate local models are profiled under the same workload.
2. Selected primary model meets verified runtime constraints from B54.
3. Fallback model documented with trigger conditions.

**Outcome:** Contest-compliant local model plan with explicit compute tradeoffs.

---

### B59 · Offline Packaging + Reproducible Execution Bundle
**Priority:** P1 | **Status:** Not started | **Depends on:** B54, B58

**Problem:** Offline execution requires deterministic packaging of code, wheels, models, and config. Ad-hoc notebook installs are brittle.

**What it does:**
- Build a reproducible offline bundle process (dataset/archive) for:
  - SideQuests runtime
  - required Python wheels
  - model artifacts
  - benchmark/submission scripts

**Files to create/modify:**
- `benchmarks/arc3/package_offline_assets.py`
- `benchmarks/arc3/offline_manifest.json`
- `benchmarks/arc3/verify_offline_bundle.py`
- `docs/arc3-offline-setup.md`

**Acceptance Criteria (Evaluation):**
1. Bundle verification passes with network disabled.
2. Environment setup succeeds using only bundled artifacts.
3. Checksums validate for all required assets.

**Outcome:** Portable offline artifact set suitable for constrained evaluation environments.

---

### B60 · Submission Notebook/Runner Assembly + Final Compliance Gate
**Priority:** P1 | **Status:** Not started | **Depends on:** B57, B58, B59

**Problem:** Final submission flow must be assembled with compliance checks and deterministic outputs.

**What it does:**
- Assemble final runner/notebook with:
  - offline install/bootstrap cell/stage
  - SideQuests daemon/service startup check
  - model load and episode loop
  - required output artifact generation
- Add pre-submit compliance gate driven by B54 checklist.

**Files to create/modify:**
- `benchmarks/arc3/submission.ipynb` (or `submission.py` if allowed)
- `benchmarks/arc3/pre_submit_check.py`
- `benchmarks/arc3/README.md`

**Acceptance Criteria (Evaluation):**
1. End-to-end run completes within verified runtime budget.
2. No network dependency is exercised during run.
3. Output format matches official evaluator expectations.
4. Pre-submit check blocks non-compliant configuration.

**Outcome:** Submission-ready, rules-compliant ARC track pipeline.

---

### ARC Success Core Priority Stack (Existing Non-ARC Cards)

This lane identifies which existing core cards should be prioritized to maximize ARC lane success and public demo quality. These are not new features; they are dependency multipliers for ARC reliability.

#### Tier 0 (Do Immediately)

1. **B27 · Extension: Passive Ingestion Event API Validation**
  - Why ARC cares: if event hooks are wrong, ARC step transitions never reach memory.
  - ARC impact: invalidates any claims about causal memory improvement.

2. **B29 · TEST CASE: Cross-Session Context Awareness (currently failing)**
  - Why ARC cares: ARC episodes are long-horizon and stateful; recall continuity is mandatory.
  - ARC impact: baseline and augmented modes collapse toward parity if recall is broken.

3. **B17 · Semantic Quest Routing (Hippocampus)**
  - Why ARC cares: ARC sessions are typically non-git; routing must not depend on repo branch context.
  - ARC impact: improves memory scoping and avoids fragmented quest/session memory.

#### Tier 1 (Immediately After Tier 0)

4. **B18 · Context Window Awareness (Working Memory)**
  - Why ARC cares: prevents redundant context injection and improves stable recall under long episodes.
  - ARC impact: better step-to-step coherence and lower token pressure in evaluation loops.

5. **B31 · Recall Ranking Recency Factor**
  - Why ARC cares: ARC requires prioritizing recent failed attempts and newly inferred constraints.
  - ARC impact: reduces repeated invalid action patterns.

6. **B34 · Junk Entity Leakage Fix**
  - Why ARC cares: state-delta text can produce noisy entities; junk pollution weakens causal graph quality.
  - ARC impact: cleaner causal edges and more reliable retrieval.

7. **B42 · Concept→Artifact Retrieval Contract**
  - Why ARC cares: interactive loops need deterministic retrieval semantics (concept vs artifact layer).
  - ARC impact: prevents ambiguous memory outputs during policy decisions.

#### Tier 2 (Scale + Public Evidence)

8. **B45 · Token Efficiency Measurement & Visualization**
  - Why ARC cares: supports public proof that SideQuests improves efficiency and not just anecdotal behavior.
  - ARC impact: stronger external communication and benchmark storytelling.

9. **B36 · Streamable HTTP Transport Audit**
  - Why ARC cares: reduces integration variance across adapters/tools used during demos and cross-client evals.
  - ARC impact: fewer transport-induced benchmark artifacts.

10. **B37/B38 · Graceful Rate Limit/Handoff**
  - Why ARC cares: useful during iterative dev/eval cycles outside strict offline submission runs.
  - ARC impact: continuity during long experiment campaigns.

#### Core Gate Before Public ARC Claims

Before publishing ARC outcome claims, require:
1. Tier 0 complete.
2. At least 3 of Tier 1 complete (must include B18).
3. B54 rules/interface verification complete.
4. One reproducible A/B run from B57 with raw artifacts retained.

**Outcome:** ARC lane remains high priority while core reliability work is sequenced to maximize benchmark validity and public credibility.

---

## Brainstorming Parking Lot
_Ideas raised in conversation — not yet decided or scheduled._

- Native Mac app wrapper (menu bar icon, status indicator, "Brain is thinking..." feedback)
- Homebrew formula for developer install on Mac
- Cloud-hosted Brain Daemon variant (changes privacy model — needs careful thought)
- Windows + Linux install stories (launchd equivalent)
- `sidequests review` CLI for `confidence_low` nodes (pre-M7 audit tool)
- Multi-machine sync (shared Brain Daemon across devices — significant architecture change)
- Action-Oriented Routing — export graph artifacts to real-world targets (shared folders, email drafts, calendar events). Phase 3+ polish, doesn't prove engine. (Source: Clay/ChatGPT analysis, March 2026)
- Voice/Audio Ingestion — Whisper transcription of voice memos → feed transcript into existing Loop pipeline. Valid Phase 3 use case (async ingestion while driving/walking). The Loop already processes text; voice is just a transcription step upstream. Don't build audio infrastructure before engine is proven across text domains. (Source: OpenClaw/Berman analysis, March 2026)

---

## Sub-Agent Readiness Matrix

> Auto-generated 2026-03-27. All 41 active (non-done) cards passed the 4-field readiness check (**Problem** / **What it does** / **Acceptance Criteria** / **Outcome**). Any card in this table can be delegated to a sub-agent without additional context prep.
>
> **How to use:** Pick a card, copy the card ID (e.g. `B17`), then delegate: `gemini -p "Read backlog.md, find B17, implement exactly as specified..." --yolo`

### ✅ All Active Cards — Ready for Sub-Agent Delegation

| Card | Title | Priority | Depends On |
|------|-------|----------|------------|
| B1 | `sidequests setup` CLI | P0 | None |
| B2 | `.mcpb` Bundle (One-Click Claude Desktop Install) | P1 | B1 |
| B3 | ChatGPT Desktop SSE Endpoint | P1 | B1 |
| B4 | Publish to PyPI | P2 | Patent filed |
| B5 | Smithery Listing | P2 | B4 |
| B6 | Claude Desktop Adapter (Full) | P3 | None |
| B7 | ChatGPT Desktop Adapter (Stub → Full) | P3 | B3 |
| B10 | `explore_graph` Tool (Directed Graph Traversal) | P5 | None |
| B11 | `Lesson` Artifact Node | P5 | None |
| B12 | Memory-Based Anomaly Detection (IP Formalization) | P5 | None |
| B14 | Proactive Insight Surfacing | P6 | None |
| B15 | Deep-Link Handoff (Chat → Memory Control Panel) | P6 | M7 |
| B17 | Semantic Quest Routing ("The Hippocampus") | P5 | None |
| B18 | Context Window Awareness ("Working Memory") | P5 | B17 |
| B20 | OpenClaw Extension: Plugin ID Mismatch | P7 | None |
| B21 | OpenClaw System Prompt + Tool Integration | P7 | B20 |
| B22 | OpenClaw Extension: `plugins.allow` Warning | P7 | B13 |
| B27 | Extension: Passive Ingestion Event API Validation | P7 | None |
| B29 | TEST CASE: Cross-Session Context Awareness | P0 | B27, B28 |
| B31 | Improvement: Recall Ranking Needs Recency Factor | P8 | None |
| B34 | Bug: Junk Entities Still Leaking | P8 | None |
| B36 | Audit All Adapters/Plugins for Streamable HTTP Transport | P8 | None |
| B42 | Document Concept→Artifact Retrieval Contract | P9 | None |
| B44 | Token Efficiency as a Side Effect (Not a Feature) | P10 | None |
| B45 | Token Efficiency Measurement & Visualization | P10 | B18, B16 |
| B46 | Benchmark Source Verification + Dataset Pinning | P11 | None |
| B47 | Local Benchmark Runner Infrastructure (Unified Harness) | P11 | B46 |
| B48 | SideQuests A/B Evaluation Contract (Protocol-Correct) | P11 | B47 |
| B49 | SWE-CI Evaluation Card (Maintainability Under Evolution) | P11 | B46–B48 |
| B50 | LoCoBench Evaluation Card (Long-Context Degradation) | P11 | B46–B48 |
| B51 | AMA-Bench + MemoryArena Card (Causality and Interdependent State) | P11 | B46–B48 |
| B52 | Autonomous Research Simulation Harness (Hypothesis Regression Rate) | P11 | B47, B48 |
| B53 | Benchmark Report Pack + Go/No-Go Thresholds | P11 | B49–B52 |
| B54 | ARC-AGI-3 Rules + Interface Verification (Blocker) | P12 | None |
| B55 | ARC Interactive Adapter (Protocol-Correct SideQuests Bridge) | P12 | B54, B48 |
| B56 | Spatial State-to-Text/State Serializer for Causal Memory | P12 | B55 |
| B57 | ARC A/B Harness (Baseline vs SideQuests-Augmented) | P12 | B55, B56 |
| B58 | Offline Model Strategy Card (Allowed Models + Resource Budget) | P12 | B54 |
| B59 | Offline Packaging + Reproducible Execution Bundle | P12 | B58 |
| B60 | Submission Notebook/Runner Assembly + Final Compliance Gate | P12 | B57, B59 |
| B61 | OpenClaw Extension: Tools Not Surfaced to Agent Without Manual Config | P7 | B13 |

### 📊 Readiness Score History

| Date | Total Active | Ready | Not Ready | Notes |
|------|-------------|-------|-----------|-------|
| 2026-03-27 (pre-normalization) | 42 | 16 | 26 | Pre-Wave-1 baseline |
| 2026-03-27 (post-Wave-1) | 42 | 24 | 18 | Wave 1: B17,B27,B29,B31,B34,B36,B42,B45 |
| 2026-03-27 (post-Wave-2) | 42 | 35 | 7 | Wave 2: B1-B7,B14,B15,B20,B22,B61 |
| 2026-03-27 (post-Wave-3) | 42 | 38 | 4 | Wave 3: B48-B51,B54 |
| 2026-03-27 (post-normalization) | 41 | 41 | 0 | All cards normalized; B9 reclassified as DONE |
