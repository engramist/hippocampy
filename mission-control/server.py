"""
SideQuests Mission Control — Local dashboard for monitoring agents,
brain health, and task progress.

Run: python mission-control/server.py
Serves: http://127.0.0.1:7800
"""

import json
import re
import subprocess
import asyncio
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta

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
DIGEST_PATH = Path(__file__).parent / "digest.json"
ACTIVITY_PATH = Path(__file__).parent / "activity-feed.json"
MEMORY_PATH = Path(__file__).parent.parent.parent.parent / ".openclaw" / "workspace" / "memory"
OPENCLAW_TOKEN = "OPENCLAW_TOKEN_REMOVED"
OPENCLAW_URL = "http://127.0.0.1:18789"
ACTIVITY_MAX = 200  # max events to keep
MOUNTAIN_TZ = ZoneInfo("America/Denver")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="SideQuests Mission Control", docs_url=None, redoc_url=None)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["mt_full"] = lambda value: _format_timestamp(value, "full")
templates.env.filters["mt_time"] = lambda value: _format_timestamp(value, "time")
templates.env.filters["mt_compact"] = lambda value: _format_timestamp(value, "compact")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mountain_now() -> datetime:
    return datetime.now(MOUNTAIN_TZ)


def _parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    dt = datetime.strptime(text, "%H:%M:%S").replace(
                        year=_mountain_now().year,
                        month=_mountain_now().month,
                        day=_mountain_now().day,
                        tzinfo=MOUNTAIN_TZ,
                    )
                except ValueError:
                    try:
                        cleaned = text.removesuffix(" MDT").strip()
                        dt = datetime.strptime(cleaned, "%a %m/%d %I:%M %p").replace(
                            year=_mountain_now().year,
                            tzinfo=MOUNTAIN_TZ,
                        )
                    except ValueError:
                        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MOUNTAIN_TZ)


def _format_timestamp(value, style: str = "full") -> str:
    dt = _parse_timestamp(value)
    if not dt:
        return value or ""
    if style == "time":
        return dt.strftime("%-I:%M %p")
    if style == "compact":
        return dt.strftime("%-m/%-d %-I:%M %p")
    return dt.strftime("%a %-m/%-d %-I:%M %p")


def _display_agent(agent_name: str | None) -> str | None:
    if agent_name == "SideClaw":
        return "Claws"
    return agent_name


def _avatar_path(agent_name: str | None) -> str:
    agent = (_display_agent(agent_name) or "").lower()
    if agent == "claws":
        return "/static/avatars/claws.png"
    if agent == "crusty":
        return "/static/avatars/crusty.png"
    if agent == "gemini":
        return "/static/avatars/gemini.png"
    return ""


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


def _append_task_note(task: dict, text: str):
    note = (task.get("notes") or "").strip()
    task["notes"] = f"{note} | {text}" if note else text


def _clear_wait_fields(task: dict):
    task["waiting_on"] = None
    task["next_event"] = None
    task["next_check_at"] = None


def _apply_workflow_signal(task: dict, signal: str, detail: str = "", at: str | None = None):
    ts = at or datetime.now(timezone.utc).isoformat()
    task["last_signal_at"] = ts
    if signal == "worker_started":
        task["column"] = "in_progress"
        task["phase"] = "running"
        task["started_at"] = task.get("started_at") or ts
    elif signal in {"worker_progress", "cron_progress"}:
        task["column"] = "in_progress"
        task["phase"] = task.get("phase") or "running"
    elif signal in {"worker_completed", "cron_completed"}:
        if task.get("on_success") and "review" in str(task.get("on_success", "")).lower():
            task["column"] = "under_review"
            task["phase"] = "under_review"
        else:
            task["column"] = "completed"
            task["phase"] = "completed"
            task["completed_at"] = task.get("completed_at") or ts
        _clear_wait_fields(task)
    elif signal in {"worker_failed", "cron_failed", "timer_expired"}:
        task["column"] = "in_progress"
        task["phase"] = "blocked"
        task["waiting_on"] = "first_pass_diagnosis"
        task["next_event"] = "diagnosis_and_reroute"
        task["next_check_at"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    elif signal == "review_requested":
        task["column"] = "under_review"
        task["phase"] = "under_review"
        task["waiting_on"] = "review_approved_or_rejected"
        task["next_event"] = "review_decision"
    elif signal == "review_approved":
        task["column"] = "completed"
        task["phase"] = "completed"
        task["completed_at"] = task.get("completed_at") or ts
        _clear_wait_fields(task)
    elif signal == "review_rejected":
        task["column"] = "in_progress"
        task["phase"] = "blocked"
        task["waiting_on"] = "rework"
        task["next_event"] = "worker_started"
    if detail:
        _append_task_note(task, f"Signal {signal} @ {_format_timestamp(ts, 'compact')}: {detail}")


async def _brain_stats() -> dict:
    """Fetch Brain Daemon stats. Returns empty dict on failure."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BRAIN_URL}/api/stats")
            return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}


async def _brain_thinking() -> dict:
    """Fetch thinking tab data from Brain Daemon (B39)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BRAIN_URL}/api/thinking")
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
# Digest helpers
# ---------------------------------------------------------------------------

