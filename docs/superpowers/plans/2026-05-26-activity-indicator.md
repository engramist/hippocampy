# Implementation Plan: Campy Activity Indicator

**Spec:** `docs/superpowers/specs/2026-05-26-activity-indicator.md`

## Task Overview

| Task | Description | Dependencies | Parallelizable |
|------|-------------|--------------|----------------|
| Task 1 | Phase state machine + SSE endpoint + heartbeat | None | ✅ Independent |
| Task 2 | Wire phase transitions into handlers | Task 1 | ❌ Needs Task 1 |
| Task 3 | CLI `campy status --watch` | Task 1 | ✅ Can parallel with Task 2 |
| Task 4 | Web dashboard widget enhancement | Task 1 | ✅ Can parallel with Tasks 2,3 |
| Task 5 | System tray app (pystray) | Task 1 | ✅ Can parallel with Tasks 2,3,4 |

**Parallel execution plan:** Task 1 first (foundation), then Tasks 2-5 in parallel.

---

## Task 1: Phase State Machine + SSE Endpoint + Heartbeat

**Files to modify:** `mcp_engine/rest_api.py`
**Files to create:** `mcp_engine/phase.py`

### Step 1a: Create `mcp_engine/phase.py` — Phase state machine singleton

Create this new file:

```python
"""Phase state machine for Campy activity indicator."""
import asyncio
import time
from datetime import datetime, timezone
from typing import Set

import logging

logger = logging.getLogger(__name__)

# --- Phase state (module-level singleton) ---
_current_phase: str = "idle"
_phase_changed_at: float = time.time()
_subscribers: Set[asyncio.Queue] = set()
_idle_handle: asyncio.TimerHandle | None = None

VALID_PHASES = {"idle", "encoding", "recalling", "sweeping"}
IDLE_TIMEOUT_S = 3.0
HEARTBEAT_INTERVAL_S = 15.0


def get_phase() -> dict:
    """Return current phase as a dict (for heartbeat endpoint)."""
    return {
        "phase": _current_phase,
        "since": datetime.fromtimestamp(_phase_changed_at, tz=timezone.utc).isoformat(),
        "uptime_s": round(time.time() - _phase_changed_at, 1),
    }


def set_phase(phase: str) -> None:
    """Transition to a new phase and broadcast to SSE subscribers."""
    global _current_phase, _phase_changed_at, _idle_handle

    if phase not in VALID_PHASES:
        logger.warning(f"Invalid phase: {phase}")
        return
    if phase == _current_phase:
        return  # no-op: same phase

    _current_phase = phase
    _phase_changed_at = time.time()
    _broadcast({"event": "phase", "data": get_phase()})

    # Schedule auto-idle if transitioning to a non-idle phase
    if _idle_handle is not None:
        _idle_handle.cancel()
        _idle_handle = None
    if phase != "idle":
        try:
            loop = asyncio.get_running_loop()
            _idle_handle = loop.call_later(IDLE_TIMEOUT_S, _auto_idle)
        except RuntimeError:
            pass  # no event loop (e.g. testing)


def _auto_idle() -> None:
    """Reset to idle after timeout (crash safety)."""
    global _idle_handle
    _idle_handle = None
    set_phase("idle")


def _broadcast(message: dict) -> None:
    """Push a message to all SSE subscriber queues."""
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber. Returns a queue that receives events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(q)
    # Send current phase immediately so subscriber knows the initial state
    q.put_nowait({"event": "phase", "data": get_phase()})
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove an SSE subscriber."""
    _subscribers.discard(q)


async def heartbeat_loop() -> None:
    """Background task that broadcasts heartbeat events to all subscribers."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        if _subscribers:
            _broadcast({"event": "heartbeat", "data": get_phase()})
```

### Step 1b: Add SSE endpoint and heartbeat to `mcp_engine/rest_api.py`

Add these imports at the top:

```python
import asyncio
import json
from starlette.responses import StreamingResponse
```

Add inside `create_router()`, before the `routes = [...]` list:

```python
    async def heartbeat_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/heartbeat — one-shot current phase."""
        from mcp_engine.phase import get_phase
        return _ok(get_phase())

    async def activity_stream_endpoint(request: Request) -> StreamingResponse:
        """GET /api/v1/activity/stream — SSE stream of phase transitions."""
        from mcp_engine.phase import subscribe, unsubscribe

        q = subscribe()

        async def event_generator():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=30.0)
                        yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"  # SSE comment to prevent proxy timeouts
            except asyncio.CancelledError:
                pass
            finally:
                unsubscribe(q)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
```

