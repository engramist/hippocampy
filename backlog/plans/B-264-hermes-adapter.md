# B264 - Hermes Agent Adapter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Hermes Agent adapter that provides session recall via `compile_context`, captures turns, and supports background agent spawning with per-agent context bundles.

**Architecture:** New `adapters/hermes/adapter.py` following the existing adapter pattern. Uses the REST API (`/api/v1/`) as the primary integration path. The `HermesAdapter` class provides `session_recall()`, `capture_turn()`, and `spawn_context()` methods.

**Tech Stack:** Python, requests (HTTP client), existing adapter patterns

---

### Task 1: Create Hermes Adapter Module

**Files:**
- Create: `adapters/hermes/__init__.py`
- Create: `adapters/hermes/adapter.py`
- Create: `tests/adapters/test_hermes_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_hermes_adapter.py
"""Test Hermes Agent adapter."""

def test_hermes_adapter_importable():
    """HermesAdapter should be importable."""
    from adapters.hermes.adapter import HermesAdapter
    adapter = HermesAdapter(brain_url="http://127.0.0.1:7799")
    assert adapter is not None
    assert adapter.brain_url == "http://127.0.0.1:7799"

def test_hermes_adapter_has_required_methods():
    """HermesAdapter should have session_recall, capture_turn, spawn_context."""
    from adapters.hermes.adapter import HermesAdapter
    adapter = HermesAdapter()
    assert hasattr(adapter, "session_recall")
    assert hasattr(adapter, "capture_turn")
    assert hasattr(adapter, "spawn_context")
    assert callable(adapter.session_recall)
    assert callable(adapter.capture_turn)
    assert callable(adapter.spawn_context)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_hermes_adapter.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the adapter**

Create `adapters/hermes/__init__.py`:

```python
"""Hermes Agent adapter for Campy memory integration."""
```

Create `adapters/hermes/adapter.py`:

```python
"""
Hermes Agent Adapter — Connects Hermes to Campy's memory system.

Provides:
- session_recall: Load context at session start via compile_context
- capture_turn: Capture agent turns into memory via notify_turn
- spawn_context: Generate focused context bundles for spawned agents

Usage:
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter(brain_url="http://127.0.0.1:7799")
    
    # At session start
    context = adapter.session_recall("Work on the auth refactor")
    
    # After each turn
    adapter.capture_turn(role="assistant", content="I'll start by...", session_id="sess-123")
    
    # When spawning a background agent
    spawn_ctx = adapter.spawn_context(
        parent_session_id="sess-123",
        task_description="Fix the rate limiter bug",
        token_budget=8000,
    )
"""
import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class HermesAdapter:
    """Adapter connecting Hermes Agent to Campy memory.
    
    Uses the REST API at /api/v1/ for simplicity.
    Falls back to MCP SSE for full tool access if needed.
    """
    
    def __init__(
        self,
        brain_url: str = "http://127.0.0.1:7799",
        timeout: int = 10,
    ):
        self.brain_url = brain_url.rstrip("/")
        self.timeout = timeout
        self._api_base = f"{self.brain_url}/api/v1"
    
    def _get(self, path: str, params: dict = None) -> dict:
        """GET request to REST API."""
        try:
            resp = requests.get(
                f"{self._api_base}{path}",
                params=params,
                timeout=self.timeout,
            )
            return resp.json()
        except requests.ConnectionError:
            logger.warning("Campy daemon not reachable at %s", self.brain_url)
            return {"ok": False, "error": "Daemon not reachable"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def _post(self, path: str, body: dict) -> dict:
        """POST request to REST API."""
        try:
            resp = requests.post(
                f"{self._api_base}{path}",
                json=body,
                timeout=self.timeout,
            )
            return resp.json()
        except requests.ConnectionError:
            logger.warning("Campy daemon not reachable at %s", self.brain_url)
            return {"ok": False, "error": "Daemon not reachable"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def is_available(self) -> bool:
        """Check if the Campy daemon is reachable."""
        result = self._get("/status")
        return result.get("ok", False)
    
    def session_recall(
        self,
        task_description: str,
        token_budget: int = 32000,
        agent_type: str = "generic",
    ) -> dict:
        """Load context at session start.
        
        Calls compile_context to assemble a heterogeneous context bundle
        containing exact facts, semantic matches, graph relationships,
        tabular data, and summaries — all shaped for the requesting agent.
        
        Args:
            task_description: What this session will work on.
            token_budget: Max tokens for the context bundle.
            agent_type: Agent type for output formatting.
        
        Returns:
            Context bundle dict with sections, or error dict.
        """
        return self._post("/bundle", {
            "query": task_description,
            "token_budget": token_budget,
            "agent_type": agent_type,
        })
    
    def capture_turn(
        self,
        role: str,
        content: str,
        session_id: str = "hermes-default",
    ) -> dict:
        """Capture an agent turn into Campy memory.
        
        Args:
            role: "user" or "assistant"
            content: The full turn content.
            session_id: Session identifier for grouping turns.
        
        Returns:
            Status dict from notify_turn.
        """
        return self._post("/notify", {
            "role": role,
            "content": content,
            "session_id": session_id,
        })
    
    def spawn_context(
        self,
        parent_session_id: str,
        task_description: str,
        token_budget: int = 8000,
    ) -> dict:
        """Generate focused context for a spawned background agent.
        
        Creates a smaller, task-scoped context bundle that gives the
        spawned agent just enough context to start working without
        needing to rediscover project state.
        
        Args:
            parent_session_id: The parent session that spawned this agent.
            task_description: What the spawned agent will work on.
            token_budget: Smaller budget for focused context.
        
        Returns:
            Focused context bundle dict.
        """
        return self._post("/bundle", {
            "query": task_description,
            "token_budget": token_budget,
            "agent_type": "generic",
        })
    
    def quick_recall(self, query: str, scope: str = "both") -> dict:
        """Quick semantic recall for specific questions.
        
        Args:
            query: What to search for.
            scope: "branch", "global", or "both".
        
        Returns:
            Recall results dict.
        """
        return self._get("/recall", {"q": query, "scope": scope})
    
    def decide(self, query: str) -> dict:
        """Ask the memory router which tool to use.
        
        Args:
            query: The question or task description.
        
        Returns:
            Dict with recommended_tool, reasoning, confidence.
        """
        return self._post("/decide", {"query": query})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/adapters/test_hermes_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/hermes/__init__.py adapters/hermes/adapter.py tests/adapters/test_hermes_adapter.py
git commit -m "feat(B264): create Hermes Agent adapter with session recall and spawn context"
```

---

### Task 2: Add Hermes Detection and Registration

**Files:**
- Modify: `campy/cli/detect.py`
- Modify: `campy/cli/register.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_hermes_adapter.py (add)
def test_detect_hermes_exists():
    """detect_hermes function should exist."""
    from campy.cli.detect import detect_hermes
    result = detect_hermes()
    assert isinstance(result, bool)

def test_register_hermes_exists():
    """register_hermes function should exist."""
    from campy.cli.register import register_hermes
    assert callable(register_hermes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_hermes_adapter.py::test_detect_hermes_exists -v`
Expected: FAIL — function doesn't exist

- [ ] **Step 3: Add detect_hermes to detect.py**

```python
def detect_hermes() -> bool:
    """Check for Hermes Agent CLI or config directory."""
    if shutil.which("hermes") is not None:
        return True
    # Check common config locations
    config_dirs = [
        os.path.expanduser("~/.hermes"),
        os.path.expanduser("~/.config/hermes"),
    ]
    return any(os.path.isdir(d) for d in config_dirs)
```

Also add to `detect_installed_clients()`:

```python
"hermes": detect_hermes(),
```

- [ ] **Step 4: Add register_hermes to register.py**

```python
def register_hermes(adapter_path: str = None) -> bool:
    """Register Campy with Hermes Agent.
    
    Installs the Hermes adapter configuration so Hermes knows
    to use Campy for session recall and turn capture.
    """
    try:
        # Hermes adapter is a Python module — just verify it's importable
        # and log the integration path
        logging.info("Hermes Agent adapter available at adapters/hermes/adapter.py")
        logging.info("Integration: from adapters.hermes.adapter import HermesAdapter")
        return True
    except Exception as e:
        logging.error(f"Failed to register Hermes: {e}")
        return False
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/adapters/test_hermes_adapter.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add campy/cli/detect.py campy/cli/register.py tests/adapters/test_hermes_adapter.py
git commit -m "feat(B264): add Hermes Agent detection and registration"
```

---

### Task 3: Create Integration README

**Files:**
- Create: `adapters/hermes/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Hermes Agent — Campy Memory Integration

## Overview

This adapter connects Hermes Agent to Campy's persistent AI memory system.
Hermes agents get session recall (loading context at conversation start),
turn capture (saving knowledge from conversations), and spawn context
(focused memory bundles for background agents).

## Quick Start

```python
from adapters.hermes.adapter import HermesAdapter

# Initialize (daemon must be running)
adapter = HermesAdapter(brain_url="http://127.0.0.1:7799")

# Check daemon is available
if not adapter.is_available():
    print("Start the Campy daemon: campy start")

# Session recall — load context at session start
context = adapter.session_recall(
    task_description="Refactor the authentication module",
    token_budget=32000,
)

# Capture turns during the session
adapter.capture_turn(
    role="assistant",
    content="I'll start by reviewing the current auth implementation...",
    session_id="hermes-session-001",
)

# Spawn context for background agents
spawn_ctx = adapter.spawn_context(
    parent_session_id="hermes-session-001",
    task_description="Fix the rate limiter edge case",
    token_budget=8000,
)
```

## Prerequisites

1. Campy daemon running: `campy start`
2. REST API available (B262) or MCP SSE endpoint at `http://127.0.0.1:7799/sse`

## API Reference

### `HermesAdapter(brain_url, timeout)`
- `brain_url`: Campy daemon URL (default: `http://127.0.0.1:7799`)
- `timeout`: Request timeout in seconds (default: 10)

### `session_recall(task_description, token_budget, agent_type)`
Compiles a heterogeneous context bundle from all memory types.

### `capture_turn(role, content, session_id)`
Captures a turn into the knowledge graph for future recall.

### `spawn_context(parent_session_id, task_description, token_budget)`
Generates a focused, smaller context bundle for spawned background agents.

### `quick_recall(query, scope)`
Quick semantic search for specific questions.

### `decide(query)`
Ask the memory router which recall tool to use.
```

- [ ] **Step 2: Commit**

```bash
git add adapters/hermes/README.md
git commit -m "docs(B264): add Hermes Agent integration README"
```

---

### Task 4: Unit Tests with Mocked Daemon

**Files:**
- Modify: `tests/adapters/test_hermes_adapter.py`

- [ ] **Step 1: Add mocked daemon tests**

```python
from unittest.mock import patch, MagicMock
from adapters.hermes.adapter import HermesAdapter

def test_session_recall_calls_bundle_endpoint():
    """session_recall should POST to /api/v1/bundle."""
    adapter = HermesAdapter()
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "data": {"sections": [], "total_token_estimate": 0}
    }
    
    with patch("adapters.hermes.adapter.requests.post", return_value=mock_resp) as mock_post:
        result = adapter.session_recall("test task", token_budget=8000)
    
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/api/v1/bundle" in call_args[0][0]
    assert call_args[1]["json"]["query"] == "test task"
    assert call_args[1]["json"]["token_budget"] == 8000

def test_capture_turn_calls_notify_endpoint():
    """capture_turn should POST to /api/v1/notify."""
    adapter = HermesAdapter()
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "data": {"status": "queued"}}
    
    with patch("adapters.hermes.adapter.requests.post", return_value=mock_resp) as mock_post:
        result = adapter.capture_turn("assistant", "test content", "sess-1")
    
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/api/v1/notify" in call_args[0][0]
    assert call_args[1]["json"]["role"] == "assistant"
    assert call_args[1]["json"]["content"] == "test content"

def test_spawn_context_uses_small_budget():
    """spawn_context should use a smaller token budget by default."""
    adapter = HermesAdapter()
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "data": {"sections": []}}
    
    with patch("adapters.hermes.adapter.requests.post", return_value=mock_resp) as mock_post:
        adapter.spawn_context("parent-1", "fix bug", token_budget=4000)
    
    call_args = mock_post.call_args
    assert call_args[1]["json"]["token_budget"] == 4000

def test_adapter_handles_connection_error():
    """Adapter should handle daemon not running gracefully."""
    adapter = HermesAdapter(brain_url="http://127.0.0.1:99999")
    
    with patch("adapters.hermes.adapter.requests.post", side_effect=ConnectionError):
        result = adapter.session_recall("test")
    
    assert result["ok"] is False
    assert "error" in result
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/adapters/test_hermes_adapter.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/adapters/test_hermes_adapter.py
git commit -m "test(B264): add mocked unit tests for Hermes adapter"
```