def _read_digest() -> list:
    """Read digest.json entries, newest first."""
    try:
        return json.loads(DIGEST_PATH.read_text())
    except Exception:
        return []


def _write_digest(entries: list):
    DIGEST_PATH.write_text(json.dumps(entries, indent=2))


async def _cron_jobs_raw() -> list:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{OPENCLAW_URL}/api/cron/jobs",
                headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}"}
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("jobs", [])
    except Exception:
        return []


async def _cron_jobs() -> list:
    """Fetch cron jobs from OpenClaw gateway."""
    jobs = await _cron_jobs_raw()
    result = []
    for j in jobs:
        next_ms = j.get("state", {}).get("nextRunAtMs")
        next_str = ""
        if next_ms:
            dt = datetime.fromtimestamp(next_ms / 1000, tz=timezone.utc).astimezone(MOUNTAIN_TZ)
            next_str = dt.strftime("%a %-I:%M %p")
        sched = j.get("schedule", {})
        sched_str = sched.get("expr", sched.get("kind", ""))
        result.append({
            "id": j.get("id"),
            "name": j.get("name", "Unnamed"),
            "enabled": j.get("enabled", True),
            "schedule": sched_str,
            "next_run": next_str,
        })
    return result


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
    agent_aliases = {"SideClaw": "Claws"}
    for task in kanban.get("tasks", []):
        agent = task.get("agent")
        display_agent = agent_aliases.get(agent, agent)
        if display_agent and task.get("column") == "in_progress":
            agents[display_agent] = {"status": "active", "task": task.get("title", ""), "model": task.get("model", "")}
    # Default agents
    for name in ["Claws", "Crusty", "Gemini"]:
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
        "now": _format_timestamp(_mountain_now(), "full"),
    })


# ---------------------------------------------------------------------------
# Activity feed helpers (file-based)
# ---------------------------------------------------------------------------

TOOL_ICONS = {
    "exec": "⚡", "Read": "📖", "Edit": "✏️", "Write": "📝",
    "web_search": "🔍", "web_fetch": "🌐", "cron": "⏰",
    "sessions_spawn": "🚀", "sessions_list": "📋", "session_status": "📊",
    "image": "🖼️", "process": "⚙️", "message": "💬",
}


def _read_activity() -> list:
    try:
        return json.loads(ACTIVITY_PATH.read_text())
    except Exception:
        return []


def _append_activity(event: dict):
    """Append one event to activity-feed.json, cap at ACTIVITY_MAX."""
    events = _read_activity()
    events.insert(0, event)
    if len(events) > ACTIVITY_MAX:
        events = events[:ACTIVITY_MAX]
    ACTIVITY_PATH.write_text(json.dumps(events, indent=2))


# ---------------------------------------------------------------------------
# Routes — Daily Digest
# ---------------------------------------------------------------------------

@app.get("/digest", response_class=HTMLResponse)
async def digest(request: Request):
    digests = _read_digest()
    cron = await _cron_jobs()
    now = datetime.now(timezone.utc).isoformat()
    return templates.TemplateResponse("digest.html", {
        "request": request,
        "digests": digests,
        "cron_jobs": cron,
        "now": now,
        "title": "Daily Digest — SideQuests Mission Control",
    })


@app.post("/api/digest/add")
async def digest_add(request: Request):
    """Add a new digest entry (called by cron sessions after completing work)."""
    body = await request.json()
    entries = _read_digest()
    entry = {
        "id": body.get("id", f"digest-{len(entries)+1:03d}"),
        "title": body.get("title", "Work Session"),
        "date": body.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        "session_type": body.get("session_type", "scheduled"),
        "emoji": body.get("emoji", "🦞"),
        "status": body.get("status", "completed"),
        "summary": body.get("summary", ""),
        "work_done": body.get("work_done", []),
        "ideas": body.get("ideas", []),
        "commit": body.get("commit"),
    }
    entries.insert(0, entry)  # newest first
    _write_digest(entries)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Routes — Activity Feed
# ---------------------------------------------------------------------------

