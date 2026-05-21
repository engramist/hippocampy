# B261 - CLI Recall Commands

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 CLI commands (`campy recall`, `campy bundle`, `campy timeline`, `campy diff`, `campy decide`, `campy context`) that query the MCP daemon and format output for terminal display.

**Architecture:** New `campy/cli/recall.py` module with a Typer app. Each command sends a JSON-RPC request to the daemon at `http://127.0.0.1:7799` using the existing `_send()` helper pattern from `campy/cli/smoke_test.py`. Rich-formatted output by default, `--json` for raw, `--format=prompt` for hook injection.

**Tech Stack:** Python, Typer, Rich, requests/httpx

---

### Task 1: Create Recall CLI Module with `campy recall`

**Files:**
- Create: `campy/cli/recall.py`
- Create: `tests/cli/test_recall_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_recall_cli.py
import subprocess
import sys

def test_recall_command_exists():
    """campy recall --help should work."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "recall", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "query" in result.stdout.lower() or "recall" in result.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_recall_cli.py::test_recall_command_exists -v`
Expected: FAIL — `recall` command doesn't exist

- [ ] **Step 3: Create recall.py with the `recall` command**

```python
# campy/cli/recall.py
"""CLI recall commands — query Campy memory from the terminal."""
import json
import sys
from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

console = Console()

# Reuse the daemon communication pattern from smoke_test
DAEMON_URL = "http://127.0.0.1:7799"


def _send(method: str, params: dict = None) -> dict:
    """Send MCP JSON-RPC request to daemon."""
    import requests
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params
    try:
        resp = requests.post(f"{DAEMON_URL}/mcp", json=payload, timeout=10)
        return resp.json()
    except requests.ConnectionError:
        return {"error": {"message": "Daemon not running. Start with: campy start"}}
    except Exception as e:
        return {"error": {"message": str(e)}}


def _call_tool(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via the daemon."""
    return _send("tools/call", {"name": tool_name, "arguments": arguments})


def _format_result(result: dict, format_type: str) -> str:
    """Format tool result based on output format."""
    if format_type == "json":
        return json.dumps(result, indent=2)
    elif format_type == "prompt":
        # Bare text for hook injection
        content = result.get("result", result)
        if isinstance(content, dict):
            # Extract text content from various response shapes
            for key in ("text", "content", "summary", "markdown"):
                if key in content:
                    return str(content[key])
            return json.dumps(content)
        return str(content)
    else:
        return None  # Use Rich formatting


def _handle_error(result: dict) -> bool:
    """Print error and return True if result is an error."""
    if "error" in result:
        console.print(f"[red]Error: {result['error'].get('message', result['error'])}[/red]")
        return True
    return False


app = typer.Typer(help="Query Campy memory from the command line")


@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for in memory"),
    scope: str = typer.Option("both", help="Search scope: branch, global, or both"),
    format: str = typer.Option("rich", "--format", help="Output format: rich, json, prompt"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Quick semantic recall using current_truth."""
    args = {"query": query, "scope": scope}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("current_truth", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        # Rich format
        data = result.get("result", {})
        results_list = data.get("results", [])
        if not results_list:
            console.print("[dim]No results found.[/dim]")
            return

        table = Table(title=f"Recall: {query}")
        table.add_column("Type", style="cyan", width=12)
        table.add_column("Content", style="white")
        table.add_column("Confidence", style="magenta", width=12)

        for item in results_list:
            table.add_row(
                item.get("type", "unknown"),
                item.get("text_raw", item.get("summary", ""))[:120],
                f"{item.get('confidence', 'N/A')}",
            )
        console.print(table)
```

- [ ] **Step 4: Mount recall app in main.py**

In `campy/cli/main.py`, add:

```python
from campy.cli.recall import app as recall_app

# Mount recall commands as top-level commands
app.add_typer(recall_app, name="memory", help="Memory recall commands")

# Also add direct shortcuts
@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for"),
    format: str = typer.Option("rich", "--format", help="Output format: rich, json, prompt"),
):
    """Quick recall from memory (shortcut for 'campy memory recall')."""
    from campy.cli.recall import recall as _recall
    _recall(query=query, format=format)
```

- [ ] **Step 5: Run test**

Run: `pytest tests/cli/test_recall_cli.py::test_recall_command_exists -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add campy/cli/recall.py campy/cli/main.py tests/cli/test_recall_cli.py
git commit -m "feat(B261): add campy recall CLI command"
```

---

### Task 2: Add `campy bundle` Command

**Files:**
- Modify: `campy/cli/recall.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/cli/test_recall_cli.py`:

```python
def test_bundle_command_exists():
    """campy bundle --help should work."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "bundle", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Add bundle command to recall.py**

```python
@app.command()
def bundle(
    query: str = typer.Argument(..., help="What context to compile"),
    token_budget: int = typer.Option(32000, help="Token budget for the bundle"),
    agent_type: str = typer.Option("generic", help="Agent type for formatting"),
    format: str = typer.Option("rich", "--format", help="Output format: rich, json, prompt"),
):
    """Compile a full context bundle from all memory types."""
    result = _call_tool("compile_context", {
        "query": query,
        "token_budget": token_budget,
        "agent_type": agent_type,
    })
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(Markdown(f"## Bundle: {query}\n"))
        sections = data.get("sections", [])
        for section in sections:
            console.print(f"\n[bold cyan]{section.get('type', 'unknown')}[/bold cyan]")
            for item in section.get("content", []):
                console.print(f"  • {str(item)[:100]}")
        console.print(f"\n[dim]Tokens: {data.get('total_token_estimate', '?')} / {data.get('token_budget', '?')}[/dim]")
