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

## Brainstorming Parking Lot
_Ideas raised in conversation — not yet decided or scheduled._

- Native Mac app wrapper (menu bar icon, status indicator, "Brain is thinking..." feedback)
- Homebrew formula for developer install on Mac
- Cloud-hosted Brain Daemon variant (changes privacy model — needs careful thought)
- Windows + Linux install stories (launchd equivalent)
- `sidequests review` CLI for `confidence_low` nodes (pre-M7 audit tool)
- Multi-machine sync (shared Brain Daemon across devices — significant architecture change)
