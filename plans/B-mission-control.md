# B-Mission-Control — SideQuests Mission Control Dashboard

## Overview

Build a local web dashboard at `http://127.0.0.1:7800` with two views:
1. **Dashboard** — agent status, brain metrics, activity feed, git status
2. **Kanban Board** — task tracking with Backlog/In Progress/Under Review/Completed columns

Single FastAPI app. HTMX for real-time updates. Tailwind CSS via CDN for styling.

## Files to Read First

| File | Why |
|------|-----|
| `web/server.py` | Existing FastAPI patterns (Brain Daemon web UI) |
| `mission-control/kanban.json` | Board state data — already seeded |

## Files to Create

```
mission-control/
├── server.py              # FastAPI app
├── kanban.json            # Board state (already created)
├── templates/
│   ├── base.html          # Shared layout (nav, tailwind CDN)
│   ├── dashboard.html     # Dashboard view
│   └── board.html         # Kanban board view
└── static/
    └── mission.css        # Minimal custom CSS
```

## Implementation

### Phase 1: `mission-control/server.py`

```python
"""
SideQuests Mission Control — Local dashboard for monitoring agents,
brain health, and task progress.

Run: python mission-control/server.py
Serves: http://127.0.0.1:7800
"""

import json
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PORT = 7800
BRAIN_URL = "http://127.0.0.1:7799"
REPO_ROOT = Path(__file__).parent.parent  # sidequests-brain/
KANBAN_PATH = Path(__file__).parent / "kanban.json"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="SideQuests Mission Control", docs_url=None, redoc_url=None)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_kanban() -> dict:
    """Read kanban.json, return parsed dict."""
    try:
        return json.loads(KANBAN_PATH.read_text())
    except Exception:
        return {"schema_version": 1, "columns": [], "tasks": []}


def _write_kanban(data: dict):
    """Write kanban.json atomically."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    KANBAN_PATH.write_text(json.dumps(data, indent=2))


async def _brain_stats() -> dict:
    """Fetch Brain Daemon stats. Returns empty dict on failure."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BRAIN_URL}/api/stats")
            return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}


async def _brain_quests() -> list:
    """Fetch active quests from Brain Daemon."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BRAIN_URL}/api/quests")
            return resp.json().get("quests", []) if resp.status_code == 200 else []
    except Exception:
        return []


async def _brain_open_loops() -> dict:
    """Fetch open loops from Brain Daemon."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BRAIN_URL}/api/open-loops")
            return resp.json() if resp.status_code == 200 else {"count": 0, "items": []}
    except Exception:
        return {"count": 0, "items": []}


async def _brain_alive() -> bool:
    """Check if Brain Daemon is responding."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(BRAIN_URL)
            return resp.status_code == 200
    except Exception:
        return False


def _git_status() -> dict:
    """Get git repo status."""
    try:
        # Recent commits
        log = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=5
        )
        commits = log.stdout.strip().split("\n") if log.stdout.strip() else []

        # Branch
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=5
        )

        # Ahead/behind
        status = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=5
        )
        first_line = status.stdout.split("\n")[0] if status.stdout else ""
        ahead = 0
        if "ahead" in first_line:
            import re
            m = re.search(r'ahead (\d+)', first_line)
            if m:
                ahead = int(m.group(1))

        # Clean?
        dirty_lines = [l for l in status.stdout.strip().split("\n")[1:] if l.strip()]

        return {
            "branch": branch.stdout.strip(),
            "commits": commits,
            "ahead": ahead,
            "clean": len(dirty_lines) == 0,
        }
    except Exception:
        return {"branch": "unknown", "commits": [], "ahead": 0, "clean": True}


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    brain_alive = await _brain_alive()
    stats = await _brain_stats() if brain_alive else {}
    quests = await _brain_quests() if brain_alive else []
    open_loops = await _brain_open_loops() if brain_alive else {"count": 0}
    git = _git_status()
    kanban = _read_kanban()

    # Count tasks by column
    task_counts = {}
    for col in kanban.get("columns", []):
        task_counts[col] = len([t for t in kanban.get("tasks", []) if t.get("column") == col])

    # Agent status (derive from kanban — who has in_progress tasks?)
    agents = {}
    for task in kanban.get("tasks", []):
        agent = task.get("agent")
        if agent and task.get("column") == "in_progress":
            agents[agent] = {"status": "active", "task": task.get("title", ""), "model": task.get("model", "")}
    # Default agents
    for name in ["SideClaw", "Gemini"]:
        if name not in agents:
            agents[name] = {"status": "idle", "task": "", "model": ""}

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "brain_alive": brain_alive,
        "stats": stats,
        "quests": quests,
        "open_loops_count": open_loops.get("count", 0),
        "git": git,
        "task_counts": task_counts,
        "agents": agents,
        "now": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Routes — Kanban Board
# ---------------------------------------------------------------------------

@app.get("/board", response_class=HTMLResponse)
async def board(request: Request):
    kanban = _read_kanban()
    columns = kanban.get("columns", [])
    tasks = kanban.get("tasks", [])

    # Group tasks by column
    by_column = {col: [] for col in columns}
    for task in tasks:
        col = task.get("column", "backlog")
        if col in by_column:
            by_column[col].append(task)

    return templates.TemplateResponse("board.html", {
        "request": request,
        "columns": columns,
        "by_column": by_column,
        "updated_at": kanban.get("updated_at", ""),
    })


# ---------------------------------------------------------------------------
# Routes — Kanban API (for HTMX interactions)
# ---------------------------------------------------------------------------

@app.post("/api/kanban/move")
async def kanban_move(request: Request):
    """Move a task to a different column."""
    body = await request.json()
    task_id = body.get("task_id", "")
    target_column = body.get("column", "")

    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task["id"] == task_id:
            task["column"] = target_column
            if target_column == "completed" and not task.get("completed_at"):
                task["completed_at"] = datetime.now(timezone.utc).isoformat()
            break
    _write_kanban(kanban)
    return JSONResponse({"ok": True})


@app.post("/api/kanban/go-forward/{task_id}")
async def kanban_go_forward(task_id: str):
    """Approve a task under review — move to completed."""
    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task["id"] == task_id and task["column"] == "under_review":
            task["column"] = "completed"
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            break
    _write_kanban(kanban)
    return RedirectResponse("/board", status_code=303)


@app.post("/api/kanban/rollback/{task_id}")
async def kanban_rollback(task_id: str):
    """Rollback a task — revert git commit and move back to backlog."""
    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task["id"] == task_id and task.get("commit"):
            # Git revert
            try:
                subprocess.run(
                    ["git", "revert", "--no-commit", task["commit"]],
                    capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30
                )
                subprocess.run(
                    ["git", "commit", "-m", f"revert: rollback {task_id} — {task.get('title', '')}"],
                    capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10
                )
                task["column"] = "backlog"
                task["rolled_back"] = True
                task["rollback_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            break
    _write_kanban(kanban)
    return RedirectResponse("/board", status_code=303)


@app.post("/api/kanban/add")
async def kanban_add(request: Request):
    """Add a new task to the backlog."""
    body = await request.json()
    kanban = _read_kanban()
    task = {
        "id": body.get("id", f"T-{len(kanban['tasks'])+1:03d}"),
        "title": body.get("title", ""),
        "backlog_ref": body.get("backlog_ref"),
        "column": "backlog",
        "priority": body.get("priority", "medium"),
        "agent": None,
        "model": None,
        "started_at": None,
        "completed_at": None,
        "commit": None,
        "rollback_commit": None,
        "notes": body.get("notes", ""),
    }
    kanban["tasks"].append(task)
    _write_kanban(kanban)
    return JSONResponse({"ok": True, "task": task})


# ---------------------------------------------------------------------------
# Routes — API (for HTMX partial updates)
# ---------------------------------------------------------------------------

@app.get("/api/dashboard-data")
async def dashboard_data():
    """JSON endpoint for HTMX polling."""
    brain_alive = await _brain_alive()
    stats = await _brain_stats() if brain_alive else {}
    git = _git_status()
    kanban = _read_kanban()
    task_counts = {}
    for col in kanban.get("columns", []):
        task_counts[col] = len([t for t in kanban.get("tasks", []) if t.get("column") == col])
    return JSONResponse({
        "brain_alive": brain_alive,
        "stats": stats,
        "git": git,
        "task_counts": task_counts,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print(f"Mission Control: http://127.0.0.1:{PORT}")
    print(f"  Dashboard: http://127.0.0.1:{PORT}/")
    print(f"  Kanban:    http://127.0.0.1:{PORT}/board")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
```