@app.get("/activity", response_class=HTMLResponse)
async def activity(request: Request):
    now = datetime.now(timezone.utc).isoformat()
    return templates.TemplateResponse("activity.html", {
        "request": request,
        "now": now,
        "title": "Activity Feed — SideQuests Mission Control",
    })


@app.get("/api/activity/agents", response_class=HTMLResponse)
async def activity_agents():
    """Derive agent status from recent activity-feed.json entries."""
    events = _read_activity()
    kanban = _read_kanban()
    in_progress = {t.get("agent", ""): t for t in kanban.get("tasks", []) if t.get("column") == "in_progress" and t.get("agent")}

    # Find last-seen time per agent
    last_seen: dict[str, str] = {}
    for ev in events:
        raw_agent = ev.get("agent", "")
        agent = _display_agent(raw_agent.replace("🦀 ", "").replace("🦞 ", "").replace("🧠 ", "").replace("✨ ", ""))
        if agent and agent not in last_seen:
            last_seen[agent] = _format_timestamp(ev.get("ts_raw") or ev.get("ts", ""), "time")

    # Known agents — always show mission-control owners, plus any others seen recently
    agents = {
        "Claws": last_seen.get("Claws", ""),
        "Crusty": last_seen.get("Crusty", ""),
        "Gemini": last_seen.get("Gemini", ""),
    }
    for a in last_seen:
        if a not in agents:
            agents[a] = last_seen[a]

    html = ""
    for name, ts in agents.items():
        task = in_progress.get(name, {})
        is_active = bool(task)
        dot = "bg-green-500 animate-pulse" if is_active else ("bg-blue-500" if ts else "bg-slate-600")
        status_text = task.get("title", f"Last active: {ts}" if ts else "Idle")
        avatar = _avatar_path(name)
        html += f"""
        <div class="flex items-center space-x-3 bg-slate-800 rounded-lg px-4 py-3 border border-slate-700/50">
            <div class="relative">
                <img src="{avatar}" alt="{name}" class="w-9 h-9 rounded-full object-cover border border-slate-600" />
                <div class="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border border-slate-900 {dot}"></div>
            </div>
            <div>
                <div class="text-sm font-semibold text-slate-200">{name}</div>
                <div class="text-[11px] text-slate-500 truncate max-w-[220px]">{status_text}</div>
            </div>
        </div>"""

    if not html:
        html = '<div class="text-xs text-slate-500 italic px-2 py-3">No agent activity recorded yet.</div>'
    return HTMLResponse(html)


@app.get("/api/activity/feed", response_class=HTMLResponse)
async def activity_feed():
    events = _read_activity()
    if not events:
        return HTMLResponse(
            '<div class="p-8 text-center text-slate-500 italic text-sm">'
            'No activity yet — events appear here as agents work.</div>'
        )
    html = ""
    for ev in events[:100]:
        icon = TOOL_ICONS.get(ev.get("tool", ""), ev.get("icon", "🔧"))
        agent = ev.get("agent", "unknown")
        display_ts = _format_timestamp(ev.get("ts_raw") or ev.get("ts", ""), "time")
        agent_color = "text-blue-400" if ("SideClaw" in agent or "Claws" in agent) else "text-purple-400" if "Gemini" in agent else "text-amber-400"
        detail_color = "text-slate-300" if ev.get("type") == "message" else "text-slate-400"
        html += f"""
        <div class="flex items-start space-x-3 px-5 py-2.5 hover:bg-slate-700/20 transition-colors">
            <span class="text-slate-600 font-mono text-[10px] pt-0.5 w-20 flex-shrink-0">{display_ts}</span>
            <span class="{agent_color} font-semibold text-[11px] w-28 flex-shrink-0 truncate">{agent}</span>
            <span class="text-[13px] flex-shrink-0">{icon}</span>
            <span class="text-[11px] font-mono text-slate-400 flex-shrink-0 w-24 truncate">{ev.get('tool','')}</span>
            <span class="{detail_color} text-[11px] truncate">{ev.get('detail','')}</span>
        </div>"""
    return HTMLResponse(html)


@app.post("/api/activity/add")
async def activity_add(request: Request):
    """Add one or more events to the activity feed."""
    body = await request.json()
    events = body if isinstance(body, list) else [body]
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    for ev in events:
        ev.setdefault("ts", now_str)
        ev.setdefault("ts_raw", datetime.now(timezone.utc).isoformat())
        _append_activity(ev)
    return JSONResponse({"ok": True, "added": len(events)})


# ---------------------------------------------------------------------------
# Routes — Thinking (Brain integration)
# ---------------------------------------------------------------------------

