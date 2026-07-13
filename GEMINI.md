# HippoCampy Daemon — Project Context

## Project Overview
**HippoCampy Daemon** is a standalone local AI memory system designed to provide persistent, cross-assistant context for software engineering tasks. It uses a **Gated Consolidation Loop**—a 9-step cognitive processing engine modeled on biomimetic heuristics—to transform passive AI memory into a self-correcting, auditable knowledge graph.

The system is built around a **Main Quest / Side Quest** paradigm, anchoring knowledge to specific project contexts (git repositories and branches) and allowing for manual branching into tangents.

### Key Technologies
- **Language:** Python 3.11+
- **Graph/Vector DB:** [Kùzu](https://kuzudb.com/) (embedded, pin version `0.11.3`)
- **NLP/NER:** [spaCy](https://spacy.io/) (`en_core_web_md` model)
- **Embeddings:** [sentence-transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`)
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Memory Control Panel / Web UI)
- **Communication:** JSON-RPC 2.0 over Unix domain sockets (MCP-compatible)
- **LLM Abstraction:** OpenAI-SDK-compatible (supports Ollama, OpenAI, Anthropic, Google)

## Building and Running

### 1. Prerequisites
Ensure you have Python 3.11+ installed and the necessary dependencies.
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_md
```

### 2. Running the Brain Daemon
The daemon must be running for adapters and the web interface to function.
```bash
python brain_daemon.py
```
This starts the IPC server at `~/.campy/brain.sock` and the Kùzu database at `~/.campy/brain.db`.

### 3. Running the Memory Control Panel (Web UI)
The web interface allows for graph visualization and memory management.
```bash
python web/server.py
```
It binds strictly to `127.0.0.1:7799`.

### 4. Registering Adapters
To connect the brain to specific tools like Claude Code:
```bash
python adapters/claude_code/setup.py
```

### 5. Running Tests
The project uses `pytest` for its extensive test suite.
```bash
pytest
```

## Development Conventions

### Architecture & Data Model
- **Graph-Native:** Any entity with identity (Decision, Constraint, Concept) is a node, not a property.
- **Kùzu Abstraction:** All Kùzu-specific logic resides in `campy/brain/hippocampus/graph/kuzu_client.py`. Do not import `kuzu` directly in other modules.
- **Concurrency:** The Brain Daemon holds the sole `READ_WRITE` connection; an `asyncio.Lock` wraps all write operations.
- **Selective Attention:** The "Cocktail Party Effect" is implemented via a confidence gate (Step 4 of the Loop). Only signals >60% confidence are structured; >90% are fully confirmed.

### Security & Integrity
- **Local Only:** All services (FastAPI, IPC) bind to `127.0.0.1` or use Unix sockets.
- **Canonical Paths:** All file operations must use `realpath()` to prevent path traversal.
- **Persistence:** Never revert changes unless explicitly asked. The graph is the "source of truth" for the assistant's memory.
- **No Shadow Stores:** KuzuDB is the single source of truth for ALL persistent agent state. Do NOT store roles, hypotheses, victory conditions, action facts, or other decision-influencing data in Python dicts/instance variables as the primary store. In-memory variables are permitted ONLY as read-through caches over KuzuDB. See `docs/ecosystem-rules.md` "No shadow stores rule".

### Documentation
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md):** Canonical architecture reference — Loop steps, graph schema, IP claims, MCP tool schemas, and all design details. **Read this for any architecture question.**
- **[`docs/ecosystem-rules.md`](docs/ecosystem-rules.md):** Ecosystem layer boundaries, separation rules, and import constraints. **Read this before adding new code or changing boundaries.**
- **[`docs/codebase-anatomy.md`](docs/codebase-anatomy.md):** Target region map for new code placement during the anatomy refactor.
- **[`docs/codebase-anatomy-refactor-plan.md`](docs/codebase-anatomy-refactor-plan.md):** Migration notes and sequencing context for the anatomy refactor.
- **[`plugin/skills/recall/SKILL.md`](plugin/skills/recall/SKILL.md):** Canonical memory-use policy (ships with plugin; dev-only: `skills/campy-memory/SKILL.md`). Do not recall on every turn; if unsure, call `memory_decision` before choosing a recall tool.
- **CLAUDE.md:** Claude-specific workflow (delegation model).
- **InvertorsDocs/:** Original Inventor's Notebook and seed examples for the ontology.

### Activity Indicator
Use the Campy activity feed as the first-line indicator for live memory behavior:

```bash
.venv/bin/campy activity --follow
```

This tails `~/.campy/activity.log`, a compact operator feed for memory writes, recall calls, durable capture scans, and daemon lifecycle state. It redacts full prompt and response bodies while preserving useful metadata like source client, role, session, character counts, recall query previews, and success/error status. Use `~/.campy/daemon.log` only for debugging failures or stack traces.

## Context Window Integration (Layer Cake)

Campy uses a 4-layer architecture to automatically inject graph knowledge into agent context windows:

1. **File Bridge** (`campy/brain/thalamus/file_bridge.py`) — Generates `CONTEXT.md` and ADR files in project directories from graph state
2. **Associative Hooks** (`campy/brain/thalamus/trigger_manifest.py`) — Compiles trigger manifest from Procedure/Lesson nodes; hook scripts inject matching context on tool calls
3. **Anticipatory Engine** (`campy/brain/temporal_lobe/loop/step4b_associative.py`) — GCL Step 4b auto-discovers and binds triggers during message processing
4. **Process Skills** (`plugin/skills/`) — 12 process skills (brief, diagnose, grill, handoff, improve-architecture, learn, memory-awareness, quest-management, recall, session-start, status, tdd) auto-installed to Claude Code, Codex, Gemini CLI, and VS Code Copilot by the plugin installer

CLI commands: `campy context regen`, `campy trigger add|list|remove|compile`.

## Key Directories
- `campy/brain/`: Core logic, including the 9-step consolidation loop.
- `adapters/`: Adapters for Claude, Codex, Gemini CLI, etc.
- `web/`: FastAPI server and static assets for the Memory Control Panel.
- `tests/`: Comprehensive test suite for all components.

<!-- CAMPY-MEMORY-START -->


## Campy Memory Integration

The Campy MCP server provides persistent AI memory. Follow the recall protocol below.

# Campy Memory — Session Recall Protocol

You have access to a persistent AI memory system called Campy (HippoCampy). It remembers decisions, constraints, plans, and context across all your sessions.

## At Session Start — MANDATORY

**BEFORE doing any work, you MUST follow this protocol:**

1. Call `memory_decision` with the user's first message:
   ```
   memory_decision(query="<user's first message>", session_id="<session>")
   ```

2. Call the recommended tool from Step 1's response:
   - `current_truth` for single-topic recall
   - `compile_context` for broad context needs
   - `recall_procedures` for process questions
   - `recall_relevant_lessons` for past outcomes

3. If continuing existing work, call `diff_since` to see recent changes:
   ```
   diff_since(since_iso="<24 hours ago ISO>")
   ```

4. Present findings to the user before starting work.

## During the Session — Recall Triggers

| When You See This | You MUST Call This |
|---|---|
| Questions about past decisions | `current_truth(query="<topic>")` |
| Architecture or design questions | `current_truth(query="<topic>")` |
| Multi-entity or broad queries | `compile_context(query="<topic>")` |
| "Why did we choose X?" | `current_truth(query="decision about X")` |
| Process or procedure questions | `recall_procedures(query="<topic>")` |
| "What went wrong last time?" | `recall_relevant_lessons(query="<topic>")` |
| Not sure which tool | `memory_decision(query="<question>")` |

## After Every Response — MANDATORY

**AFTER every response, you MUST call `notify_turn`:**

```
notify_turn(role="assistant", content="<your full response>", session_id="<session>")
```

This is how the Brain captures knowledge. Never skip it.

## Available Tools

| Tool | Purpose |
|---|---|
| `memory_decision` | Ask the Brain which recall tool to use |
| `current_truth` | Semantic search for specific facts |
| `compile_context` | Multi-source bundle compilation |
| `recall_procedures` | Process and procedure knowledge |
| `recall_relevant_lessons` | Past outcomes and lessons learned |
| `reconstruct_timeline` | Temporal view of events |
| `diff_since` | Changes since a timestamp |
| `analogical_search` | Cross-project pattern matching |
| `notify_turn` | Capture your response in memory |
| `ingest_data` | Ingest files/data into memory |
| `reconstruct_timeline` | Sequence, history, chronology | 0.8 | Ordered events + timestamps |
| `recall_plans` | Similar prior work, strategies | 0.75 | Plans + outcomes + lessons |
| `recall_procedures` | Workflows, standard processes | 0.85 | Step-by-step + variants |
| `recall_relevant_lessons` | Learned lessons, anti-patterns | 0.8 | Lesson + context + application |
| `analogical_search` | Similar past projects | 0.7 | Analogies + key differences |
| `recall_mechanic_priors` | ARC mechanics, world models | 0.75 | Mechanic signature + evidence |
| `recall_scene_graph_priors` | ARC scene graphs, spatial patterns | 0.75 | Scene pattern + success rate |
| `memory_decision` | Should I recall? Which tool? | 0.9 | Recommendation + confidence |
| `context_status` | Token/context health | 0.95 | Metrics + warnings |

---

## Anti-Bloat Rules

1. **Do not recall for every turn.** Only recall when a *decision needs memory*.

2. **Do not dump raw memory into your answer.** Use memory to *inform* your decision, then synthesize a compact answer.

3. **Prefer top 3 results unless you ask for exhaustive review.** Tools return ranked results; use the top few unless context demands exhaustive analysis.

4. **Summarize recalled memory compactly.** Example: "The prior installer learned X; we fixed Y by doing Z" - not the raw message dump.

5. **Use raw Message/DocumentExtract evidence as *provenance*, not primary context.** If you recall "the team decided on async pattern," cite the evidence but explain it yourself.

6. **If unsure whether to recall, call `memory_decision` first.** It's cheap and faster than guessing wrong.

7. **Recall refines; it doesn't replace current context.** Your current messages remain your primary working context.

---

## Examples

### Good: Selective, Compact Recall

**User:** "I need to implement the installer. What did we learn from the last attempt?"

**You:** (Call `recall_plans` with query "installer design and failures")
-> Returns: [Plan A (failed due to X), Plan B (succeeded with constraints Y), Lesson Z]

**Your answer:** "We learned that async bootstrapping is necessary (Plan B). Last time we avoided it and hit timeout issues. Let me build on that approach for this installer."

---

### Bad: Bloated, Unnecessary Recall

**User:** "Fix the typo on line 42"

**You:** (Call `current_truth` with query "line 42 typo context"  - DON'T DO THIS)

-> Your context bloats for no reason. Just fix the typo.

---

### Good: Structured Timeline

**User:** "Walk me through how we debugged the graph corruption."

**You:** (Call `reconstruct_timeline` with query "graph corruption debug sequence")
-> Returns: Event 1 (2026-03-15 10:30): noticed X, Event 2 (10:35): traced to Y, Event 3 (11:00): fixed by Z

**Your answer:** "Here's the sequence: we noticed corruption in the morning, traced it to a race condition in the sweep loop, and fixed it with a transaction lock."

---

## Activity Indicator

After you use memory, you can verify capture/recall worked:

```bash
campy activity --follow
```

This shows live events:
- `notify_turn` - your message was captured
- Consolidation steps - the system processed and stored it
- `recall` operations - when memory was retrieved
- Warnings - potential issues

---

## Failure Modes

### "Brain daemon is offline"
-> Passive capture stops. You can still edit and code. When the daemon restarts, it will resume captures.
-> **Workaround:** `campy doctor --repair` and `campy activity --follow` to monitor restart.

### "Recall tool timed out"
-> Network or KuzuDB latency. Recall failed; no memory was added to context.
-> **Workaround:** Retry or use `context_status` to check health. Fall back to current context.

### "I got the wrong recall results"
-> Query was ambiguous or memory is sparse (new quest).
-> **Workaround:** Rephrase the query more specifically. Example: "installer bootstrap script" instead of "install".

### "I'm using too much context"
-> Too many recalls or memory payloads are too large.
-> **Workaround:** Use `context_status` first. Call `memory_decision` before recalling. Reduce result count (top 3 instead of top 10).

---

## Key Takeaways

1. **Write is passive; recall is active.** Campy listens. You decide when to remember.
2. **Recall is selective.** Use the decision tree to pick the right tool for the question.
3. **Compact is better.** Summarize, don't dump. Prefer top results. Use evidence for provenance.
4. **`memory_decision` is your copilot.** If unsure, ask it first.
5. **`campy activity --follow` is your verification.** Watch the feed to confirm capture/recall worked.

---

**Last Updated:** May 11, 2026  
**Status:** Canonical Policy (all agents share this core guidance)

<!-- CAMPY-MEMORY-END -->