Add to the `routes` list:

```python
        Route("/api/v1/heartbeat", heartbeat_endpoint, methods=["GET"]),
        Route("/api/v1/activity/stream", activity_stream_endpoint, methods=["GET"]),
```

### Step 1c: Start the heartbeat background task

Find where the Starlette/ASGI app is created (likely in `web/server.py` or wherever `create_router` is called) and add:

```python
from mcp_engine.phase import heartbeat_loop

# In the app startup/lifespan:
asyncio.create_task(heartbeat_loop())
```

### Testing

```bash
# Test heartbeat endpoint
curl -s http://127.0.0.1:7799/api/v1/heartbeat | python3 -m json.tool
# Expected: {"ok": true, "data": {"phase": "idle", "since": "...", "uptime_s": ...}}

# Test SSE stream (Ctrl+C to stop)
curl -N http://127.0.0.1:7799/api/v1/activity/stream
# Expected: event: phase\ndata: {"phase": "idle", ...}\n\n
```

### Unit tests

Create `tests/test_phase.py`:

```python
"""Tests for the phase state machine."""
import asyncio
import pytest
from mcp_engine.phase import set_phase, get_phase, subscribe, unsubscribe, _current_phase

class TestPhaseStateMachine:
    def setup_method(self):
        """Reset phase state before each test."""
        import mcp_engine.phase as mod
        mod._current_phase = "idle"
        mod._phase_changed_at = 0
        mod._subscribers.clear()

    def test_initial_phase_is_idle(self):
        assert get_phase()["phase"] == "idle"

    def test_set_phase_changes_state(self):
        set_phase("encoding")
        assert get_phase()["phase"] == "encoding"

    def test_set_same_phase_is_noop(self):
        set_phase("encoding")
        t1 = get_phase()["since"]
        set_phase("encoding")
        t2 = get_phase()["since"]
        assert t1 == t2  # timestamp unchanged

    def test_invalid_phase_ignored(self):
        set_phase("encoding")
        set_phase("bogus")
        assert get_phase()["phase"] == "encoding"

    def test_subscriber_receives_initial_phase(self):
        q = subscribe()
        msg = q.get_nowait()
        assert msg["event"] == "phase"
        assert msg["data"]["phase"] == "idle"
        unsubscribe(q)

    def test_subscriber_receives_transition(self):
        q = subscribe()
        _ = q.get_nowait()  # consume initial
        set_phase("recalling")
        msg = q.get_nowait()
        assert msg["event"] == "phase"
        assert msg["data"]["phase"] == "recalling"
        unsubscribe(q)

    def test_unsubscribe_stops_delivery(self):
        q = subscribe()
        _ = q.get_nowait()
        unsubscribe(q)
        set_phase("sweeping")
        assert q.empty()
```

### Commit message
```
feat(indicator): add phase state machine and SSE activity stream endpoint
```

---

## Task 2: Wire Phase Transitions into Handlers

**Depends on:** Task 1
**Files to modify:** `mcp_engine/tools/__init__.py`, `mcp_engine/sweep.py`

### Step 2a: Wire `notify_turn` handler

In `mcp_engine/tools/__init__.py`, find the `notify_turn` function (line ~556). Add phase transitions:

```python
async def notify_turn(params: dict, db: KuzuClient, config: dict) -> dict:
    from mcp_engine.phase import set_phase
    set_phase("encoding")
    try:
        # ... existing function body unchanged ...
        return result
    finally:
        set_phase("idle")
```

Wrap the existing function body in a try/finally so that `set_phase("idle")` always fires, even on errors.

### Step 2b: Wire recall tool handlers

Find the recall tools and add phase transitions. The recall tools are: `current_truth`, `compile_context`, `recall_relevant_lessons`, `recall_procedures`, `recall_plans`, `reconstruct_timeline`, `analogical_search`, `explore_graph`, `memory_decision`.

Rather than modifying each function individually, add a wrapper approach. Near the top of `mcp_engine/tools/__init__.py`, add:

```python
RECALL_TOOLS = {
    "current_truth", "compile_context", "recall_relevant_lessons",
    "recall_procedures", "recall_plans", "reconstruct_timeline",
    "analogical_search", "explore_graph", "memory_decision",
}
```

Then modify the `TOOL_HANDLERS` dict construction or add a decorator. The simplest approach: wrap each recall handler in the dict:

```python
def _with_phase(phase: str, fn):
    """Wrap a tool handler to set phase during execution."""
    async def wrapper(params=None, arguments=None, db=None, config=None, **kw):
        from mcp_engine.phase import set_phase
        set_phase(phase)
        try:
            return await fn(params=params, arguments=arguments, db=db, config=config, **kw)
        finally:
            set_phase("idle")
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
```

Then in the `TOOL_HANDLERS` dict, wrap the recall tools:

```python
TOOL_HANDLERS = {
    "notify_turn":      _with_phase("encoding", notify_turn),
    "current_truth":    _with_phase("recalling", current_truth),
    "compile_context":  _with_phase("recalling", compile_context),
    # ... etc for all recall tools
    # Non-phased tools remain unwrapped:
    "set_quest":        set_quest,
    "context_status":   context_status,
    # ...
}
```

### Step 2c: Wire sweep runner

In `mcp_engine/sweep.py`, in `run_sweep()` (line 68):

```python
async def run_sweep(db, config: dict, llm_client=None) -> dict:
    from mcp_engine.phase import set_phase
    set_phase("sweeping")
    try:
        # ... existing function body unchanged ...
        return summary
    finally:
        set_phase("idle")
```

### Testing

```bash
# Start daemon, then in another terminal:
curl -N http://127.0.0.1:7799/api/v1/activity/stream &

# Trigger encoding by sending a test message:
curl -X POST http://127.0.0.1:7799/api/v1/notify \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"test message"}'

# Expected SSE output:
# event: phase
# data: {"phase": "encoding", ...}
# event: phase
# data: {"phase": "idle", ...}
```

### Commit message
```
feat(indicator): wire phase transitions into notify_turn, recall tools, and sweep
```

---

## Task 3: CLI `campy status --watch`

**Depends on:** Task 1 (needs the heartbeat/SSE endpoints to exist)
**Can run in parallel with:** Tasks 2, 4, 5
**Files to modify:** `campy/cli/main.py`

### Implementation

Add a `--watch` flag to the existing `status` command in `campy/cli/main.py` (line 245):

```python
@app.command()
def status(
    watch: bool = typer.Option(False, "--watch", "-w", help="Live-updating phase display"),
):
    """
    Check the health and status of the HippoCampy memory daemon.
    """
    import httpx
    import sys

    HEARTBEAT_URL = "http://127.0.0.1:7799/api/v1/heartbeat"
    STREAM_URL = "http://127.0.0.1:7799/api/v1/activity/stream"

    PHASE_COLORS = {
        "idle": "green",
        "encoding": "yellow",
        "recalling": "blue",
        "sweeping": "magenta",
    }

    def _format_phase(data: dict) -> str:
        phase = data.get("phase", "unknown")
        uptime = data.get("uptime_s", 0)
        color = PHASE_COLORS.get(phase, "white")
        return f"[{color}]🧠 {phase}[/{color}] · {uptime:.0f}s"

    if not watch:
        # One-shot mode: hit heartbeat endpoint and exit
        try:
            r = httpx.get(HEARTBEAT_URL, timeout=2.0)
            body = r.json()
            if body.get("ok"):
                console.print(_format_phase(body["data"]))
            else:
                console.print("[red]🧠 error[/red]")
                raise typer.Exit(code=1)
        except (httpx.ConnectError, httpx.TimeoutException):
            console.print("[red]🧠 offline[/red]")
            raise typer.Exit(code=1)
        return

    # Watch mode: subscribe to SSE stream
    console.print("[dim]Watching Campy phase changes (Ctrl+C to stop)...[/dim]")
    try:
        with httpx.stream("GET", STREAM_URL, timeout=None) as response:
            event_type = ""
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:") and event_type == "phase":
                    import json
                    data = json.loads(line[5:].strip())
                    sys.stdout.write(f"\r{' ' * 40}\r")  # clear line
                    console.print(_format_phase(data), end="")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        console.print()  # newline after \r content
    except (httpx.ConnectError, httpx.TimeoutException):
        console.print("[red]🧠 offline[/red]")
        raise typer.Exit(code=1)
```

Remove the old `status` function body (lines 246-253) — it's replaced entirely.

### Testing

```bash
# One-shot (daemon running):
campy status
# Expected: 🧠 idle · 5s

# One-shot (daemon not running):
campy status
# Expected: 🧠 offline (exit code 1)

# Watch mode:
campy status --watch
# Expected: live-updating line that changes on phase transitions
```

### Commit message
```
feat(indicator): add campy status --watch with live SSE phase display
```

---

## Task 4: Web Dashboard Widget Enhancement

**Depends on:** Task 1 (needs the SSE endpoint)
**Can run in parallel with:** Tasks 2, 3, 5
**Files to modify:** `web/static/index.html`

