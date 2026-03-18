# SideQuests Brain — Backlog Implementation Guide (B1–B12)

> **Purpose:** Hand this document to Sonnet 4.6 (or any capable coding agent) to execute each backlog item. Each section is self-contained with exact file paths, function signatures, code patterns to follow, acceptance criteria, and known gotchas.
>
> **Execution order:** B1 → B4 → B6 → B8 → B9 → B3 → B7 → B2 → B5 → B10 → B11 → B12
> (B1 unlocks everything; B4 creates pyproject.toml needed by B2/B5; adapters before tests; B12 is docs-only.)

---

## Pre-Read: Codebase Conventions

Before implementing anything, internalize these patterns:

### Tool Handler Signature (daemon side)
```python
async def tool_name(params: dict, db: KuzuClient, config: dict) -> dict:
```
All handlers live in `mcp_engine/tools.py` and are registered in `TOOL_HANDLERS` dict at the bottom of that file.

### Adapter Structure (MCP STDIO)
Every adapter follows the same skeleton (see `adapters/claude_code/adapter.py` as canonical reference):
1. Git context detection at import time
2. `TOOLS` list (JSON Schema for each tool)
3. `_call_brain(method, params)` — Unix socket JSON-RPC client
4. `_queue_offline(method, params)` — JSONL offline queue
5. `_inject_git_context(params)` — adds `repo_root` + `git_branch`
6. `handle_mcp_request(request)` — MCP lifecycle routing
7. `async def main()` — stdin/stdout JSON-RPC loop

### Key Constants
| Name | Value | Where |
|------|-------|-------|
| `SOCKET_PATH` | `~/.sidequests/brain.sock` | All adapters |
| `OFFLINE_QUEUE` | `~/.sidequests/offline_queue.jsonl` | All adapters |
| `DB_PATH` | `~/.sidequests/brain.db` | `brain_daemon.py` |
| `WEB_HOST` | `127.0.0.1` | `web/server.py` |
| `WEB_PORT` | `7799` | `sidequests.toml` |
| `_SOCKET_TIMEOUT` | `10.0` | Claude Code adapter |

### Security Rules (Non-Negotiable)
- **No TCP/HTTP listening ports** except the FastAPI web server on `127.0.0.1`
- All file paths canonicalized via `realpath()`; block `..` and symlinks
- Never bind to `0.0.0.0`

### Test Patterns
- `pytest` + `pytest-asyncio`
- Shared fixtures in `tests/conftest.py`
- Adapters tested via `handle_mcp_request()` with monkeypatched `_call_brain`
- DB-dependent tests use mock `KuzuClient` or real temp DB

---

## B1 — `sidequests setup` CLI

**Goal:** One command to detect installed AI clients, register adapters, start the daemon, and run a smoke test. Replace all manual JSON editing.

### Files to Create

#### `sidequests/cli/__init__.py`
Empty `__init__.py`.

#### `sidequests/cli/main.py`
CLI entry point using `click` (add `click>=8.1` to `requirements.txt`).

```python
"""sidequests CLI — setup, start, stop, status, review."""
import click

@click.group()
def cli():
    """SideQuests Brain Daemon CLI."""
    pass

@cli.command()
@click.option("--target", type=click.Choice(
    ["claude-code", "claude-desktop", "codex", "chatgpt-desktop", "gemini-cli", "all"],
    case_sensitive=False), default="all",
    help="Which AI client to register. 'all' detects installed clients.")
@click.option("--project-root", type=click.Path(exists=True), default=None,
    help="Project root for .mcp.json (Claude Code only). Defaults to cwd.")
def setup(target, project_root):
    """Detect AI clients, register adapters, start the Brain Daemon."""
    from sidequests.cli.setup import run_setup
    run_setup(target=target, project_root=project_root)

@cli.command()
def start():
    """Start the Brain Daemon (foreground)."""
    from sidequests.cli.daemon_ctl import start_daemon
    start_daemon()

@cli.command()
def stop():
    """Stop the Brain Daemon (launchd/systemd)."""
    from sidequests.cli.daemon_ctl import stop_daemon
    stop_daemon()

@cli.command()
def status():
    """Check if the Brain Daemon is running and healthy."""
    from sidequests.cli.smoke_test import check_status
    check_status()

if __name__ == "__main__":
    cli()
```

#### `sidequests/cli/detect.py`
Detect which AI clients are installed on the system.

```python
"""Detect installed AI clients."""
from pathlib import Path
import shutil
import subprocess

def detect_installed_clients() -> dict[str, bool]:
    """
    Returns {"claude-code": True/False, "claude-desktop": True/False, ...}

    Detection methods:
      claude-code:     `which claude` succeeds
      claude-desktop:  ~/Library/Application Support/Claude/ exists (macOS)
      codex:           `which codex` succeeds
      chatgpt-desktop: ~/Library/Application Support/com.openai.chat/ exists (macOS)
      gemini-cli:      `which gemini` succeeds
    """
    # Implementation: use shutil.which() for CLI tools,
    # Path.exists() for GUI app support directories.
    # Return dict with bool values.
```

#### `sidequests/cli/setup.py`
Main setup orchestration.

```python
"""sidequests setup — register adapters + start daemon."""
from pathlib import Path

def run_setup(target: str, project_root: str | None) -> None:
    """
    1. Detect installed clients (or use --target)
    2. For each detected client, call register_<client>(project_root)
    3. Write/update sidequests.toml if not present
    4. Write launchd plist (macOS) and load it
    5. Run smoke test
    6. Print pass/fail report
    """
```

Registration per client:

| Client | Registration Action | Config File |
|--------|-------------------|-------------|
| `claude-code` | Write `.mcp.json` in project root + `UserPromptSubmit` hook in `~/.claude/settings.json` | Uses existing `adapters/claude_code/setup.py:register()` |
| `claude-desktop` | Write entry to `~/Library/Application Support/Claude/claude_desktop_config.json` | `{"mcpServers": {"sidequests-brain": {"command": "python", "args": ["/abs/path/to/adapters/claude_desktop/adapter.py"]}}}` |
| `codex` | Write entry to `~/.codex/config.toml` or project `.codex/config.toml` | `[mcp_servers.sidequests]\ncommand = "python"\nargs = ["/abs/path/to/adapters/codex/adapter.py"]` |
| `chatgpt-desktop` | Print manual instruction (SSE URL) OR write connector config if API exists | Depends on B3 |
| `gemini-cli` | Write entry to Gemini CLI MCP config | TBD — check Gemini CLI docs at build time |