### Phase 2: Templates

**`mission-control/templates/base.html`**

The base template with:
- Tailwind CSS via CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- HTMX via CDN: `<script src="https://unpkg.com/htmx.org@2.0.4"></script>`
- Dark mode by default (class="dark" on html)
- Navigation bar with Dashboard / Board tabs
- `{% block content %}{% endblock %}` for page content
- Footer with "SideQuests Mission Control" and current time

Color scheme: dark background (#0f172a / slate-900), cards (#1e293b / slate-800),
accent blue (#3b82f6), green for active (#22c55e), yellow for warning (#eab308),
red for critical (#ef4444).

**`mission-control/templates/dashboard.html`**

Extends base.html. Layout (CSS Grid, 2 columns):

Left column:
- **Agents panel**: card per agent with status dot (green=active, gray=idle), current task, model
- **Brain Health panel**: Daemon status (green/red dot), node counts from stats, edge count, quest list
- **Scheduled Sessions panel**: next cron job times

Right column:
- **Metrics bar**: 4 stat cards (Tasks Done, Concepts, Decisions, Open Loops) — data from brain stats + kanban counts
- **Git Status panel**: branch, ahead count, clean/dirty, last 5 commits
- **Quick Actions**: link to Brain Control Panel (7799), link to Kanban board

Use `hx-get="/api/dashboard-data" hx-trigger="every 10s" hx-swap="none"` on the body
to auto-refresh data. For the MVP, full page reload every 30s is fine too — use
`<meta http-equiv="refresh" content="30">` as the simplest approach.

**`mission-control/templates/board.html`**

Extends base.html. Kanban layout (CSS Grid, 4 equal columns):

Each column:
- Header with column name and task count badge
- Stack of task cards

Each task card shows:
- Task ID + Title (bold)
- Priority badge (colored: red=critical, orange=high, blue=medium, gray=low)
- Agent name + emoji (🦞 SideClaw, ✨ Gemini, 🤖 other)
- Model used
- Timestamp (started_at or completed_at)
- Notes (truncated to 80 chars)

For "under_review" cards, add two buttons:
- ✅ Go Forward: `hx-post="/api/kanban/go-forward/{task_id}" hx-swap="none"` then redirect
- ↩️ Rollback: `hx-post="/api/kanban/rollback/{task_id}" hx-swap="none"` with confirm dialog

Auto-refresh: `<meta http-equiv="refresh" content="10">` — simple, effective for MVP.

**`mission-control/static/mission.css`**

Minimal custom CSS — only what Tailwind can't do:
- Scrollbar styling for dark mode
- Card hover effects
- Priority badge pulse animation for critical items
- Column min-height so empty columns still show

### Phase 3: Dependencies

Add `httpx` and `jinja2` to the venv:
```bash
cd /Users/djshelton/Desktop/GitProjects/sidequests-brain
.venv/bin/pip install httpx jinja2
```

These are lightweight. FastAPI and uvicorn are already installed.

## What NOT to Do

- Do NOT use React, Next.js, or any JS framework — HTMX + server templates only
- Do NOT add a database for the dashboard — `kanban.json` is the only state
- Do NOT build authentication — localhost only, no auth needed
- Do NOT modify the Brain Daemon code — dashboard reads Brain API, never writes
- Do NOT use websockets — SSE or simple polling via HTMX/meta-refresh
- Do NOT over-design — MVP first, iterate later
- Do NOT add npm/node dependencies — this is a Python project

## Verification

1. `python mission-control/server.py` starts without errors
2. `http://127.0.0.1:7800/` shows the Dashboard with brain stats, agent status, git info
3. `http://127.0.0.1:7800/board` shows the Kanban board with tasks in correct columns
4. Clicking "Go Forward" on an under_review card moves it to completed
5. Clicking "Rollback" on a card reverts the git commit and moves to backlog
6. Dashboard auto-refreshes every 30 seconds
7. Board auto-refreshes every 10 seconds
8. Works with Brain Daemon down (shows "Offline" status, no crash)

## Summary

| File | Lines (approx) | What |
|------|----------------|------|
| `mission-control/server.py` | ~250 | FastAPI app with all routes |
| `mission-control/templates/base.html` | ~50 | Shared layout + Tailwind/HTMX CDN |
| `mission-control/templates/dashboard.html` | ~150 | Dashboard view |
| `mission-control/templates/board.html` | ~150 | Kanban board view |
| `mission-control/static/mission.css` | ~30 | Minimal custom CSS |
| `mission-control/kanban.json` | (exists) | Board state |

Total: ~630 lines across 5 new files. No new infrastructure. Reuses existing Brain API.