### Implementation

In `web/static/index.html`, make three changes:

**1. Add CSS for phase colors** (add after the existing `#status-dot.offline` rule, around line 18):

```css
#status-dot.encoding { background: #ecc94b; }
#status-dot.recalling { background: #4299e1; }
#status-dot.sweeping { background: #9f7aea; }
#phase-label { font-size: 0.7rem; color: #a0aec0; margin-left: 6px;
               text-transform: uppercase; letter-spacing: 0.05em; }
```

**2. Add the phase label element** (add after `<div id="status-dot"></div>`, around line 133):

```html
<span id="phase-label">idle</span>
```

**3. Add SSE subscription JavaScript** (add at the end of the existing `<script>` block, or replace the existing status-dot logic):

```javascript
// --- Activity Indicator SSE ---
(function() {
  const dot = document.getElementById('status-dot');
  const label = document.getElementById('phase-label');
  const PHASE_CLASSES = ['encoding', 'recalling', 'sweeping', 'offline'];

  function updatePhase(phase) {
    // Remove all phase classes
    PHASE_CLASSES.forEach(c => dot.classList.remove(c));
    if (phase === 'idle') {
      // Default green (no extra class needed)
    } else if (PHASE_CLASSES.includes(phase)) {
      dot.classList.add(phase);
    }
    label.textContent = phase;
  }

  function connectSSE() {
    const es = new EventSource('/api/v1/activity/stream');
    es.addEventListener('phase', (e) => {
      const data = JSON.parse(e.data);
      updatePhase(data.phase);
    });
    es.addEventListener('heartbeat', (e) => {
      const data = JSON.parse(e.data);
      updatePhase(data.phase);
    });
    es.onerror = () => {
      updatePhase('offline');
      es.close();
      // Reconnect after 5 seconds
      setTimeout(connectSSE, 5000);
    };
  }

  connectSSE();
})();
```

### Testing

```bash
# Open http://127.0.0.1:7799 in browser
# Verify: green dot + "idle" label visible in header bar
# Trigger a notify_turn call:
curl -X POST http://127.0.0.1:7799/api/v1/notify \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"test"}'
# Verify: dot turns amber + label shows "encoding", then returns to green + "idle"
```

### Commit message
```
feat(indicator): enhance dashboard status dot with live phase colors via SSE
```

---

## Task 5: System Tray App (pystray)

**Depends on:** Task 1 (needs the heartbeat/SSE endpoints)
**Can run in parallel with:** Tasks 2, 3, 4
**Files to create:** `campy/cli/indicator.py`
**Files to modify:** `campy/cli/main.py`, `pyproject.toml`

### Step 5a: Add optional dependency group to `pyproject.toml`

In the `[project.optional-dependencies]` section (after line 34), add:

```toml
indicator = [
    "pystray>=0.19",
    "Pillow>=10.0",
]
```

### Step 5b: Create `campy/cli/indicator.py`