**Key behaviors:**
- **Idempotent** — safe to run multiple times. Check for existing registration before writing.
- **Merge, don't overwrite** — read existing config files, merge the sidequests entry, write back. Never clobber other MCP servers.
- **Resolve adapter paths** — use `Path(__file__).resolve()` to get absolute paths to adapter scripts. Never use relative paths in config files.

#### `sidequests/cli/launchd.py`
macOS daemon management via launchd.

```python
"""launchd plist generation + control (macOS only)."""
from pathlib import Path
import subprocess
import sys
import plistlib

PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "ai.sidequests.brain.plist"

def write_plist() -> Path:
    """
    Write ~/Library/LaunchAgents/ai.sidequests.brain.plist

    Plist contents:
      Label: ai.sidequests.brain
      ProgramArguments: [sys.executable, "/abs/path/to/brain_daemon.py"]
      RunAtLoad: true
      KeepAlive: true
      StandardOutPath: ~/.sidequests/daemon.log
      StandardErrorPath: ~/.sidequests/daemon.log
      WorkingDirectory: <repo_root>

    Use stdlib plistlib to write (no external deps).
    Returns the plist path.
    """

def load_plist() -> bool:
    """Run `launchctl load <plist_path>`. Returns True on success."""

def unload_plist() -> bool:
    """Run `launchctl unload <plist_path>`. Returns True on success."""

def is_loaded() -> bool:
    """Check if ai.sidequests.brain is loaded via `launchctl list`."""
```

#### `sidequests/cli/smoke_test.py`
End-to-end validation.

```python
"""Smoke test: verify Brain Daemon is running and responsive."""
import asyncio
import json
from pathlib import Path

SOCKET_PATH = Path.home() / ".sidequests" / "brain.sock"

async def smoke_test() -> dict:
    """
    Run 3 checks, return {"checks": [...], "passed": bool}:

    1. Socket exists and daemon accepts connection
       → open_unix_connection to SOCKET_PATH

    2. tools/list returns expected tools
       → send JSON-RPC {"method": "tools/list"} and verify response

    3. Kùzu schema initialized (at least GistClass nodes exist)
       → send JSON-RPC {"method": "current_truth", "params": {"query": "test", "session_id": "smoke"}}
       → verify response has "results" key (even if empty)

    Each check: {"name": str, "passed": bool, "detail": str}
    """

def check_status():
    """Print human-readable status to stdout."""
    result = asyncio.run(smoke_test())
    for check in result["checks"]:
        icon = "PASS" if check["passed"] else "FAIL"
        print(f"  [{icon}] {check['name']}: {check['detail']}")
    if result["passed"]:
        print("\nBrain Daemon is healthy.")
    else:
        print("\nSome checks failed. Run `sidequests start` to start the daemon.")
```

#### `sidequests/cli/daemon_ctl.py`
Start/stop helpers.

```python
"""Daemon start/stop control."""
import subprocess
import sys

def start_daemon():
    """Start brain_daemon.py in foreground (for manual use / debugging)."""
    # exec into brain_daemon.py — replaces current process
    import brain_daemon
    brain_daemon.main()

def stop_daemon():
    """Stop via launchctl unload (macOS)."""
    from sidequests.cli.launchd import unload_plist, is_loaded
    if is_loaded():
        unload_plist()
        print("Brain Daemon stopped.")
    else:
        print("Brain Daemon is not running.")
```

### Files to Modify

#### `requirements.txt`
Add: `click>=8.1`

### Acceptance Criteria
- [ ] `python -m sidequests.cli.main setup` detects Claude Code and registers it
- [ ] `python -m sidequests.cli.main setup --target codex` registers Codex adapter
- [ ] Running setup twice is safe (idempotent)
- [ ] `sidequests status` reports pass/fail for socket + tools/list + schema
- [ ] Plist is written and loadable via `launchctl`

### Tests to Write: `tests/test_cli_setup.py`
- `test_detect_claude_code_when_installed` — monkeypatch `shutil.which` to return a path
- `test_detect_claude_code_when_missing` — monkeypatch to return None
- `test_write_plist_creates_valid_plist` — write to tmp_path, parse with `plistlib.load`
- `test_setup_idempotent` — run `run_setup` twice, verify no duplicate entries
- `test_smoke_test_reports_offline` — monkeypatch socket to not exist
- `test_mcp_json_merges_with_existing` — pre-populate `.mcp.json` with another server, verify it's preserved

---

## B2 — `.mcpb` Bundle (One-Click Claude Desktop Install)

**Goal:** Package as a Desktop Extension for non-technical Claude Desktop users.

**Dependency:** B1 (launchd plist generation), B4 (pyproject.toml for version info)

### Files to Create

#### `mcpb/manifest.json`
```json
{
  "name": "sidequests-brain",
  "version": "0.1.0",
  "description": "Persistent AI memory with a Gated Consolidation Loop and graph-native knowledge base.",
  "author": "SideQuests",
  "license": "UNLICENSED",
  "entry_point": {
    "command": "python",
    "args": ["adapters/claude_desktop/adapter.py"]
  },
  "permissions": ["filesystem_read", "filesystem_write"],
  "lifecycle": {
    "install": "mcpb/install.sh",
    "uninstall": "mcpb/uninstall.sh"
  }
}
```

#### `mcpb/install.sh`
```bash
#!/bin/bash
set -e
# 1. Install Python deps
pip install -r requirements.txt
python -m spacy download en_core_web_md

# 2. Write + load launchd plist (calls B1 code)
python -c "from sidequests.cli.launchd import write_plist, load_plist; write_plist(); load_plist()"

# 3. Smoke test
python -c "from sidequests.cli.smoke_test import check_status; check_status()"
```

#### `mcpb/uninstall.sh`
```bash
#!/bin/bash
# 1. Unload daemon
python -c "from sidequests.cli.launchd import unload_plist; unload_plist()" 2>/dev/null || true

# 2. Remove plist
rm -f ~/Library/LaunchAgents/ai.sidequests.brain.plist

# 3. Optionally remove data (prompt user? or leave it?)
echo "Brain Daemon stopped. Data preserved at ~/.sidequests/"
```

