# SideQuest Brain Daemon — Project Context

## Project Overview
**SideQuest Brain Daemon** is a standalone local AI memory system designed to provide persistent, cross-assistant context for software engineering tasks. It uses a **Gated Consolidation Loop**—a 9-step cognitive processing engine modeled on biomimetic heuristics—to transform passive AI memory into a self-correcting, auditable knowledge graph.

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
This starts the IPC server at `~/.sidequests/brain.sock` and the Kùzu database at `~/.sidequests/brain.db`.

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

### Documentation
- **CLAUDE.md:** Provides comprehensive documentation on the Gated Consolidation Loop, IP claims, and detailed architectural notes.
- **InvertorsDocs/:** Contains the original "Inventor's Notebook" and seed examples for the ontology.

## Key Directories
- `mcp_engine/`: Core logic, including the 9-step consolidation loop.
- `adapters/`: Adapters for Claude, Codex, Gemini CLI, etc.
- `web/`: FastAPI server and static assets for the Memory Control Panel.
- `tests/`: Comprehensive test suite for all components.
