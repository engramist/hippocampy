# SideQuests Brain — Backlog

> M1–M8 are complete. This backlog tracks post-M8 work.

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
Make the system actually usable without manual JSON editing.

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

---

### B2 · `.mcpb` Bundle (One-Click Claude Desktop Install)
Package the entire system as a Desktop Extension so non-technical Claude Desktop users get a true one-click install.

What it does:
- Bundles adapter code + deps + launchd plist into a `.mcpb` (ZIP + manifest.json)
- User opens Claude Desktop > Settings > Extensions > install `.mcpb`
- Claude Desktop runs the bundle's lifecycle hooks → daemon starts, adapter registered

Files to create:
- `mcpb/manifest.json` — bundle manifest (name, description, version, entry point, permissions)
- `mcpb/install.sh` — lifecycle hook: installs launchd plist + loads daemon
- `mcpb/uninstall.sh` — teardown hook
- `Makefile` target: `make mcpb` → runs `mcpb pack` to produce `sidequests-brain.mcpb`

Dependencies:
- `mcpb` CLI: `npm install -g @anthropic-ai/mcpb`
- Requires B1 (launchd plist generation) as a dependency

Notes:
- The `.mcpb` adapter entry point is `adapters/claude_code/adapter.py` (same as manual install)
- Brain Daemon is started by the lifecycle hook, NOT by the `.mcpb` directly
- Target audience: non-technical Claude Desktop users

---

### B3 · ChatGPT Desktop SSE Endpoint
Add an SSE (Server-Sent Events) transport to the Brain Daemon's web server so ChatGPT Desktop can connect as a Connector.

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

---

## P2 — Distribution / Discoverability

### B4 · Publish to PyPI
Make `pip install sidequests-brain` and `uvx sidequests-brain` work.

- Create `pyproject.toml` with proper metadata, entry points, and dependency declarations
- `sidequests setup` as the primary CLI entry point
- Test `uvx sidequests-brain setup` end-to-end

Notes:
- Only publish after provisional patent is filed (IP protection constraint)
- `uvx` is the target developer install story

---

### B5 · Smithery Listing
List on Smithery for discoverability.

- Create Smithery-compatible server definition
- Submit to `smithery.ai` registry
- Enables: `npx @smithery/cli install sidequests-brain --client claude`

Notes:
- Only publish after provisional patent is filed
- Requires B4 (PyPI) first

---

## P3 — Adapters (Deferred from M8)

### B6 · Claude Desktop Adapter (Full)
The Claude Desktop adapter is referenced in CLAUDE.md (`adapters/claude_desktop/adapter.py`) but only the Codex adapter was built in M8. Claude Desktop uses the same stdio MCP protocol as Claude Code — adapter is nearly identical.

Files to create:
- `adapters/claude_desktop/adapter.py` — copy of Claude Code adapter with `serverInfo.name = "sidequests-brain-desktop"`

---

### B7 · ChatGPT Desktop Adapter (Stub → Full)
`adapters/chatgpt_desktop/adapter.py` is a stub. If B3 (SSE endpoint) is built, this adapter may be unnecessary — the SSE route in `web/server.py` handles it. Decide after B3.

---

### B8 · Gemini CLI Adapter — DONE
`adapters/gemini_cli/adapter.py` — completed 2026-03-18. Protocol version negotiation, `resources/list`, and full tool surface implemented. Requires `gemini trust` per project folder.

---

## P4 — Missing Tests

### B9 · `tests/test_adapters.py`
Still a docstring stub. Needs full adapter integration tests covering:
- Tool registration for all adapters
- `handle_mcp_request` routing for all tools
- Offline queue behavior
- Git context injection

---

## P5 — New Capabilities (Post-M8 Research)

### B17 · Semantic Quest Routing ("The Hippocampus")
Replace git-only MainQuest identification with a semantic routing mechanism that works for desktop apps and non-dev users. Two-phase System 1/2 routing: git context as one high-confidence signal, content embedding similarity for the rest. Progressive consolidation (tentative → consolidated → locked) with prediction error reconsolidation.

New module: `mcp_engine/hippocampus.py`. New tool: `set_quest`. Schema changes: MainQuest gets `purpose_embedding`, `routing_method`; Session gets `routing_state`, `routing_confidence`. New relationship: `REROUTED_FROM`.

Architecture doc: `B17-B18-architecture.md`. Dependency: None (builds on existing quest infrastructure). Implement before B18.

IP claims: Semantic Quest Routing, Hippocampus Mechanism, Prediction Error Reconsolidation, Multi-Signal Routing Fusion.

---