#### `Makefile` addition
```makefile
.PHONY: mcpb
mcpb: ## Build .mcpb bundle for Claude Desktop
	@echo "Building .mcpb bundle..."
	cd $(CURDIR) && zip -r sidequests-brain.mcpb \
		mcpb/manifest.json \
		mcpb/install.sh \
		mcpb/uninstall.sh \
		adapters/ \
		mcp_engine/ \
		web/ \
		brain_daemon.py \
		sidequests/ \
		requirements.txt \
		sidequests.toml \
		InvertorsDocs/GistSeedExamples.md \
		-x '*.pyc' '__pycache__/*' '.git/*' 'tests/*' '*.db'
	@echo "Built: sidequests-brain.mcpb"
```

### Notes
- The `.mcpb` spec is from Anthropic's Desktop Extensions. At build time, verify the spec hasn't changed — check the `@anthropic-ai/mcpb` npm package docs.
- The bundle's `entry_point` is the **adapter**, not the daemon. The daemon is started by `install.sh` via launchd.
- If the `.mcpb` spec requires a `smithery.yaml` or different manifest format, adapt accordingly.

### Acceptance Criteria
- [ ] `make mcpb` produces `sidequests-brain.mcpb` (valid ZIP)
- [ ] `manifest.json` passes `mcpb validate` if available
- [ ] `install.sh` starts daemon and adapter smoke test passes
- [ ] `uninstall.sh` stops daemon cleanly

---

## B3 — ChatGPT Desktop SSE Endpoint

**Goal:** Add MCP-over-SSE transport to the FastAPI web server so ChatGPT Desktop can connect as a Connector.

**Dependency:** None (web server already exists at `web/server.py`)

### Files to Modify

#### `web/server.py`
Add an SSE endpoint that implements the MCP SSE transport spec.

```python
# Add to imports:
from starlette.responses import StreamingResponse
import asyncio
import json
import uuid

# Add to create_app(db):

@app.get("/sse")
async def mcp_sse(request: Request):
    """
    MCP-over-SSE transport for ChatGPT Desktop.

    Protocol (MCP SSE spec):
    1. Client connects to GET /sse
    2. Server sends `event: endpoint\ndata: /mcp\n\n` to tell client where to POST
    3. Client POSTs JSON-RPC requests to /mcp
    4. Server streams responses back via SSE on the open connection

    Implementation:
    - Create an asyncio.Queue per connection
    - Store queue in a connection registry keyed by connection_id
    - /mcp endpoint looks up the queue and puts responses into it
    - SSE generator reads from queue and yields SSE events
    """
    connection_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    _sse_connections[connection_id] = queue

    async def event_generator():
        try:
            # First event: tell client where to POST
            yield f"event: endpoint\ndata: /mcp?connection_id={connection_id}\n\n"

            while True:
                # Wait for responses from /mcp handler
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: message\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            _sse_connections.pop(connection_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.post("/mcp")
async def mcp_post(request: Request):
    """
    Receive JSON-RPC from SSE client, dispatch to Brain, push response to SSE stream.
    """
    connection_id = request.query_params.get("connection_id", "")
    queue = _sse_connections.get(connection_id)
    if not queue:
        return JSONResponse({"error": "No active SSE connection"}, status_code=400)

    body = await request.json()

    # Dispatch to tool handlers (same as IPC dispatch in brain_daemon.py)
    response = await _dispatch_mcp(body, db)

    # Push response to SSE stream
    if response is not None:
        await queue.put(response)

    return JSONResponse({"status": "ok"})

# Module-level connection registry
_sse_connections: dict[str, asyncio.Queue] = {}

async def _dispatch_mcp(request: dict, db) -> dict:
    """
    Dispatch MCP JSON-RPC — same routing as brain_daemon.py._dispatch().

    Re-use the TOOL_HANDLERS dict from mcp_engine/tools.py.
    Handle initialize, tools/list, tools/call, notifications/initialized.
    """
    from mcp_engine.tools import TOOL_HANDLERS
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sidequests-brain-sse", "version": "0.1.0"},
        }}

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        # Return same TOOLS list as adapters
        from adapters.claude_code.adapter import TOOLS
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        try:
            # SSE runs in-process — call handler directly (no socket hop)
            result = await handler(tool_args, db, _config)
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(result)}]
            }}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}}

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}}
```

**Critical:** The SSE endpoint runs **inside the Brain Daemon process** (same FastAPI app). It calls `TOOL_HANDLERS` directly — no Unix socket hop needed. This means it needs access to `db` and `config` from `create_app()`.

Modify `create_app(db)` signature to `create_app(db, config)` — thread config through so the SSE dispatch can use it.

### Requirements
Add `sse-starlette>=2.0` to `requirements.txt` (or use raw Starlette `StreamingResponse` as shown above — no extra dep needed).

### Acceptance Criteria
- [ ] `GET http://127.0.0.1:7799/sse` opens SSE stream
- [ ] First event is `event: endpoint` with POST URL
- [ ] `POST /mcp` with `tools/list` returns tool list via SSE
- [ ] `POST /mcp` with `notify_turn` returns `{"status": "queued"}` via SSE
- [ ] Connection cleanup on client disconnect (no memory leak)
- [ ] Keepalive every 30s prevents proxy/firewall timeout

### Tests to Write: `tests/test_sse.py`
- `test_sse_endpoint_sends_endpoint_event` — use `httpx` async client
- `test_mcp_post_dispatches_tools_list` — POST to `/mcp`, check SSE stream
- `test_sse_connection_cleanup_on_disconnect`
- `test_mcp_post_without_connection_returns_400`

---

## B4 — Publish to PyPI

**Goal:** `pip install sidequests-brain` and `uvx sidequests-brain setup` work.

**Dependency:** B1 (CLI entry point)

### Files to Create

