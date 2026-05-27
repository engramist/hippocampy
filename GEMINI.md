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
- **Kùzu Abstraction:** All Kùzu-specific logic resides in `mcp_engine/graph/kuzu_client.py`. Do not import `kuzu` directly in other modules.
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

1. **File Bridge** (`mcp_engine/file_bridge.py`) — Generates `CONTEXT.md` and ADR files in project directories from graph state
2. **Associative Hooks** (`mcp_engine/trigger_manifest.py`) — Compiles trigger manifest from Procedure/Lesson nodes; hook scripts inject matching context on tool calls
3. **Anticipatory Engine** (`mcp_engine/loop/step4b_associative.py`) — GCL Step 4b auto-discovers and binds triggers during message processing
4. **Process Skills** (`plugin/skills/`) — 12 process skills (brief, diagnose, grill, handoff, improve-architecture, learn, memory-awareness, quest-management, recall, session-start, status, tdd) auto-installed to Claude Code, Codex, Gemini CLI, and VS Code Copilot by the plugin installer

CLI commands: `campy context regen`, `campy trigger add|list|remove|compile`.

## Key Directories
- `mcp_engine/`: Core logic, including the 9-step consolidation loop.
- `adapters/`: Adapters for Claude, Codex, Gemini CLI, etc.
- `web/`: FastAPI server and static assets for the Memory Control Panel.
- `tests/`: Comprehensive test suite for all components.
