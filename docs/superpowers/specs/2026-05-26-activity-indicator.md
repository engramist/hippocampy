# Campy Activity Indicator

## Context

Campy runs as a background daemon processing messages through the Gated Consolidation Loop, running recall queries, and executing dreaming sweeps. But there's no way to tell at a glance whether Campy is active, what it's doing, or whether it's even running. Users work across Claude Code, Codex, Gemini CLI, VS Code Copilot, and ChatGPT Desktop — the indicator must be agent-agnostic.

**Problem:** No visibility into Campy's operational state without running `campy activity --follow` in a dedicated terminal and reading raw JSON logs.

**Solution:** A lightweight status API on the daemon that emits real-time phase transitions via SSE, consumed by three presentation surfaces: a cross-platform system tray app, a CLI one-liner, and an enhanced web dashboard widget.

## Design

### 1. Phase State Machine

Four high-level phases, mapped to the existing activity log `lane` field:

| Phase | Color | Trigger | Returns to idle |
|---|---|---|---|
| `idle` | Green (#48bb78) | No activity for 3+ seconds | — |
| `encoding` | Amber (#ecc94b) | `notify_turn` handler begins processing | Handler completes |
| `recalling` | Blue (#4299e1) | Recall tool invoked (`current_truth`, `compile_context`, `recall_relevant_lessons`, etc.) | Tool returns |
| `sweeping` | Purple (#9f7aea) | `run_sweep` begins | Sweep completes |

**State machine implementation:** An in-memory singleton in the daemon process — not a database write, not a file write. Two fields:

```python
_current_phase: str = "idle"       # one of: idle, encoding, recalling, sweeping
_phase_changed_at: float = time.time()  # monotonic timestamp
```

**Phase transition function:**

```python
def set_phase(phase: str) -> None:
    global _current_phase, _phase_changed_at
    if phase != _current_phase:
        _current_phase = phase
        _phase_changed_at = time.time()
        _broadcast_phase()  # push to SSE subscribers
```

**Where transitions fire:**
- `notify_turn` handler entry → `set_phase("encoding")`, completion → `set_phase("idle")`
- Any recall tool handler entry → `set_phase("recalling")`, completion → `set_phase("idle")`
- `run_sweep` entry → `set_phase("sweeping")`, completion → `set_phase("idle")`
- 3-second idle timeout: if no new `set_phase` call within 3 seconds, auto-reset to `idle` (handles edge cases where a handler crashes without resetting)

**Concurrency:** The daemon is async (single event loop), so `_current_phase` is only accessed from one thread. No locks needed. The `set_phase` function is synchronous and non-blocking.

### 2. SSE Activity Stream Endpoint

**Endpoint:** `GET /api/v1/activity/stream`

**Event types:**

```
event: phase
data: {"phase": "encoding", "since": "2026-05-26T10:30:00Z"}

event: heartbeat
data: {"phase": "idle", "since": "2026-05-26T10:29:57Z", "uptime_s": 3600}
```

- `phase` events emit on every state transition (only when phase actually changes)
- `heartbeat` events emit every 15 seconds with current phase (consumer liveness check)

**Implementation:** Starlette `StreamingResponse` with `text/event-stream` content type. Maintains a set of subscriber asyncio.Queue objects. `_broadcast_phase()` pushes to all queues. On client disconnect, the queue is removed.

**Also add:** `GET /api/v1/heartbeat` — non-streaming JSON endpoint for one-shot checks:

```json
{"phase": "encoding", "since": "2026-05-26T10:30:00Z", "uptime_s": 3600}
```

### 3. System Tray App (pystray)

A cross-platform system tray indicator using `pystray` + `Pillow`.

**Appearance:**
- Tray icon: a 22×22 pixel colored circle generated with Pillow, color matches current phase
- Tooltip on hover: `Campy: encoding (2s ago)`

**Menu items (click/right-click):**
1. Current phase + duration (disabled label): `● encoding (2s ago)`
2. Separator
3. `Open Control Panel` → opens `http://127.0.0.1:7799` in default browser
4. Separator
5. `Quit`

**Architecture:**
- Single file: `campy/cli/indicator.py` (~100 lines)
- Background thread subscribes to `GET /api/v1/activity/stream` via `httpx`
- On each `phase` event: generate new colored circle icon with Pillow, update `icon.icon` and `icon.title`
- On connection loss: icon goes grey (#718096), tooltip shows `Campy: offline`, auto-reconnect every 5 seconds
- On reconnect: immediately fetch `/api/v1/heartbeat` to get current phase

**Cross-platform behavior:**

| | macOS | Windows | Linux |
|---|---|---|---|
| Location | Menu bar | System tray | System tray |
| Icon | Colored circle | Colored circle | Colored circle |
| Interaction | Click for menu | Right-click for menu | Click for menu |

**Auto-start installation:**

```bash
campy indicator              # run in foreground
campy indicator --install    # install auto-start for current platform
campy indicator --uninstall  # remove auto-start
```

| Platform | --install mechanism |
|---|---|
| macOS | Write `~/Library/LaunchAgents/dev.hippocampy.indicator.plist`, load via `launchctl` |
| Windows | Create shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` |
| Linux | Write `~/.config/autostart/campy-indicator.desktop` |

**Dependencies:** `pystray` and `Pillow`, added as optional extras: `pip install campy[indicator]`

### 4. CLI Status Command

**New command:** `campy status`

**Modes:**

```bash
campy status              # one-shot: print current phase and exit
campy status --watch      # live: update in-place until Ctrl+C
```

**One-shot output:**
```
🧠 encoding · 2s · hippocampy
```

Format: `icon phase · duration-since-phase-change · last-active-project`

If daemon unreachable: `🧠 offline` (exit code 1).

**Watch mode:** Subscribe to `/api/v1/activity/stream`, update the line in-place using `\r` carriage return. Single line, no scrolling.

**Implementation:** ~30 lines added to `campy/cli/doctor.py` (where `campy activity` already lives). Uses `httpx` (already a dependency) for both one-shot GET and SSE streaming.

### 5. Web Dashboard Widget Enhancement

The existing Memory Control Panel (`localhost:7799`) already has a `#status-dot` element in the header — green when online, red when offline.

**Enhancement:**
- Dot color now reflects all 4 phases (green/amber/blue/purple) instead of binary online/offline
- Add a text label next to the dot: `idle`, `encoding`, `recalling`, `sweeping`
- JavaScript subscribes to `EventSource("/api/v1/activity/stream")`
- On `phase` events: update dot color + label text
- On `heartbeat` events: update tooltip with uptime
- On SSE connection error: revert to red dot + `offline` label

**Implementation:** ~20 lines of JavaScript added to the existing control panel HTML. No new files.

## What Doesn't Change

- **GCL pipeline logic:** No changes to any consolidation loop step
- **Database schema:** No new tables, columns, or migrations
- **Activity log format:** `~/.campy/activity.log` continues writing the same JSON lines
- **MCP tool surface:** No new MCP tools (the SSE stream is a REST endpoint, not a tool)
- **Existing `campy activity` command:** Unchanged (still tails the activity log)
- **Agent integrations:** No agent-specific changes (the tray app is agent-agnostic)

## Implementation

### Files to modify (4)

| File | Change |
|---|---|
| `mcp_engine/rest_api.py` | Add `activity_stream` SSE endpoint (~40 lines), add `heartbeat` endpoint (~10 lines), add phase state machine module-level singleton (~20 lines) |
| `mcp_engine/server.py` | Wire `set_phase()` calls into `notify_turn` handler and tool dispatch (~10 lines), enhance dashboard HTML status dot (~20 lines JS) |
| `campy/cli/doctor.py` | Add `campy status` and `campy status --watch` (~30 lines) |
| `pyproject.toml` | Add `indicator` optional dependency group with `pystray` and `Pillow` (~3 lines) |

### New files (1)

| File | Purpose |
|---|---|
| `campy/cli/indicator.py` | System tray app: pystray icon, SSE subscriber, auto-start install/uninstall (~100 lines) |

### Testing

| Test | Expected |
|---|---|
| Phase state machine: `set_phase("encoding")` | `_current_phase == "encoding"`, `_phase_changed_at` updated |
| Phase state machine: same phase twice | No broadcast on second call (no-op) |
| SSE endpoint: connect and receive | Initial `phase` event with current state |
| SSE endpoint: phase changes | New `phase` event pushed to all subscribers |
| SSE endpoint: heartbeat | Event every 15 seconds with current phase |
| Heartbeat endpoint: daemon running | JSON with phase + since + uptime_s |
| Heartbeat endpoint: daemon down | Connection refused (consumer handles) |
| CLI one-shot: daemon running | Prints `🧠 idle · 0s` and exits 0 |
| CLI one-shot: daemon down | Prints `🧠 offline` and exits 1 |
| Tray icon: phase change | Icon color updates to match phase |
| Tray icon: daemon restart | Auto-reconnects within 5 seconds |
| Dashboard dot: phase change | Dot color and label text update in real-time |
| Auto-start install/uninstall: macOS | Plist created/removed in ~/Library/LaunchAgents/ |