### B18 · Context Window Awareness ("Working Memory")
Model each LLM session as a tracked working memory buffer. Track which graph nodes are loaded in each context window via `LOADED` edges. Smart deduplication in `current_truth` (demote, don't exclude already-loaded nodes). Token estimation, bloat detection, session handoff intelligence.

New module: `mcp_engine/working_memory.py`. New tool: `context_status`. Schema changes: Session gets `token_estimate`, `token_limit`, `loaded_node_count`; new `LOADED` relationship (multi-FROM).

Architecture doc: `B17-B18-architecture.md`. Dependency: B17 (shared Session schema changes, `notify_turn` rewire).

**Design constraint (from graph schema review, 2026-03-22):** Session is a supernode risk — it accumulates `SENT_IN` (every message), `LOADED` (every injected node), `WORKING_ON`, `USED`, `IN_WORKSPACE`, `REROUTED_FROM`. Implementation must include a session edge pruning strategy: archive stale `LOADED` edges aggressively, keep session-centric traversals narrow and task-specific, never use Session as a general-purpose hop for exploratory queries.

IP claims: Context Window as Working Memory Model, Smart Deduplication via Load Tracking, Session Handoff Intelligence, Bloat Detection via Token Estimation.

---

### B10 · `explore_graph` Tool (Directed Graph Traversal)
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

---

### B11 · `Lesson` Artifact Node
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

---

### B12 · Memory-Based Anomaly Detection (IP Formalization)
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

---

## P0 — Installation Experience (Critical — Blocking Adoption)

### B13 · Guided Installer with LLM Provider Choice
The current installation process is fragile and manual — requires hand-editing config files, manually installing Ollama, pulling models, running multiple CLI commands, and debugging cascading failures. This is the #1 adoption blocker.

**What it should do:**
- Single entry point: `sidequests install` (or a `.dmg` / native installer on macOS)
- Interactive wizard asks one key question upfront: **"Do you want a free local model (Ollama) or bring your own API keys?"**
  - **Local (Ollama):** Auto-install Ollama via Homebrew (macOS) or package manager (Linux), pull the default model (`llama3.1:8b`), verify it's running
  - **Cloud (BYOK):** Prompt for provider choice (OpenAI / Anthropic / Google) and API key, validate the key works with a test call
- Auto-detect installed AI clients (Claude Code, Claude Desktop, Codex, Gemini CLI, ChatGPT Desktop)
- Register MCP adapters for all detected clients (user scope, not project-local)
- Write `sidequests.toml` with correct provider config
- Run full smoke test: LLM ping + embedding model load + Kùzu schema init + spaCy model download + `tools/list` round-trip
- Print clear pass/fail report with actionable fix instructions for any failures
- Must be idempotent — safe to re-run

**Potential distribution formats:**
- `.dmg` with drag-to-install (macOS — best for non-technical users)
- Homebrew formula: `brew install sidequests-brain`
- `pipx install sidequests-brain` (developer audience)
- `.mcpb` bundle for Claude Desktop one-click install (see B2)

**Dependencies to auto-install:**
- Ollama (if local model chosen)
- spaCy `en_core_web_md` model
- sentence-transformers model (auto-downloaded on first use, but should pre-warm)
- Kùzu schema init

**Supersedes:** B1 (`sidequests setup` CLI) — B13 is the full vision; B1 is the MVP subset.

---

### B19 · `sidequests uninstall` Command
Reverse everything `sidequests install` does. Required before public release / beta testers.

**What it does:**
- Remove `sidequests-brain` MCP entry from all detected client configs (Claude Desktop, Claude Code `.mcp.json`, etc.)
- Unload and remove the launchd plist (`~/Library/LaunchAgents/ai.sidequests.brain.plist`)
- Optionally delete the Kùzu database and `sidequests.toml` (prompt user, default: keep data)
- Optionally remove Ollama model (`ollama rm qwen2.5:3b`) if no other tools use it

**Priority:** Before public release, not before wife demo. Follow-up to B13.

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

**Dependencies:** M7 (Memory Control Panel) must have routable views.

---

### B16 · Task-Based Model Routing
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
The `openclaw.plugin.json` uses `id: "sidequests-brain"` but the npm `package.json` uses a different name (`openclaw-brain`). This causes a persistent config warning on every gateway startup:
```
plugin id mismatch (manifest uses "sidequests-brain", entry hints "openclaw-brain")
```

**Fix:** Align `package.json` `name` field with `openclaw.plugin.json` `id` field. Both should be `sidequests-brain`.

**Files:** `extensions/sidequests-brain/package.json`, `extensions/sidequests-brain/openclaw.plugin.json`

---

### B21 · OpenClaw Extension: Tools Not Surfaced to Agent Without Manual Config
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

**Files:** `sidequests/cli/setup.py` (or equivalent installer), `extensions/sidequests-brain/README.md` (document the manual step until installer handles it)

---

### B22 · OpenClaw Extension: `plugins.allow` Warning
OpenClaw warns on every startup that `plugins.allow` is empty and non-bundled plugins auto-load. The installer should set `plugins.allow` to explicitly trust the sidequests-brain plugin:
```json
"plugins": {
  "allow": ["sidequests-brain"]
}
```

**Fix:** Add to installer config step. Low priority — cosmetic warning, no functional impact.

**Files:** `sidequests/cli/setup.py`

---

### B23 · ~~OpenClaw Extension: SSE Connection Per Tool Call is Expensive~~ RESOLVED
~~The `BrainClient.callTool()` method opens a new SSE connection per call.~~

**Resolved 2026-03-21:** Upgraded to Streamable HTTP transport (MCP 2025-03-26). `POST /mcp` now returns results directly in the response body. Single HTTP round-trip per tool call. Commit: `feat: upgrade MCP transport from SSE to Streamable HTTP (2025-03-26)`

---

### B24 · OpenClaw Extension: Missing `memory_search`, `memory_get` Core Tool Aliases
The OpenClaw `coding` tools profile expects `memory_search` and `memory_get` (core memory tools from the default `memory-core` plugin). When sidequests-brain replaces `memory-core`, these are missing:
```
tools.profile (coding) allowlist contains unknown entries (apply_patch, memory_search, memory_get)
```

**Fix:** Either register `memory_search` and `memory_get` as aliases for `memory_recall` in the extension, or document that the `coding` profile warning is harmless.

**Files:** `extensions/sidequests-brain/src/index.ts`

---

### B25 · OpenClaw Installer: `sidequests setup --target openclaw`
Add OpenClaw as a supported target in the installer. Should:
1. Detect if `openclaw` CLI is installed (`which openclaw`)
2. Install the extension: `openclaw plugins install <path>`
3. Configure sandbox tool allowlist
4. Configure `plugins.allow`
5. Restart the gateway
6. Verify: `openclaw sandbox explain` shows memory tools in allow list

**Depends on:** B1/B13 (installer framework), B20-B22 (extension fixes)

**Files:** `sidequests/cli/setup.py`

---

### B26 · Document: OpenClaw Standalone Install Guide
Comprehensive install doc for OpenClaw standalone (not NemoClaw) with SideQuests Brain integration. Covers:
- OpenClaw install via npm
- OrbStack/Docker setup for sandbox
- Sandbox image build
- Gateway config (security hardening)
- Discord bot setup
- Brain Daemon + plugin wiring
- Troubleshooting

**Reference:** `~/Desktop/B-openclaw-standalone-install.md` (draft created 2026-03-21, needs updating with plugin steps)

**Files:** `docs/openclaw-install.md`

---

### B41 · OpenClaw Integration: Ensure Brain Daemon Auto-Starts with Gateway Sessions
When OpenClaw gateway starts, the SideQuests memory plugin currently only pings the Brain Daemon and logs a warning if `http://127.0.0.1:7799` is unreachable. This is correct for health reporting, but it creates a poor first-run experience because memory tools silently fail until the daemon is started separately.

**Preferred fix:** Treat the Brain Daemon as a managed background service, not something spawned by the plugin. On macOS this should use the existing `launchd` path (`RunAtLoad` + `KeepAlive`) so the daemon is already running before OpenClaw starts, survives gateway restarts, and auto-recovers from crashes.

**Optional fallback:** Add an opt-in plugin behavior in `extensions/sidequests-brain/src/index.ts` `start()` that attempts to launch the daemon when `brain.ping()` fails. This should be disabled by default and only used as a convenience fallback, since plugin-managed process launch is more fragile (paths, env, permissions, duplicate daemon risk).

**Acceptance criteria:**
- `sidequests install` or `sidequests setup --target openclaw` configures the Brain Daemon as a persistent user service where supported
- After reboot/login, OpenClaw gateway sees the Brain Daemon as reachable without manual startup
- If the daemon crashes, service management restarts it independently of OpenClaw
- Plugin startup warning is updated to distinguish between "service not installed" and "daemon temporarily unreachable"
- If plugin auto-launch fallback is added, it is explicitly opt-in and avoids spawning duplicate daemon instances

**Files:** `sidequests/cli/install.py`, `sidequests/cli/setup.py`, `sidequests/cli/launchd.py`, `extensions/sidequests-brain/src/index.ts`, `docs/openclaw-install.md`

---

### B28 · CRITICAL: `api.registerTool()` Does Not Surface Tools to Agent Sessions — ✅ FIXED (2026-03-22)
**GitHub Issue:** [#1](https://github.com/djs54/sidequests-brain/issues/1)

**Fix applied:**
1. Fixed `package.json` name from `@sidequests/openclaw-brain` → `@sidequests/sidequests-brain` to match `openclaw.plugin.json` manifest ID
2. Added `alsoAllow: ["group:plugins"]` to `tools` section in `~/.openclaw/openclaw.json`
3. Reinstalled plugin with `openclaw plugins install --force`

**Verified (2026-03-22 smoke test):** All 5 tools (`memory_recall`, `memory_store`, `memory_search_analogies`, `memory_status`, `memory_open_loops`) return valid results from agent sessions. Passive ingestion continues working.

**Files:** `extensions/sidequests-brain/package.json`, `extensions/sidequests-brain/src/index.ts`
**Priority:** P0 — ✅ resolved
**Depends on:** None

---

### B27 · Extension: Passive Ingestion Event API Validation
The extension uses `api.on("llm_input")`, `api.on("llm_output")`, and `api.on("before_agent_start")` — these event names were assumed from the OpenClaw plugin docs. Need to verify:
1. Are these the correct event names in OpenClaw 2026.3.13?
2. Is the event payload shape correct (`event.prompt`, `event.assistantTexts`)?
3. Are hooks actually firing? (Gateway logs show "Connected" but no ingestion confirmation)

**Fix:** Test each event by adding temporary logging. Adapt event names/payloads to match actual API.

**Files:** `extensions/sidequests-brain/src/index.ts`

---

## P8 — Cross-Session Awareness (Discovered 2026-03-21)

The core value proposition of SideQuests Brain as a memory system for OpenClaw agents: multiple sessions of the same agent share a persistent knowledge graph, so they all know what the others have been doing.

### B29 · TEST CASE: Cross-Session Context Awareness
**Status:** FAILING (2026-03-21)  
**Priority:** P0 — this is the entire reason the Brain exists

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

**Acceptance criteria:**
- [ ] Session A stores a decision via conversation (e.g., "We decided to use Streamable HTTP")
- [ ] Session B, started fresh with no shared context window, queries "What transport protocol did we choose?"
- [ ] Session B's `current_truth` returns the Streamable HTTP decision from session A
- [ ] Session B can give an informed answer without reading markdown files

**Depends on:** B28 (tool binding), B27 (hook validation), working quest routing for non-git sessions

**Files:** `extensions/sidequests-brain/src/index.ts` (hooks), `mcp_engine/tools.py` (current_truth), agent system prompt / SOUL.md

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
When recalling memories, old high-pathway-strength nodes dominate over recently stored, highly relevant ones. A "Redis caching decision" stored 5 minutes ago loses to a "JWT" concept from 2 days ago.

**Fix:** Add recency decay to the ranking formula in `current_truth`:
```python
from datetime import datetime, timezone
days_old = (datetime.now(timezone.utc) - node_created_at).total_seconds() / 86400
recency = 1.0 / (1 + days_old)
rank = (ps * conf * 0.4) + (similarity * 0.4) + (recency * 0.2)
```

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

**Files:** `mcp_engine/loop/step1_ner.py`

---

### B35 · Bug: `set_quest` Fails with Kuzu Schema Error
`set_quest` tool returns: `Binder exception: Cannot find property git_repo_root for q.`

The hippocampus code references `git_repo_root` on the MainQuest table, but the property doesn't exist in the schema (or was renamed).

**Files:** `mcp_engine/hippocampus.py`, `mcp_engine/schema.py`

---

### B36 · Audit All Adapters/Plugins for Streamable HTTP Transport
**Priority:** Medium  
**Status:** Not started

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
The `Concept → REIFIED_AS → Artifact` dual-layer design is intentional, but the retrieval contract is not documented outside CLAUDE.md. When does `current_truth` return Concepts vs artifact nodes vs both? How should callers interpret results when the same idea exists at both layers?

**What it does:**
- Document which layer `current_truth` searches (currently: artifact tables via `UNION ALL` across per-table HNSW indexes)
- Define the canonical rule: when should something stay a `Concept` vs when it should be promoted and primarily retrieved as an artifact?
- Clarify whether `explore_graph` should traverse through `REIFIED_AS` or start from artifact nodes directly
- Add this as a design doc section in `B17-B18-architecture.md` or a standalone `docs/retrieval-contract.md`

**Why it matters:** Without a documented contract, future retrieval work risks creating parallel truth layers where concept-layer and artifact-layer results compete in confusing ways.

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