#### `pyproject.toml`
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sidequests-brain"
version = "0.1.0"
description = "Persistent AI memory with a Gated Consolidation Loop and graph-native Kuzu knowledge base"
readme = "README.md"
license = "UNLICENSED"
requires-python = ">=3.11"
authors = [
    { name = "SideQuests" }
]
keywords = ["ai", "memory", "mcp", "knowledge-graph", "kuzu"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

dependencies = [
    "kuzu==0.11.3",
    "sentence-transformers>=3.3,<4",
    "spacy>=3.8,<4",
    "openai>=1.50,<2",
    "fastapi>=0.115,<1",
    "uvicorn>=0.32,<1",
    "click>=8.1,<9",
    "tomli>=2.0; python_version < '3.11'",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[project.scripts]
sidequests = "sidequests.cli.main:cli"

[project.urls]
Homepage = "https://github.com/yourusername/sidequests-brain"
Issues = "https://github.com/yourusername/sidequests-brain/issues"

[tool.hatch.build.targets.wheel]
packages = ["sidequests", "mcp_engine", "adapters", "web"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

#### `sidequests/__init__.py`
```python
"""SideQuests Brain Daemon — Persistent AI memory."""
__version__ = "0.1.0"
```

### Files to Modify

#### Directory restructure consideration
The CLI code lives in `sidequests/cli/` (B1). The existing `mcp_engine/`, `adapters/`, `web/` modules need to be importable from the installed package. The `[tool.hatch.build.targets.wheel] packages` setting includes all four top-level packages.

Verify that `brain_daemon.py` can be found by the launchd plist — it should reference `python -m sidequests.daemon` or similar. **Option:** Move `brain_daemon.py` to `sidequests/daemon.py` and add:
```toml
[project.scripts]
sidequests = "sidequests.cli.main:cli"
sidequests-daemon = "sidequests.daemon:main"
```

Or keep `brain_daemon.py` at root and have the plist reference the installed script. Simpler to move it.

### Build & Test
```bash
# Local install
pip install -e ".[dev]"

# Test entry point
sidequests --help
sidequests setup --target claude-code

# Build distribution
pip install build
python -m build
# Produces dist/sidequests_brain-0.1.0-py3-none-any.whl

# Test with uvx (requires uv)
uvx sidequests-brain setup
```

### Acceptance Criteria
- [ ] `pip install -e .` installs all deps and makes `sidequests` CLI available
- [ ] `sidequests --help` shows setup/start/stop/status commands
- [ ] `python -m build` produces valid wheel
- [ ] `uvx sidequests-brain setup` works from a clean venv

### Notes
- **Do NOT publish to PyPI until provisional patent is filed** (IP protection constraint from CLAUDE.md)
- The `UNLICENSED` license placeholder should be updated before publishing
- `spacy` model download (`en_core_web_md`) is a post-install step — add to `sidequests setup` or document clearly
- Consider a `[project.scripts]` entry for `sidequests-daemon` that runs the Brain Daemon directly

---

## B5 — Smithery Listing

**Goal:** List on Smithery for discoverability: `npx @smithery/cli install sidequests-brain --client claude`

**Dependency:** B4 (PyPI package must exist first)

### Files to Create

#### `smithery.yaml`
```yaml
# Smithery server definition
# https://smithery.ai/docs/server-definition

name: sidequests-brain
description: >
  Persistent AI memory with a Gated Consolidation Loop.
  Automatically captures decisions, constraints, and plans
  from your conversations into a graph-native knowledge base.
version: 0.1.0
author: SideQuests
license: UNLICENSED

install:
  pip: sidequests-brain
  post_install:
    - python -m spacy download en_core_web_md
    - sidequests setup

server:
  command: sidequests-daemon
  # Or: command: python
  # args: ["-m", "sidequests.daemon"]

tools:
  - name: notify_turn
    description: Forward conversation turns to the Brain for background memory processing
  - name: current_truth
    description: Retrieve relevant memory before answering architecture or past-decision questions
  - name: branch_quest
    description: Create a SideQuest for exploring tangents
  - name: diff_since
    description: Surface changes since a prior session
  - name: get_open_loops
    description: Return unresolved tentative knowledge nodes
  - name: analogical_search
    description: Search across historical projects for similar decisions
  - name: ingest_document
    description: Ingest a local file into the knowledge graph

clients:
  - claude-code
  - claude-desktop
  - codex
  - gemini-cli
```

### Submission Process
1. Verify `smithery.yaml` passes `npx @smithery/cli validate`
2. Submit to `smithery.ai` (requires GitHub account)
3. Test: `npx @smithery/cli install sidequests-brain --client claude`

### Acceptance Criteria
- [ ] `smithery.yaml` passes validation
- [ ] Listing appears on smithery.ai after submission
- [ ] `npx @smithery/cli install sidequests-brain --client claude` completes successfully

### Notes
- The smithery.yaml spec may have changed — check latest docs at build time
- Only submit after provisional patent is filed and B4 is published to PyPI

---

## B6 — Claude Desktop Adapter

**Goal:** Full MCP STDIO adapter for Claude Desktop. Nearly identical to Claude Code but with no hook system (GUI app — both user and assistant turns use `notify_turn`).

**Dependency:** None (can be built independently)

### Files to Modify

#### `adapters/claude_desktop/adapter.py`
**Copy `adapters/codex/adapter.py` verbatim**, then make these changes:

1. **Module docstring:** Update to reference Claude Desktop registration path
2. **`serverInfo.name`:** Change to `"sidequests-brain-desktop"`
3. **`SYSTEM_PROMPT_FRAGMENT`:** Same as codex adapter (both user and assistant turns use notify_turn)

That's it. The Codex adapter is already the correct template for "no hooks" adapters.

```python
"""
adapters/claude_desktop/adapter.py — Claude Desktop MCP STDIO Adapter

No hook system available (GUI app). Both user and assistant turns use notify_turn.
Otherwise identical to Claude Code adapter.

Registration: added to ~/Library/Application Support/Claude/claude_desktop_config.json by `sidequests setup`:
  {"mcpServers": {"sidequests-brain": {"command": "python", "args": ["/abs/path/adapter.py"]}}}
"""
# ... (copy codex/adapter.py, change serverInfo.name to "sidequests-brain-desktop")
```

### Diff from Codex adapter
Literally 3 lines:
1. Module docstring (registration instructions)
2. `serverInfo.name` → `"sidequests-brain-desktop"`
3. Optional: description tweaks in TOOLS list (not required)

### Acceptance Criteria
- [ ] `python adapters/claude_desktop/adapter.py` starts without error
- [ ] MCP `initialize` returns `serverInfo.name = "sidequests-brain-desktop"`
- [ ] `tools/list` returns all 7 tools
- [ ] `tools/call notify_turn` forwards to Brain Daemon (or queues offline)

---

## B7 — ChatGPT Desktop Adapter

**Goal:** Decide: if B3 (SSE endpoint) is built, this adapter may be unnecessary. If SSE handles it, delete the stub. If not, build a stdio adapter.

### Decision Tree

```
B3 built? ─── Yes ──→ Delete stub, update backlog.md:
                       "B7: eliminated — SSE endpoint (B3) handles ChatGPT Desktop"
             │
             No ───→ Copy codex/adapter.py with:
                       serverInfo.name = "sidequests-brain-chatgpt"
                       Registration docs for ChatGPT Desktop MCP config
```

### If Building the Adapter

#### `adapters/chatgpt_desktop/adapter.py`
Same pattern as B6 — copy `codex/adapter.py`, change `serverInfo.name` to `"sidequests-brain-chatgpt"`, update docstring with ChatGPT Desktop registration path.

ChatGPT Desktop MCP config location (check at build time):
- macOS: `~/Library/Application Support/com.openai.chat/mcp.json` (verify)
- The config format may differ from Claude Desktop — check OpenAI docs

### Acceptance Criteria
- [ ] Either: adapter works end-to-end with ChatGPT Desktop
- [ ] Or: B3 SSE endpoint tested with ChatGPT Desktop's Connector feature, stub deleted

---

## B8 — Gemini CLI Adapter

**Goal:** MCP STDIO adapter for Google's Gemini CLI.

**Dependency:** None

### Files to Modify

#### `adapters/gemini_cli/adapter.py`
Copy `adapters/codex/adapter.py`, change:
1. Module docstring — Gemini CLI registration path
2. `serverInfo.name` → `"sidequests-brain-gemini"`
3. Registration format (check Gemini CLI MCP docs at build time)

**Hook investigation:** Gemini CLI open-sourced MCP support mid-2025. Check if it supports hooks (like Claude Code's `UserPromptSubmit`). If yes, add hook support similar to Claude Code. If no, both user and assistant turns use `notify_turn` (same as Codex pattern).

Gemini CLI MCP config location (check at build time):
- Likely `~/.gemini/config.json` or similar
- May use `gemini mcp add` CLI command

### Acceptance Criteria
- [ ] `python adapters/gemini_cli/adapter.py` starts without error
- [ ] MCP `initialize` returns correct serverInfo
- [ ] `tools/list` returns all 7 tools
- [ ] If hooks available: hook registered + tested
- [ ] If no hooks: notify_turn handles both roles

---

## B9 — Adapter Integration Tests

**Goal:** Comprehensive test coverage for all adapters. The existing `tests/test_adapters.py` covers Claude Code basics only.

**Dependency:** B6, B7, B8 (adapters must exist to test them)

### Files to Modify

#### `tests/test_adapters.py`
Expand the existing file. Structure tests by adapter, using parametrize where patterns are identical.

```python
"""
Comprehensive adapter integration tests.

Tests cover:
  1. MCP lifecycle (initialize, tools/list, notifications/initialized)
  2. Tool dispatch (all 7 tools)
  3. Offline queue behavior
  4. Git context injection
  5. Daemon recovery (offline → online transition)

Each adapter is tested independently via its handle_mcp_request function.
"""

import asyncio
import json
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Adapter modules to test
# ---------------------------------------------------------------------------

ADAPTERS = [
    ("claude_code", "adapters.claude_code.adapter"),
    ("codex", "adapters.codex.adapter"),
    ("claude_desktop", "adapters.claude_desktop.adapter"),
    ("gemini_cli", "adapters.gemini_cli.adapter"),
    # chatgpt_desktop only if B7 builds it (not B3 SSE)
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=[a[1] for a in ADAPTERS], ids=[a[0] for a in ADAPTERS])
def adapter_module(request):
    """Import and return each adapter module."""
    import importlib
    return importlib.import_module(request.param)


@pytest.fixture
def patched_adapter(adapter_module, tmp_path, monkeypatch):
    """Patch OFFLINE_QUEUE to tmp_path and provide fake _call_brain."""
    monkeypatch.setattr(adapter_module, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    monkeypatch.setattr(adapter_module, "_daemon_online", True)
    return adapter_module


# ---------------------------------------------------------------------------
# 1. MCP Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize(adapter_module):
    response = await adapter_module.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in response["result"]["capabilities"]
    assert "sidequests-brain" in response["result"]["serverInfo"]["name"]


@pytest.mark.asyncio
async def test_tools_list_has_all_seven_tools(adapter_module):
    response = await adapter_module.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tool_names = {t["name"] for t in response["result"]["tools"]}
    expected = {"notify_turn", "current_truth", "branch_quest", "diff_since",
                "get_open_loops", "analogical_search", "ingest_document"}
    assert expected == tool_names


@pytest.mark.asyncio
async def test_notifications_initialized_returns_none(adapter_module):
    response = await adapter_module.handle_mcp_request({
        "jsonrpc": "2.0", "method": "notifications/initialized"
    })
    assert response is None


@pytest.mark.asyncio
async def test_unknown_method_returns_error(adapter_module):
    response = await adapter_module.handle_mcp_request({
        "jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}
    })
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# 2. Tool Dispatch — all 7 tools
# ---------------------------------------------------------------------------

TOOL_CALLS = [
    ("notify_turn", {"role": "user", "content": "test", "session_id": "s1"}),
    ("current_truth", {"query": "test", "session_id": "s1"}),
    ("branch_quest", {"name": "test", "purpose": "test"}),
    ("diff_since", {"since_iso": "2026-01-01T00:00:00Z"}),
    ("get_open_loops", {}),
    ("analogical_search", {"query": "test"}),
    ("ingest_document", {"file_path": "/tmp/test.md"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,tool_args", TOOL_CALLS,
                         ids=[t[0] for t in TOOL_CALLS])
async def test_tool_dispatch_calls_brain(patched_adapter, monkeypatch,
                                          tool_name, tool_args):
    """Each tool dispatches to _call_brain with git context injected."""
    called_with = {}
    async def fake_call_brain(method, params):
        called_with["method"] = method
        called_with["params"] = params
        return {"status": "ok"}
    monkeypatch.setattr(patched_adapter, "_call_brain", fake_call_brain)

    await patched_adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_args}
    })
    assert called_with["method"] == tool_name
    # Git context should be injected
    assert "repo_root" in called_with["params"]
    assert "git_branch" in called_with["params"]


# ---------------------------------------------------------------------------
# 3. Offline Queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_turn_queues_when_offline(patched_adapter, monkeypatch, tmp_path):
    async def fail_brain(method, params):
        raise RuntimeError("DAEMON_OFFLINE")
    monkeypatch.setattr(patched_adapter, "_call_brain", fail_brain)

    response = await patched_adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 20, "method": "tools/call",
        "params": {"name": "notify_turn",
                   "arguments": {"role": "user", "content": "x", "session_id": "s"}}
    })
    assert "queued_offline" in response["result"]["content"][0]["text"]
    assert (tmp_path / "offline.jsonl").exists()


@pytest.mark.asyncio
async def test_current_truth_returns_offline_fragment(patched_adapter, monkeypatch):
    async def fail_brain(method, params):
        raise RuntimeError("DAEMON_OFFLINE")
    monkeypatch.setattr(patched_adapter, "_call_brain", fail_brain)

    response = await patched_adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 21, "method": "tools/call",
        "params": {"name": "current_truth",
                   "arguments": {"query": "test", "session_id": "s"}}
    })
    assert "OFFLINE" in response["result"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# 4. Git Context Injection
# ---------------------------------------------------------------------------

def test_inject_git_context(adapter_module):
    result = adapter_module._inject_git_context({"foo": "bar"})
    assert "repo_root" in result
    assert "git_branch" in result
    assert result["foo"] == "bar"  # original params preserved


def test_detect_git_context_returns_strings(adapter_module):
    root, branch = adapter_module.detect_git_context()
    assert isinstance(root, str)
    assert isinstance(branch, str)


# ---------------------------------------------------------------------------
# 5. Unknown tool returns error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool_returns_error(patched_adapter, monkeypatch):
    async def fake_brain(method, params):
        return {"status": "ok"}
    monkeypatch.setattr(patched_adapter, "_call_brain", fake_brain)

    response = await patched_adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 30, "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}}
    })
    assert response["error"]["code"] == -32601
```

### Acceptance Criteria
- [ ] All 5 test categories pass for Claude Code adapter
- [ ] All 5 test categories pass for Codex adapter
- [ ] All 5 test categories pass for Claude Desktop adapter
- [ ] All 5 test categories pass for Gemini CLI adapter
- [ ] Parametrized tests ensure no adapter is accidentally missing tools

---

## B10 — `explore_graph` Tool (Directed Graph Traversal)

**Goal:** Let the LLM traverse the knowledge graph structurally instead of only via vector search. Complements `current_truth`.

**Dependency:** None

### Files to Modify

#### `mcp_engine/tools.py`
Add handler:

```python
# ---------------------------------------------------------------------------
# B10 — explore_graph
# ---------------------------------------------------------------------------

# Allowlisted relationship types (prevent arbitrary Cypher)
_TRAVERSABLE_RELS = frozenset({
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    "CO_OCCURS_WITH", "REIFIED_AS", "DEPRECATED_BY",
    "BELONGS_TO", "DERIVED_FROM", "ESTABLISHED",
    "HAS_PREF_LABEL", "HAS_ALT_LABEL",
    "PRODUCED_LESSON",  # B11
})

MAX_DEPTH = 3

async def explore_graph(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Directed graph traversal from a known node.

    params:
      start_node_id: str (required) — concept_id, decision_id, etc.
      relationship_type: str (optional) — filter to specific rel type
      direction: str (optional) — "outgoing" | "incoming" | "both", default "both"
      depth: int (optional) — 1-3, default 1

    Returns:
      {start_node_id, nodes: [{node_id, node_type, text_raw, ...}],
       edges: [{source, target, type, properties}]}

    Security:
      - Only traverses allowlisted relationship types
      - Depth capped at MAX_DEPTH (3)
      - Read-only operation
      - No arbitrary Cypher — builds query from validated params
    """
    start_id = params.get("start_node_id", "").strip()
    rel_type = params.get("relationship_type", "").strip().upper()
    direction = params.get("direction", "both")
    depth = min(int(params.get("depth", 1)), MAX_DEPTH)

    if not start_id:
        return {"error": "start_node_id is required"}

    if rel_type and rel_type not in _TRAVERSABLE_RELS:
        return {"error": f"Unknown relationship type: {rel_type}",
                "allowed": sorted(_TRAVERSABLE_RELS)}

    # Build Cypher query
    # Strategy: find the start node across all node tables,
    # then traverse outgoing/incoming edges up to depth.
    #
    # Use MATCH (a)-[r*1..{depth}]-(b) pattern for variable-length traversal.
    # Filter by rel_type if provided.
    # Collect distinct nodes and edges.

    # ... implementation builds safe parameterized Cypher ...

    return {
        "start_node_id": start_id,
        "nodes": [...],  # [{node_id, node_type, text_raw, confidence, pathway_strength}]
        "edges": [...],  # [{source, target, type, properties}]
    }
```

Add to `TOOL_HANDLERS`:
```python
TOOL_HANDLERS = {
    ...
    "explore_graph": explore_graph,
}
```

#### All adapter files (`adapters/*/adapter.py`)
Add the tool schema to the `TOOLS` list:

```python
{
    "name": "explore_graph",
    "description": (
        "Traverse the knowledge graph from a known node. Use when current_truth "
        "returns a relevant node and you want to see what it connects to. "
        "Returns neighboring nodes and edges up to 3 hops."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "start_node_id":    {"type": "string",
                                 "description": "ID of the node to start from."},
            "relationship_type": {"type": "string",
                                  "description": "Filter to specific edge type (e.g. REQUIRES)."},
            "direction":         {"type": "string",
                                  "enum": ["outgoing", "incoming", "both"],
                                  "default": "both"},
            "depth":             {"type": "integer", "default": 1,
                                  "description": "Traversal depth (1-3)."},
        },
        "required": ["start_node_id"],
    },
}
```

Also add `"explore_graph"` to the tool dispatch in each adapter's `handle_mcp_request` (or to the catch-all group like codex does).

### Cypher Implementation Notes

Finding the start node is the tricky part — the `start_node_id` could be in any node table. Options:

**Option A (recommended):** Try each table in order:
```python
NODE_TABLES = [
    ("Concept", "concept_id"),
    ("Decision", "decision_id"),
    ("Constraint", "constraint_id"),
    # ... etc
]
for table, pk in NODE_TABLES:
    r = db.execute(f"MATCH (n:{table} {{{pk}: $id}}) RETURN n", {"id": start_id})
    if r.has_next():
        # Found it
        break
```

**Option B:** Use a unified query with UNION ALL (Kuzu may not support this cleanly for variable-length paths).

For traversal, use Kuzu's `MATCH (a)-[r*1..N]-(b)` syntax for variable-length paths. Note: Kuzu 0.11.3 may have limitations on recursive/variable-length path queries — test and fall back to iterative single-hop queries if needed.

### Acceptance Criteria
- [ ] `explore_graph(start_node_id="<id>")` returns 1-hop neighbors
- [ ] `depth=2` returns 2-hop neighbors
- [ ] `relationship_type="REQUIRES"` filters edges
- [ ] `direction="outgoing"` only returns outgoing edges
- [ ] Unknown relationship type returns error with allowed list
- [ ] Depth > 3 is clamped to 3

### Tests to Write: `tests/test_explore_graph.py`
- `test_explore_returns_neighbors` — create nodes + edges in test DB, verify traversal
- `test_explore_filters_by_rel_type`
- `test_explore_respects_depth_cap`
- `test_explore_unknown_rel_type_returns_error`
- `test_explore_nonexistent_node_returns_empty`
- `test_explore_direction_outgoing_only`

---

## B11 — `Lesson` Artifact Node

**Goal:** Synthesize lessons learned when quests complete. Feed analogical reasoning.

**Dependency:** None (but pairs with B10)

### Files to Modify

#### `mcp_engine/schema.py`
Add Lesson node table and relationship. Find the section where node tables are created and add:

```python
# Lesson node (B11) — synthesized at quest completion
conn.execute("""
    CREATE NODE TABLE IF NOT EXISTS Lesson (
        lesson_id        STRING PRIMARY KEY,
        text_raw         STRING,
        embedding        FLOAT[384],
        embedding_model  STRING,
        embedding_dim    INT16,
        obstacle_summary STRING,
        source_quest_id  STRING,
        confidence       FLOAT,
        confidence_low   BOOLEAN,
        pathway_strength FLOAT,
        archived         BOOLEAN,
        created_at       TIMESTAMP
    )
""")

# PRODUCED_LESSON relationship
conn.execute("""
    CREATE REL TABLE IF NOT EXISTS PRODUCED_LESSON (
        FROM MainQuest TO Lesson
    )
""")

# HNSW vector index
conn.execute("""
    CALL CREATE_VECTOR_INDEX('Lesson', 'embedding', 'lesson_emb_idx')
""")
```

#### `mcp_engine/tools.py`
Modify `complete_quest` handler (if it exists — if not, create it). After marking the quest as completed, trigger lesson synthesis:

```python
async def complete_quest(params: dict, db: KuzuClient, config: dict) -> dict:
    """Mark quest as completed and synthesize a Lesson."""
    quest_id = params.get("quest_id", "").strip()
    if not quest_id:
        return {"error": "quest_id is required"}

    now = datetime.now(timezone.utc).isoformat()

    # Mark quest completed
    await db.execute_write(
        """MATCH (q:MainQuest {quest_id: $qid})
           SET q.status = 'completed', q.completed_at = $now""",
        {"qid": quest_id, "now": now}
    )

    # B11: Synthesize lesson in background (fire-and-forget)
    if _loop_queue is not None:
        asyncio.create_task(_synthesize_lesson(quest_id, db, config))

    return {"status": "completed", "quest_id": quest_id}


async def _synthesize_lesson(quest_id: str, db: KuzuClient, config: dict):
    """
    Synthesize a Lesson from quest artifacts.

    1. Query top 10 confirmed artifacts (Decision, Constraint, Requirement)
       linked to this quest (via Message → Session → Quest chain)
    2. Query top 5 messages with highest pathway_strength
    3. Send to LLM: "Given these decisions and constraints from project X,
       what was the hardest obstacle overcome and the key lesson learned?"
    4. Store as Lesson node with confidence_low=true
    5. Link via PRODUCED_LESSON
    """
    from mcp_engine.llm.provider import create_llm_client
    from mcp_engine.graph import embeddings as emb

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Gather quest artifacts
    # ... query confirmed artifacts linked to quest_id ...

    # Synthesize via LLM
    llm = create_llm_client(config)
    if llm is None:
        _logger.warning("LLM unavailable — skipping lesson synthesis for %s", quest_id)
        return

    prompt = f"""Given these artifacts from a completed project quest:

{artifacts_text}

Synthesize in 1-2 sentences:
1. The hardest obstacle overcome
2. The key lesson learned that would help someone doing similar work

Return JSON: {{"lesson": "...", "obstacle": "..."}}"""

    response = await asyncio.to_thread(llm.chat, prompt)
    # Parse response, embed, store Lesson node, link PRODUCED_LESSON
```

#### `mcp_engine/analogical.py`
Add `Lesson` to the cross-quest search tables:

```python
CROSS_QUEST_TABLES = [
    ("Decision",    "decision_emb_idx",    "decision_id"),
    ("Constraint",  "constraint_emb_idx",  "constraint_id"),
    ("Requirement", "requirement_emb_idx", "requirement_id"),
    ("Lesson",      "lesson_emb_idx",      "lesson_id"),  # B11
]
```

#### `web/server.py`
Surface Lessons in the quests API endpoint:

```python
# In the /api/quests endpoint, add lesson lookup per quest:
# MATCH (q:MainQuest)-[:PRODUCED_LESSON]->(l:Lesson) ...
```

#### All adapter files (`adapters/*/adapter.py`)
Add `complete_quest` to `TOOLS` list if not already present:

```python
{
    "name": "complete_quest",
    "description": (
        "Mark a Quest as completed. Triggers lesson synthesis. "
        "Completed quests feed cross-project analogical reasoning."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "quest_id": {"type": "string"},
        },
        "required": ["quest_id"],
    },
}
```

Add `"complete_quest"` to the tool dispatch and to `TOOL_HANDLERS`.

### Acceptance Criteria
- [ ] `Lesson` table created by schema init
- [ ] `complete_quest` triggers lesson synthesis
- [ ] Lesson stored with `confidence_low=true`
- [ ] `PRODUCED_LESSON` edge links quest to lesson
- [ ] `analogical_search` includes lessons in results
- [ ] Lesson visible in Memory Control Panel quests view

### Tests to Write: `tests/test_lesson.py`
- `test_lesson_schema_creates_table` — schema init includes Lesson
- `test_complete_quest_creates_lesson` — mock LLM, verify Lesson node created
- `test_lesson_included_in_analogical_search` — embed a lesson, search for similar query
- `test_lesson_synthesis_skips_when_llm_unavailable` — no crash, warning logged
- `test_lesson_confidence_low_by_default`

---

## B12 — Memory-Based Anomaly Detection (IP Formalization)

**Goal:** No code changes. Document the existing Contradiction sense + GlobalConstraint mechanism as a named security principle for patent purposes.

**Dependency:** None

### What Already Exists (No Code Needed)
The Brain Daemon is **out-of-band** — a separate process that cannot be hijacked by prompt injection. The Step 4 Contradiction sense already fires when `notify_turn` content conflicts with a high-confidence GlobalConstraint. This is mechanically a security monitoring system.

### Documentation Actions

#### 1. `InvertorsDocs/` — Update Inventor's Notebook
Add a new section (or update the existing canvas):

**Section 5.5.D — Out-of-Band Behavioral Integrity Monitoring**
```
Named Principle: Out-of-Band Behavioral Integrity Monitoring

The Brain Daemon operates as a separate process from any LLM session.
It receives conversation content via notify_turn (fire-and-forget) and
processes it through the Gated Consolidation Loop independently.

Security properties:
1. Architectural isolation: Brain cannot be prompt-injected through the
   LLM's context window — it's a different process with its own logic.
2. GlobalConstraints as policy baseline: Decay rate 0.999/day means
   security constraints are effectively permanent (~2 years to half-strength).
3. Contradiction sense fires automatically: When notify_turn content
   conflicts with a high-confidence GlobalConstraint, Step 4 flags it.

Scope (important for patent claim precision):
- Conversation-layer only — detects constraint override language in conversation
- Does NOT detect OS-level actions (filesystem, network, subprocess)
- Detects: prompt injection attempts, goal hijacking, constraint violations

Distinct from Cocktail Party Effect:
- Cocktail Party Effect = selective attention for memory formation
- Anomaly Detection = same mechanism applied to security monitoring
- Both use Step 4 confidence gate, but the signal interpretation differs
```

**Add Claim #7 to Section 5.7 — Novelty:**
```
Claim 7: Out-of-Band Behavioral Integrity Monitoring via Contradiction Detection

An AI memory system operating as a separate process from the LLM session,
where high-confidence policy constraints (GlobalConstraint nodes with
pathway_strength decay rate ≥ 0.999) serve as a security baseline, and
the Contradiction sense (Step 4, Gated Consolidation Loop) automatically
flags conversational content that conflicts with established constraints,
providing prompt injection and goal hijacking detection without requiring
explicit security rules or a separate monitoring system.
```

#### 2. Update CLAUDE.md (Optional)
Add a brief mention in the Cocktail Party Effect sensory table:

| Sense | Fires On |
|-------|---------|
| ... existing ... | ... |
| Anomaly / Security sense | Content contradicts a high-confidence GlobalConstraint (pathway_strength > 0.8) |

#### 3. Future Code (Not B12 Scope)
- Configurable alert threshold in `sidequests.toml`: `[security] anomaly_threshold = 0.8`
- Memory Control Panel: dedicated "Anomalies" tab showing flagged contradictions
- Webhook/notification when anomaly detected (e.g., desktop notification)

### Acceptance Criteria
- [ ] Inventor's Notebook updated with Section 5.5.D
- [ ] Claim #7 added to Section 5.7
- [ ] Patent attorney flagged on distinct claim from Cocktail Party Effect
- [ ] No code changes required — this is documentation/IP only

---

## Execution Checklist

| Item | Deps | Est. Scope | Files Changed |
|------|------|-----------|---------------|
| **B1** | None | Large | 6 new files in `sidequests/cli/`, modify `requirements.txt` |
| **B4** | B1 | Medium | `pyproject.toml`, `sidequests/__init__.py`, possibly move `brain_daemon.py` |
| **B6** | None | Small | 1 file: `adapters/claude_desktop/adapter.py` (copy of codex) |
| **B8** | None | Small | 1 file: `adapters/gemini_cli/adapter.py` (copy of codex) |
| **B9** | B6, B8 | Medium | Expand `tests/test_adapters.py` |
| **B3** | None | Medium | Modify `web/server.py`, new `tests/test_sse.py` |
| **B7** | B3 | Tiny | Delete stub or copy codex (depends on B3 outcome) |
| **B2** | B1, B4 | Small | 3 new files in `mcpb/`, `Makefile` |
| **B5** | B4 | Small | `smithery.yaml` |
| **B10** | None | Medium | Modify `mcp_engine/tools.py`, all adapters, new test file |
| **B11** | None | Medium | Modify `schema.py`, `tools.py`, `analogical.py`, `web/server.py`, all adapters, new test file |
| **B12** | None | Small | Documentation only (`InvertorsDocs/`) |

### Order of Operations
```
B1 (setup CLI) ──→ B4 (pyproject.toml) ──→ B2 (mcpb bundle)
                                         ──→ B5 (smithery)

B6 (claude desktop adapter) ─┐
B8 (gemini cli adapter) ─────┤──→ B9 (adapter tests)
                              │
B3 (SSE endpoint) ───────────┤──→ B7 (chatgpt decision)

B10 (explore_graph) ─── independent
B11 (lesson node) ────── independent
B12 (IP docs) ────────── independent, do anytime
```

Items on the same line can be parallelized. B12 can be done at any time since it's documentation only.