@app.get("/thinking", response_class=HTMLResponse)
async def thinking(request: Request):
    brain_alive = await _brain_alive()
    now = datetime.now(timezone.utc).isoformat()

    # B39: Brain is now integrated — B28 tool binding is fixed
    brain_integrated = brain_alive

    thinking_data = {}
    decisions = []
    concepts = []
    constraints = []
    open_loops_count = 0
    stats = {}

    if brain_alive:
        thinking_data = await _brain_thinking()
        decisions = thinking_data.get("decisions", [])
        concepts = thinking_data.get("concepts", [])
        constraints = thinking_data.get("constraints", [])
        open_loops_count = thinking_data.get("open_loops_count", 0)
        stats = thinking_data.get("stats", {})

    return templates.TemplateResponse("thinking.html", {
        "request": request,
        "now": now,
        "brain_alive": brain_alive,
        "brain_integrated": brain_integrated,
        "stats": stats,
        "decisions": decisions,
        "concepts": concepts,
        "constraints": constraints,
        "open_loops_count": open_loops_count,
        "title": "Thinking — SideQuests Mission Control",
    })


# ---------------------------------------------------------------------------
# Routes — Kanban Board
# ---------------------------------------------------------------------------

@app.get("/board", response_class=HTMLResponse)
async def board(request: Request):
    now = _format_timestamp(_mountain_now(), "full")
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
        "phase": body.get("phase", "backlog"),
        "execution_mode": body.get("execution_mode"),
        "run_ref": body.get("run_ref"),
        "job_ref": body.get("job_ref"),
        "waiting_on": body.get("waiting_on"),
        "next_event": body.get("next_event"),
        "next_check_at": body.get("next_check_at"),
        "on_success": body.get("on_success"),
        "on_failure": body.get("on_failure"),
        "escalate_to": body.get("escalate_to"),
        "last_signal_at": body.get("last_signal_at"),
        "notes": body.get("notes", ""),
    }
    kanban["tasks"].append(task)
    _write_kanban(kanban)
    return JSONResponse({"ok": True, "task": task})


# ---------------------------------------------------------------------------
# Routes — API (workflow + HTMX partial updates)
# ---------------------------------------------------------------------------

@app.post("/api/workflow/signal")
async def workflow_signal(request: Request):
    body = await request.json()
    task_id = body.get("task_id")
    signal = body.get("signal")
    detail = body.get("detail", "")
    at = body.get("at") or datetime.now(timezone.utc).isoformat()
    if not task_id or not signal:
        return JSONResponse({"error": "task_id and signal are required"}, status_code=400)

    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") == task_id:
            _apply_workflow_signal(task, signal, detail=detail, at=at)
            _write_kanban(kanban)
            return JSONResponse({
                "ok": True,
                "task_id": task_id,
                "signal": signal,
                "phase": task.get("phase"),
                "column": task.get("column"),
            })
    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.post("/api/workflow/reconcile")
async def workflow_reconcile():
    kanban = _read_kanban()
    jobs = await _cron_jobs_raw()
    jobs_by_id = {j.get("id"): j for j in jobs}
    now = datetime.now(timezone.utc)
    updates = []

    for task in kanban.get("tasks", []):
        task_id = task.get("id")
        if task.get("column") == "completed":
            continue

        job_id = task.get("job_ref")
        if job_id and job_id in jobs_by_id:
            job = jobs_by_id[job_id]
            state = job.get("state", {})
            last_run_ms = state.get("lastRunAtMs")
            last_signal = _parse_timestamp(task.get("last_signal_at"))
            if last_run_ms:
                last_run_dt = datetime.fromtimestamp(last_run_ms / 1000, tz=timezone.utc)
                if not last_signal or last_run_dt > last_signal.astimezone(timezone.utc):
                    status = state.get("lastRunStatus") or state.get("lastStatus")
                    detail = state.get("lastError", "") if status == "error" else f"Cron job {job.get('name', job_id)} completed"
                    signal = "cron_failed" if status == "error" else "cron_completed"
                    _apply_workflow_signal(task, signal, detail=detail, at=last_run_dt.isoformat())
                    updates.append({"task_id": task_id, "signal": signal})
                    continue

        next_check = _parse_timestamp(task.get("next_check_at"))
        if next_check and next_check.astimezone(timezone.utc) <= now and task.get("phase") not in {"completed", "under_review"}:
            _apply_workflow_signal(task, "timer_expired", detail="Checkpoint expired without a newer completion signal", at=now.isoformat())
            updates.append({"task_id": task_id, "signal": "timer_expired"})

    if updates:
        _write_kanban(kanban)
    return JSONResponse({"ok": True, "updates": updates, "count": len(updates)})


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