```python
"""Cross-platform system tray indicator for Campy daemon phase status."""
import json
import logging
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HEARTBEAT_URL = "http://127.0.0.1:7799/api/v1/heartbeat"
STREAM_URL = "http://127.0.0.1:7799/api/v1/activity/stream"
CONTROL_PANEL_URL = "http://127.0.0.1:7799"

PHASE_COLORS = {
    "idle":      (72, 187, 120),    # green
    "encoding":  (236, 201, 75),    # amber
    "recalling": (66, 153, 225),    # blue
    "sweeping":  (159, 122, 234),   # purple
    "offline":   (113, 128, 150),   # grey
}

ICON_SIZE = 22


def _make_icon_image(color: tuple):
    """Generate a colored circle icon image using Pillow."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        fill=(*color, 255),
    )
    return img


def _sse_listener(icon, stop_event: threading.Event):
    """Background thread: subscribe to SSE stream and update tray icon."""
    import httpx

    while not stop_event.is_set():
        try:
            with httpx.stream("GET", STREAM_URL, timeout=None) as response:
                event_type = ""
                for line in response.iter_lines():
                    if stop_event.is_set():
                        return
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:") and event_type in ("phase", "heartbeat"):
                        data = json.loads(line[5:].strip())
                        phase = data.get("phase", "idle")
                        uptime = data.get("uptime_s", 0)
                        color = PHASE_COLORS.get(phase, PHASE_COLORS["idle"])
                        icon.icon = _make_icon_image(color)
                        icon.title = f"Campy: {phase} ({uptime:.0f}s)"
        except Exception:
            # Connection lost — show offline and retry
            icon.icon = _make_icon_image(PHASE_COLORS["offline"])
            icon.title = "Campy: offline"
            if not stop_event.is_set():
                stop_event.wait(timeout=5.0)


def _open_control_panel():
    """Open the Campy control panel in the default browser."""
    import webbrowser
    webbrowser.open(CONTROL_PANEL_URL)


def run_indicator():
    """Launch the system tray indicator (blocking — runs the event loop)."""
    try:
        import pystray
    except ImportError:
        print("pystray not installed. Run: pip install campy[indicator]")
        sys.exit(1)

    stop_event = threading.Event()

    menu = pystray.Menu(
        pystray.MenuItem("Open Control Panel", lambda: _open_control_panel()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, _: (stop_event.set(), icon.stop())),
    )

    icon = pystray.Icon(
        name="campy",
        icon=_make_icon_image(PHASE_COLORS["offline"]),
        title="Campy: connecting...",
        menu=menu,
    )

    # Start SSE listener in background thread
    listener = threading.Thread(target=_sse_listener, args=(icon, stop_event), daemon=True)
    listener.start()

    # Run the icon (blocking)
    icon.run()
    stop_event.set()


# --- Auto-start install/uninstall ---

_LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.hippocampy.indicator</string>
  <key>ProgramArguments</key>
  <array>
    <string>{exe}</string>
    <string>indicator</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
"""

_LINUX_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=Campy Indicator
Exec={exe} indicator
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""


def install_autostart():
    """Install platform-appropriate auto-start entry."""
    exe = sys.executable.replace("python", "campy")
    # Try to find the actual campy executable
    campy_bin = Path(sys.executable).parent / "campy"
    if campy_bin.exists():
        exe = str(campy_bin)

    system = platform.system()
    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "dev.hippocampy.indicator.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(_LAUNCHD_PLIST.format(exe=exe))
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print(f"Installed: {plist_path}")
    elif system == "Windows":
        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        # Create a .bat file (simpler than .lnk for Python)
        bat = startup / "campy-indicator.bat"
        bat.write_text(f'@echo off\nstart /b "" "{exe}" indicator\n')
        print(f"Installed: {bat}")
    elif system == "Linux":
        desktop_path = Path.home() / ".config" / "autostart" / "campy-indicator.desktop"
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(_LINUX_DESKTOP.format(exe=exe))
        print(f"Installed: {desktop_path}")
    else:
        print(f"Unsupported platform: {system}")
        return
    print("Campy indicator will start automatically on login.")


def uninstall_autostart():
    """Remove platform-appropriate auto-start entry."""
    system = platform.system()
    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "dev.hippocampy.indicator.plist"
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink(missing_ok=True)
        print(f"Removed: {plist_path}")
    elif system == "Windows":
        bat = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "campy-indicator.bat"
        bat.unlink(missing_ok=True)
        print(f"Removed: {bat}")
    elif system == "Linux":
        desktop_path = Path.home() / ".config" / "autostart" / "campy-indicator.desktop"
        desktop_path.unlink(missing_ok=True)
        print(f"Removed: {desktop_path}")
    else:
        print(f"Unsupported platform: {system}")
```

### Step 5c: Add CLI command to `campy/cli/main.py`

Add after the existing `activity` command:

```python
@app.command()
def indicator(
    install: bool = typer.Option(False, "--install", help="Install auto-start for current platform"),
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove auto-start"),
):
    """
    Launch the Campy system tray indicator.

    Shows a colored icon in the system tray reflecting the daemon's current phase:
    green (idle), amber (encoding), blue (recalling), purple (sweeping).

    Install with: pip install campy[indicator]
    """
    from campy.cli.indicator import run_indicator, install_autostart, uninstall_autostart

    if install:
        install_autostart()
        return
    if uninstall:
        uninstall_autostart()
        return
    run_indicator()
```

### Testing

```bash
# Verify optional deps install
pip install campy[indicator]

# Run indicator (shows tray icon)
campy indicator

# Install auto-start
campy indicator --install

# Uninstall auto-start
campy indicator --uninstall
```

### Commit message
```
feat(indicator): add cross-platform system tray app with pystray
```

---

## Execution Summary

```
Task 1 (foundation) ──────┐
                           ├── Task 2 (wire phase transitions)
                           ├── Task 3 (CLI status --watch)
                           ├── Task 4 (dashboard widget)
                           └── Task 5 (system tray app)
```

Task 1 runs first. Tasks 2-5 run in parallel as independent haiku subagents.
