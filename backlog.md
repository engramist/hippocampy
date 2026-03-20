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