```

Also add shortcut in `main.py`:

```python
@app.command()
def bundle(
    query: str = typer.Argument(..., help="Context to compile"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """Compile full context bundle (shortcut)."""
    from campy.cli.recall import bundle as _bundle
    _bundle(query=query, format=format)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/cli/test_recall_cli.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add campy/cli/recall.py campy/cli/main.py tests/cli/test_recall_cli.py
git commit -m "feat(B261): add campy bundle CLI command"
```

---

### Task 3: Add `campy timeline`, `campy diff`, `campy decide`, `campy context`

**Files:**
- Modify: `campy/cli/recall.py`
- Modify: `campy/cli/main.py`
- Modify: `tests/cli/test_recall_cli.py`

- [ ] **Step 1: Write failing tests for all 4 commands**

Add to `tests/cli/test_recall_cli.py`:

```python
import pytest

@pytest.mark.parametrize("cmd", ["timeline", "diff", "decide", "context"])
def test_recall_commands_exist(cmd):
    """All recall subcommands should be available."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", cmd, "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"{cmd} --help failed: {result.stderr}"
```

- [ ] **Step 2: Add all 4 commands to recall.py**

```python
@app.command()
def timeline(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp to start from"),
    limit: int = typer.Option(20, help="Max events to return"),
    quest_id: Optional[str] = typer.Option(None, help="Filter by quest"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """View temporal timeline of memory events."""
    args = {"limit": limit}
    if since:
        args["since_iso"] = since
    if quest_id:
        args["quest_id"] = quest_id

    result = _call_tool("reconstruct_timeline", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        events = result.get("result", {}).get("events", [])
        table = Table(title="Timeline")
        table.add_column("Time", style="cyan", width=20)
        table.add_column("Type", style="magenta", width=12)
        table.add_column("Summary", style="white")
        for event in events:
            table.add_row(
                event.get("timestamp", "?"),
                event.get("type", "?"),
                str(event.get("summary", ""))[:80],
            )
        console.print(table)


@app.command()
def diff(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp (default: 24h ago)"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """Show what changed in memory since a timestamp."""
    if since is None:
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"

    result = _call_tool("diff_since", {"since_iso": since})
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(f"[bold]Changes since {since}[/bold]\n")
        for category in ["created", "updated", "deprecated"]:
            items = data.get(category, [])
            if items:
                console.print(f"[cyan]{category.title()} ({len(items)}):[/cyan]")
                for item in items:
                    console.print(f"  • {item.get('label', item.get('text_raw', str(item)))[:100]}")


@app.command()
def decide(
    query: str = typer.Argument(..., help="Question to route"),
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Ask the memory router which tool to use."""
    args = {"query": query}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("memory_decision", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(f"[bold cyan]Recommended tool:[/bold cyan] {data.get('recommended_tool', '?')}")
        console.print(f"[dim]Reasoning: {data.get('reasoning', 'N/A')}[/dim]")
        console.print(f"[dim]Confidence: {data.get('confidence', 'N/A')}[/dim]")


@app.command()
def context(
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Check current context health and status."""
    args = {}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("context_status", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print("[bold]Context Status[/bold]")
        for key, value in data.items():
            console.print(f"  [cyan]{key}:[/cyan] {value}")
```

- [ ] **Step 3: Mount shortcut commands in main.py**

In `campy/cli/main.py`:

```python
@app.command()
def timeline(since: Optional[str] = typer.Option(None, "--since"), format: str = typer.Option("rich", "--format")):
    """View memory timeline."""
    from campy.cli.recall import timeline as _timeline
    _timeline(since=since, format=format)

@app.command(name="diff")
def diff_cmd(since: Optional[str] = typer.Option(None, "--since"), format: str = typer.Option("rich", "--format")):
    """Show memory changes since timestamp."""
    from campy.cli.recall import diff as _diff
    _diff(since=since, format=format)

@app.command()
def decide(query: str = typer.Argument(...), format: str = typer.Option("rich", "--format")):
    """Ask memory router which tool to use."""
    from campy.cli.recall import decide as _decide
    _decide(query=query, format=format)

@app.command(name="context")
def context_cmd(format: str = typer.Option("rich", "--format")):
    """Check context health."""
    from campy.cli.recall import context as _context
    _context(format=format)
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/cli/test_recall_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/recall.py campy/cli/main.py tests/cli/test_recall_cli.py
git commit -m "feat(B261): add timeline, diff, decide, context CLI commands"
```

---

### Task 4: Integration Test (Requires Running Daemon)

**Files:**
- Create: `tests/cli/test_recall_cli_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/cli/test_recall_cli_integration.py
import subprocess
import sys
import pytest

@pytest.mark.integration
def test_recall_returns_results():
    """campy recall should return results from running daemon."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "recall", "test query", "--format=json"],
        capture_output=True, text=True, timeout=10
    )
    if "Daemon not running" in result.stdout:
        pytest.skip("Daemon not running")
    assert result.returncode == 0

@pytest.mark.integration
def test_decide_returns_recommendation():
    """campy decide should return a tool recommendation."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "decide", "what tools are available?", "--format=json"],
        capture_output=True, text=True, timeout=10
    )
    if "Daemon not running" in result.stdout:
        pytest.skip("Daemon not running")
    assert result.returncode == 0
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/cli/test_recall_cli_integration.py -m integration -v`
Expected: PASS or SKIP

- [ ] **Step 3: Commit**

```bash
git add tests/cli/test_recall_cli_integration.py
git commit -m "test(B261): add CLI recall integration tests"
```
