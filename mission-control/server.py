"""
SideQuests Mission Control — Local dashboard for monitoring agents,
brain health, and task progress.

Run: python mission-control/server.py
Serves: http://127.0.0.1:7800
"""

import json
import os
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
OPENCLAW_TOKEN = "0365c314e1df16b969f91da30f6efc5b226d2ac3c894643980e6781e943e43c8"
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


RISK_TIER_META = {
    "tier0_auto": {
        "label": "Tier 0 · Auto",
        "short": "T0 Auto",
        "classes": "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
    },
    "tier1_crusty_review": {
        "label": "Tier 1 · Crusty Review",
        "short": "T1 Review",
        "classes": "text-amber-300 bg-amber-500/10 border-amber-500/20",
    },
    "tier2_crusty_decide": {
        "label": "Tier 2 · Crusty Decides",
        "short": "T2 Decide",
        "classes": "text-orange-300 bg-orange-500/10 border-orange-500/20",
    },
    "tier3_dj_required": {
        "label": "Tier 3 · DJ Required",
        "short": "T3 DJ",
        "classes": "text-rose-300 bg-rose-500/10 border-rose-500/20",
    },
}

CRUSTY_DECISION_META = {
    "approve": {
        "label": "Approved",
        "short": "Approved",
        "classes": "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
    },
    "approve_with_guardrails": {
        "label": "Approve w/ Guardrails",
        "short": "Guardrails",
        "classes": "text-cyan-300 bg-cyan-500/10 border-cyan-500/20",
    },
    "reroute": {
        "label": "Rerouted",
        "short": "Reroute",
        "classes": "text-violet-300 bg-violet-500/10 border-violet-500/20",
    },
    "elevate_to_dj": {
        "label": "Elevate to DJ",
        "short": "Elevate",
        "classes": "text-rose-300 bg-rose-500/10 border-rose-500/20",
    },
}


def _risk_tier_meta(value: str | None) -> dict | None:
    if not value:
        return None
    return RISK_TIER_META.get(value, {
        "label": value.replace("_", " ").title(),
        "short": value.replace("_", " ").title(),
        "classes": "text-slate-300 bg-slate-700/40 border-slate-600/30",
    })


def _crusty_decision_meta(value: str | None) -> dict | None:
    if not value:
        return None
    return CRUSTY_DECISION_META.get(value, {
        "label": value.replace("_", " ").title(),
        "short": value.replace("_", " ").title(),
        "classes": "text-slate-300 bg-slate-700/40 border-slate-600/30",
    })


PERSISTENT_STATE_META = {
    "operational": {
        "label": "Persistent Operational Loop",
        "short": "Ops Loop",
        "classes": "text-cyan-300 bg-cyan-500/10 border-cyan-500/20",
    },
    "watching": {
        "label": "Watching",
        "short": "Watching",
        "classes": "text-sky-300 bg-sky-500/10 border-sky-500/20",
    },
    "persistent": {
        "label": "Persistent",
        "short": "Persistent",
        "classes": "text-teal-300 bg-teal-500/10 border-teal-500/20",
    },
}


def _persistent_state_meta(value: str | None) -> dict | None:
    if not value:
        return None
    return PERSISTENT_STATE_META.get(value, {
        "label": value.replace("_", " ").title(),
        "short": value.replace("_", " ").title(),
        "classes": "text-cyan-300 bg-cyan-500/10 border-cyan-500/20",
    })


def _board_state_badges(task: dict) -> list[dict]:
    badges = []
    phase = str(task.get("phase") or "")
    waiting_on = str(task.get("waiting_on") or "")

    if task.get("column") != "completed" and (phase in {"blocked", "chain_blocked"} or waiting_on):
        detail = waiting_on.replace("_", " ") if waiting_on else phase.replace("_", " ")
        badges.append({
            "label": "Blocked",
            "short": "Blocked",
            "detail": detail,
            "classes": "text-red-300 bg-red-500/10 border-red-500/20",
        })

    if task.get("dj_decision_required") or task.get("risk_tier") == "tier3_dj_required" or task.get("crusty_decision") == "elevate_to_dj":
        badges.append({
            "label": "DJ Decision Needed",
            "short": "DJ Needed",
            "detail": task.get("dj_decision_question") or task.get("crusty_dj_question") or "",
            "classes": "text-fuchsia-300 bg-fuchsia-500/10 border-fuchsia-500/20",
        })

    risk_meta = _risk_tier_meta(task.get("risk_tier"))
    if risk_meta:
        badges.append({
            "label": risk_meta["label"],
            "short": risk_meta["short"],
            "detail": task.get("risk_reason") or "",
            "classes": risk_meta["classes"],
        })

    decision_meta = _crusty_decision_meta(task.get("crusty_decision"))
    if decision_meta:
        badges.append({
            "label": decision_meta["label"],
            "short": decision_meta["short"],
            "detail": task.get("crusty_rationale") or "",
            "classes": decision_meta["classes"],
        })

    persistent_meta = _persistent_state_meta(task.get("persistent_state"))
    if persistent_meta:
        badges.append({
            "label": persistent_meta["label"],
            "short": persistent_meta["short"],
            "detail": task.get("persistent_state_reason") or "",
            "classes": persistent_meta["classes"],
        })

    return badges


def _jinja_execution_handles(task: dict) -> list[dict]:
    """Jinja2 filter: extract execution handles with short display values."""
    handles = _get_execution_handles(task)
    for h in handles:
        val = str(h["value"])
        # Shorten UUIDs (8-4-4-4-12) to first 8 chars
        if len(val) == 36 and val.count("-") == 4:
            h["short"] = val[:8]
        elif len(val) > 16:
            h["short"] = val[:12] + "..."
        else:
            h["short"] = val
    return handles


templates.env.filters["execution_handles"] = _jinja_execution_handles
templates.env.filters["risk_tier_meta"] = _risk_tier_meta
templates.env.filters["crusty_decision_meta"] = _crusty_decision_meta
templates.env.filters["persistent_state_meta"] = _persistent_state_meta
templates.env.filters["board_state_badges"] = _board_state_badges
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

DISCORD_CHANNELS = {
    "anchor": "mission-control",
    "blocked": "blocked-decisions",
    "shiplog": "ship-log",
    "intake": "work-intake",
}


def _discord_card_url(task: dict) -> str:
    task_id = task.get("id", "")
    return f"http://127.0.0.1:{PORT}/board?card={task_id}" if task_id else f"http://127.0.0.1:{PORT}/board"


def _discord_thread_slug(task: dict) -> str:
    task_id = str(task.get("id") or "CARD")
    title = str(task.get("title") or "work")
    words = re.findall(r"[a-z0-9]+", title.lower())
    slug = "-".join(words[:3]) or "work"
    return f"{task_id} · {slug}"


def _discord_thread_needed(task: dict) -> bool:
    explicit = task.get("discord_thread_needed")
    if explicit is not None:
        return bool(explicit)
    if task.get("priority") == "critical":
        return True
    if task.get("card_type") == "implementation":
        return True
    phase = str(task.get("phase") or "")
    return phase in {"implementation", "running", "blocked", "under_review", "chain_blocked"}


def _discord_meaningful_card(task: dict) -> bool:
    column = str(task.get("column") or "")
    phase = str(task.get("phase") or "")
    if column in {"in_progress", "under_review", "completed"}:
        return True
    if task.get("priority") in {"high", "critical"}:
        return True
    return phase in {"implementation", "running", "blocked", "under_review", "chain_blocked", "completed"}


def _discord_anchor_status(task: dict) -> str:
    return str(task.get("phase") or task.get("column") or "unknown")


def _discord_anchor_message(task: dict) -> str:
    lines = [
        f"[{task.get('id')}] {task.get('title')}",
        f"Owner: {task.get('agent') or 'unassigned'}",
        f"Phase: {_discord_anchor_status(task)}",
        f"Priority: {task.get('priority') or 'medium'}",
    ]
    goal = task.get("notes") or task.get("on_success") or ""
    goal = str(goal).split("|")[0].strip()
    if goal:
        lines.append(f"Goal: {goal}")
    if task.get("next_event"):
        lines.append(f"Next: {task.get('next_event')}")
    lines.append(f"Thread: {'needed' if _discord_thread_needed(task) else 'not needed yet'}")
    lines.append(f"Card: {_discord_card_url(task)}")
    return "\n".join(lines)


def _discord_blocker_message(task: dict) -> str:
    lines = [
        f"[BLOCKED][{task.get('id')}] {task.get('title')}",
        f"Waiting on: {task.get('waiting_on') or 'unknown'}",
    ]
    if task.get("next_event"):
        lines.append(f"Decision / next event: {task.get('next_event')}")
    if task.get("on_failure"):
        lines.append(f"Impact: {task.get('on_failure')}")
    if task.get("next_check_at"):
        lines.append(f"Next check: {_format_timestamp(task.get('next_check_at'), 'compact')}")
    lines.append(f"Context: {_discord_card_url(task)}")
    return "\n".join(lines)


def _discord_completion_message(task: dict) -> str:
    lines = [
        f"[DONE][{task.get('id')}] {task.get('title')}",
        f"Owner: {task.get('agent') or 'unassigned'}",
    ]
    result = task.get("notes") or task.get("on_success") or "Completed"
    result = str(result).split("|")[0].strip()
    lines.append(f"Result: {result}")
    artifact = task.get("spec_path") or (f"commit {task.get('commit')}" if task.get("commit") else None)
    if artifact:
        lines.append(f"Artifact: {artifact}")
    if task.get("chain_next"):
        lines.append(f"Follow-on: {len(task.get('chain_next') or [])} chained template(s) remain")
    elif task.get("on_success"):
        lines.append(f"Follow-on: {task.get('on_success')}")
    lines.append(f"Card: {_discord_card_url(task)}")
    return "\n".join(lines)


def _discord_hook_plan(task: dict, signal: str | None = None) -> list[dict]:
    actions = []
    if not _discord_meaningful_card(task):
        return actions

    if task.get("column") != "completed":
        anchor_mode = "update" if task.get("discord_anchor_message_id") else "create"
        actions.append({
            "kind": "anchor",
            "channel": DISCORD_CHANNELS["anchor"],
            "mode": anchor_mode,
            "title": f"[{task.get('id')}] {task.get('title')}",
            "thread_needed": _discord_thread_needed(task),
            "thread_name": _discord_thread_slug(task) if _discord_thread_needed(task) else None,
            "body": _discord_anchor_message(task),
        })

    phase = str(task.get("phase") or "")
    if task.get("column") != "completed" and (phase in {"blocked", "chain_blocked"} or task.get("waiting_on")):
        blocker_mode = "update" if task.get("discord_blocked_message_id") else "create"
        actions.append({
            "kind": "blocker",
            "channel": DISCORD_CHANNELS["blocked"],
            "mode": blocker_mode,
            "body": _discord_blocker_message(task),
        })

    if task.get("column") == "completed" or phase == "completed" or signal in {"worker_completed", "cron_completed", "review_approved"}:
        ship_mode = "update" if task.get("discord_shiplog_message_id") else "create"
        actions.append({
            "kind": "completion",
            "channel": DISCORD_CHANNELS["shiplog"],
            "mode": ship_mode,
            "body": _discord_completion_message(task),
        })
        if task.get("discord_anchor_message_id"):
            actions.append({
                "kind": "anchor_reply",
                "channel": DISCORD_CHANNELS["anchor"],
                "mode": "reply",
                "body": f"Resolved: [{task.get('id')}] {task.get('title')} is complete. See #{DISCORD_CHANNELS['shiplog']} for the summary.",
            })
    return actions


DISCORD_CHANNEL_ENV_KEYS = {
    DISCORD_CHANNELS["anchor"]: "MISSION_CONTROL_DISCORD_CHANNEL_MISSION_CONTROL",
    DISCORD_CHANNELS["blocked"]: "MISSION_CONTROL_DISCORD_CHANNEL_BLOCKED_DECISIONS",
    DISCORD_CHANNELS["shiplog"]: "MISSION_CONTROL_DISCORD_CHANNEL_SHIP_LOG",
    DISCORD_CHANNELS["intake"]: "MISSION_CONTROL_DISCORD_CHANNEL_WORK_INTAKE",
}


class DiscordAdapterError(RuntimeError):
    """Mission Control Discord adapter failure."""


def _discord_adapter_enabled() -> bool:
    return os.getenv("MISSION_CONTROL_DISCORD_ENABLE_WRITES", "").lower() in {"1", "true", "yes", "on"}


def _discord_auto_execute_enabled() -> bool:
    return os.getenv("MISSION_CONTROL_DISCORD_AUTO_EXECUTE", "").lower() in {"1", "true", "yes", "on"}


def _discord_config_status() -> dict:
    missing = []
    if not _discord_adapter_enabled():
        missing.append("MISSION_CONTROL_DISCORD_ENABLE_WRITES=1")
    if not os.getenv("MISSION_CONTROL_DISCORD_BOT_TOKEN", "").strip():
        missing.append("MISSION_CONTROL_DISCORD_BOT_TOKEN")
    for env_key in DISCORD_CHANNEL_ENV_KEYS.values():
        if not os.getenv(env_key, "").strip():
            missing.append(env_key)
    return {
        "writes_enabled": _discord_adapter_enabled(),
        "auto_execute_enabled": _discord_auto_execute_enabled(),
        "ready": len(missing) == 0,
        "missing": missing,
        "first_missing": missing[0] if missing else None,
        "ready_for_live_execute": len(missing) == 0,
    }


def _discord_state_snapshot(task: dict) -> dict:
    return {
        "discord_anchor_channel": task.get("discord_anchor_channel"),
        "discord_anchor_message_id": task.get("discord_anchor_message_id"),
        "discord_thread_id": task.get("discord_thread_id"),
        "discord_thread_state": task.get("discord_thread_state"),
        "discord_blocked_message_id": task.get("discord_blocked_message_id"),
        "discord_shiplog_message_id": task.get("discord_shiplog_message_id"),
    }


def _discord_channel_id(channel_name: str) -> str | None:
    env_key = DISCORD_CHANNEL_ENV_KEYS.get(channel_name)
    return os.getenv(env_key, "").strip() or None if env_key else None


def _discord_api_headers() -> dict:
    token = os.getenv("MISSION_CONTROL_DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise DiscordAdapterError("MISSION_CONTROL_DISCORD_BOT_TOKEN is not configured")
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "mission-control-discord-adapter/0.1",
    }


async def _discord_api_request(method: str, path: str, payload: dict | None = None, client: httpx.AsyncClient | None = None) -> dict:
    own_client = client is None
    client = client or httpx.AsyncClient(base_url="https://discord.com/api/v10", timeout=20.0)
    try:
        resp = await client.request(method, path, headers=_discord_api_headers(), json=payload)
        resp.raise_for_status()
        if not resp.text:
            return {}
        return resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise DiscordAdapterError(f"Discord API {method} {path} failed: {exc.response.status_code} {detail}") from exc
    finally:
        if own_client:
            await client.aclose()


def _discord_apply_persisted_ids(task: dict, action: dict, result: dict):
    kind = action.get("kind")
    if kind == "anchor" and result.get("message_id"):
        task["discord_anchor_channel"] = action.get("channel")
        task["discord_anchor_message_id"] = result.get("message_id")
    elif kind == "blocker" and result.get("message_id"):
        task["discord_blocked_message_id"] = result.get("message_id")
    elif kind == "completion" and result.get("message_id"):
        task["discord_shiplog_message_id"] = result.get("message_id")
    if result.get("thread_id"):
        task["discord_thread_id"] = result.get("thread_id")
        task["discord_thread_state"] = result.get("thread_state") or "open"


async def _execute_discord_hook_action(task: dict, action: dict, client: httpx.AsyncClient | None = None) -> dict:
    channel_name = action.get("channel")
    channel_id = _discord_channel_id(channel_name)
    if not channel_id:
        raise DiscordAdapterError(f"Discord channel id is not configured for {channel_name}")

    kind = action.get("kind")
    content = action.get("body", "")
    result = {
        "kind": kind,
        "channel": channel_name,
        "channel_id": channel_id,
        "mode": action.get("mode"),
    }

    if kind == "anchor":
        if action.get("mode") == "update" and task.get("discord_anchor_message_id"):
            message_id = task.get("discord_anchor_message_id")
            payload = await _discord_api_request("PATCH", f"/channels/{channel_id}/messages/{message_id}", {"content": content}, client=client)
        else:
            payload = await _discord_api_request("POST", f"/channels/{channel_id}/messages", {"content": content}, client=client)
            message_id = payload.get("id")
        result["message_id"] = message_id

        if action.get("thread_needed") and not task.get("discord_thread_id") and message_id:
            thread_payload = await _discord_api_request(
                "POST",
                f"/channels/{channel_id}/messages/{message_id}/threads",
                {
                    "name": action.get("thread_name") or _discord_thread_slug(task),
                    "auto_archive_duration": 1440,
                },
                client=client,
            )
            result["thread_id"] = thread_payload.get("id")
            result["thread_state"] = "open"
    elif kind == "blocker":
        if action.get("mode") == "update" and task.get("discord_blocked_message_id"):
            message_id = task.get("discord_blocked_message_id")
            await _discord_api_request("PATCH", f"/channels/{channel_id}/messages/{message_id}", {"content": content}, client=client)
        else:
            payload = await _discord_api_request("POST", f"/channels/{channel_id}/messages", {"content": content}, client=client)
            message_id = payload.get("id")
        result["message_id"] = message_id
    elif kind == "completion":
        if action.get("mode") == "update" and task.get("discord_shiplog_message_id"):
            message_id = task.get("discord_shiplog_message_id")
            await _discord_api_request("PATCH", f"/channels/{channel_id}/messages/{message_id}", {"content": content}, client=client)
        else:
            payload = await _discord_api_request("POST", f"/channels/{channel_id}/messages", {"content": content}, client=client)
            message_id = payload.get("id")
        result["message_id"] = message_id
        if task.get("discord_thread_id"):
            result["thread_id"] = task.get("discord_thread_id")
            result["thread_state"] = "ready_to_archive"
    elif kind == "anchor_reply":
        if not task.get("discord_anchor_message_id"):
            raise DiscordAdapterError("anchor_reply requested but card has no discord_anchor_message_id")
        payload = await _discord_api_request(
            "POST",
            f"/channels/{channel_id}/messages",
            {
                "content": content,
                "message_reference": {
                    "channel_id": channel_id,
                    "message_id": task.get("discord_anchor_message_id"),
                },
            },
            client=client,
        )
        result["message_id"] = payload.get("id")
    else:
        raise DiscordAdapterError(f"Unsupported discord hook kind: {kind}")

    return result


async def _execute_discord_hook_plan(task: dict, plan: list[dict], dry_run: bool = True, client: httpx.AsyncClient | None = None) -> list[dict]:
    results = []
    for action in plan:
        if dry_run:
            result = {
                "kind": action.get("kind"),
                "channel": action.get("channel"),
                "mode": action.get("mode"),
                "dry_run": True,
                "would_persist": {
                    "anchor": ["discord_anchor_channel", "discord_anchor_message_id", "discord_thread_id", "discord_thread_state"],
                    "blocker": ["discord_blocked_message_id"],
                    "completion": ["discord_shiplog_message_id", "discord_thread_state"],
                    "anchor_reply": [],
                }.get(action.get("kind"), []),
            }
        else:
            result = await _execute_discord_hook_action(task, action, client=client)
            _discord_apply_persisted_ids(task, action, result)
            result["dry_run"] = False
        results.append(result)
    return results


async def _maybe_auto_execute_discord(task: dict, signal: str | None, kanban: dict) -> dict:
    plan = _discord_hook_plan(task, signal=signal)
    status = _discord_config_status()
    if not plan:
        return {"attempted": False, "reason": "no_discord_actions", "hooks": []}
    if not _discord_auto_execute_enabled():
        return {"attempted": False, "reason": "auto_execute_disabled", "hooks": plan, "config": status}
    if not status["ready"]:
        return {"attempted": False, "reason": "discord_not_configured", "hooks": plan, "config": status}

    results = await _execute_discord_hook_plan(task, plan, dry_run=False)
    _write_kanban(kanban)
    return {
        "attempted": True,
        "ok": True,
        "hooks": plan,
        "executed": results,
        "config": status,
        "discord_state": {
            "discord_anchor_channel": task.get("discord_anchor_channel"),
            "discord_anchor_message_id": task.get("discord_anchor_message_id"),
            "discord_thread_id": task.get("discord_thread_id"),
            "discord_thread_state": task.get("discord_thread_state"),
            "discord_blocked_message_id": task.get("discord_blocked_message_id"),
            "discord_shiplog_message_id": task.get("discord_shiplog_message_id"),
        },
    }


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


MAX_SIGNAL_NOTES = 10  # keep only the N most recent signal notes on loop cards


def _write_kanban(data: dict):
    """Write kanban.json atomically via temp file + rename."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Cap signal notes on loop cards to prevent unbounded growth
    for task in data.get("tasks", []):
        if task.get("card_type") == "loop":
            _cap_signal_notes(task)
    tmp = KANBAN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(KANBAN_PATH)  # atomic rename on POSIX


def _append_task_note(task: dict, text: str):
    note = (task.get("notes") or "").strip()
    task["notes"] = f"{note} | {text}" if note else text


def _cap_signal_notes(task: dict):
    """Trim signal notes on loop cards, keeping the base note + last N signals."""
    notes = (task.get("notes") or "").strip()
    if not notes:
        return
    parts = notes.split(" | ")
    # First segment(s) before any "Signal " entry are the base description
    base_parts = []
    signal_parts = []
    for p in parts:
        if p.startswith("Signal ") and base_parts:
            signal_parts.append(p)
        else:
            base_parts.append(p)
    if len(signal_parts) > MAX_SIGNAL_NOTES:
        signal_parts = signal_parts[-MAX_SIGNAL_NOTES:]
    all_parts = base_parts + signal_parts
    task["notes"] = " | ".join(all_parts)


def _clear_wait_fields(task: dict):
    task["waiting_on"] = None
    task["next_event"] = None
    task["next_check_at"] = None


def _active_card(task: dict) -> bool:
    return task.get("column") not in {"completed", "backlog"}


_GENERIC_LAST_MILE_WAITS = {"", "unknown", "todo", "tbd", "something", "pending"}


def _normalize_visible_result(task: dict):
    """Backfill visible_result from on_success when older cards only carry narrative success text."""
    if task.get("visible_result"):
        return
    fallback = str(task.get("on_success") or "").strip()
    if fallback:
        task["visible_result"] = fallback


def _last_mile_gaps(task: dict) -> list[str]:
    """Return missing operational requirements for active cards under MC-027."""
    if not _active_card(task):
        return []

    gaps = []
    next_event = str(task.get("next_event") or "").strip()
    waiting_on = str(task.get("waiting_on") or "").strip()
    visible_result = str(task.get("visible_result") or task.get("on_success") or "").strip()

    if not next_event:
        gaps.append("missing_last_mile_next_event")
    if not visible_result:
        gaps.append("missing_visible_result")
    if str(task.get("phase") or "") == "blocked" and waiting_on.lower() in _GENERIC_LAST_MILE_WAITS:
        gaps.append("missing_named_blocker")

    return gaps


def _block_for_last_mile_gap(task: dict, gaps: list[str], ts: str):
    """Operationally enforce the last-mile rule by routing stale cards into an explicit repair state."""
    task["column"] = "in_progress"
    task["phase"] = "blocked"
    primary = gaps[0] if gaps else "workflow_repair"
    repair_event = {
        "missing_last_mile_next_event": "name_last_mile_next_event",
        "missing_visible_result": "define_visible_result",
        "missing_named_blocker": "name_blocker_and_next_event",
    }.get(primary, "repair_last_mile_workflow")
    task["waiting_on"] = primary
    task["next_event"] = repair_event
    task["next_check_at"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    _append_task_note(task, f"MC-027 repair @ {_format_timestamp(ts, 'compact')}: {', '.join(gaps)}")


# ---------------------------------------------------------------------------
# Execution handles — first-class lifecycle state (MC-006B)
# ---------------------------------------------------------------------------

# Recognized handle types and their display labels
HANDLE_TYPES = {
    "run_ref": "Run",
    "job_ref": "Job",
    "session_ref": "Session",
    "process_ref": "Process",
}

HANDLE_STATUS_CLASSES = {
    "active": "text-green-400",
    "pending": "text-amber-400",
    "completed": "text-slate-500",
    "failed": "text-red-400",
    "stale": "text-orange-400",
    "unknown": "text-slate-600",
}


def _get_execution_handles(task: dict) -> list[dict]:
    """Extract all non-null execution handles from a task as structured objects."""
    handles = []
    for field, label in HANDLE_TYPES.items():
        value = task.get(field)
        if value:
            handles.append({
                "field": field,
                "label": label,
                "value": value,
                "status": _infer_handle_status(task, field),
            })
    return handles


def _infer_handle_status(task: dict, handle_field: str) -> str:
    """Infer the status of an execution handle from the card's lifecycle state."""
    phase = task.get("phase", "")
    column = task.get("column", "")
    if column == "completed" or phase == "completed":
        return "completed"
    if phase == "blocked":
        return "stale"
    if phase in ("running", "in_progress") or column == "in_progress":
        return "active"
    if phase in ("ready", "backlog"):
        return "pending"
    return "unknown"


def _set_handle_from_signal(task: dict, signal_data: dict):
    """Update execution handle fields from signal payload data."""
    for field in HANDLE_TYPES:
        if field in signal_data and signal_data[field] is not None:
            task[field] = signal_data[field]


def _is_rate_limit_error(detail: str) -> bool:
    """Detect rate limit / quota errors in cron job error messages."""
    if not detail:
        return False
    lowered = detail.lower()
    return any(kw in lowered for kw in [
        "rate limit", "rate_limit", "ratelimit",
        "429", "too many requests",
        "quota", "throttl",
        "tokens per min", "requests per min",
    ])


def _retry_time_from_error(detail: str, fallback_at: str | None = None) -> str | None:
    """Extract a retry/reset timestamp from an error message, or use fallback.

    Looks for patterns like 'retry after 2026-03-23T10:00:00Z' or
    'reset at 1711234567' (unix epoch) in the detail string.
    """
    if detail:
        # ISO-8601 timestamp after "retry" or "reset"
        m = re.search(r'(?:retry|reset)[^\d]*(20\d{2}-\d{2}-\d{2}T[\d:.]+Z?)', detail, re.IGNORECASE)
        if m:
            return m.group(1)
        # Unix epoch seconds after "retry" or "reset"
        m = re.search(r'(?:retry|reset)[^\d]*(\d{10,13})\b', detail, re.IGNORECASE)
        if m:
            epoch = int(m.group(1))
            if epoch > 1e12:  # milliseconds
                epoch = epoch / 1000
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    return fallback_at


def _is_handle_stale(task: dict, now: datetime, stale_hours: int = 6) -> bool:
    """Check if a task's execution handles look stale based on last_signal_at."""
    if task.get("column") == "completed":
        return False
    handles = _get_execution_handles(task)
    if not handles:
        return False
    last_signal = _parse_timestamp(task.get("last_signal_at"))
    if not last_signal:
        return True  # has handles but no signal timestamp
    return (now - last_signal.astimezone(timezone.utc)) > timedelta(hours=stale_hours)


# ---------------------------------------------------------------------------
# chain_next — declarative follow-on chaining (MC-006C)
# ---------------------------------------------------------------------------

MAX_CHAIN_DEPTH = 3
_CHAIN_SUCCESS_SIGNALS = {"worker_completed", "cron_completed", "review_approved"}


def _check_chain_guardrails(
    template: dict, completing_task: dict, depth: int
) -> tuple[bool, str]:
    """Return (ok, reason). If ok is False, reason explains the blocked guardrail."""
    # G1: template exists — caller already checked chain_next[0]
    # G3: same-agent
    if template.get("agent") != completing_task.get("agent"):
        return False, f"Cross-agent handoff: completing agent={completing_task.get('agent')}, next agent={template.get('agent')}"
    # G4: not critical priority
    if template.get("priority") == "critical":
        return False, f"Next card priority is critical ({template.get('id')})"
    # G5: no review-mode execution
    if "review" in str(template.get("execution_mode", "")).lower():
        return False, f"Next card execution_mode contains review ({template.get('execution_mode')})"
    # G6: depth limit
    if depth + 1 > MAX_CHAIN_DEPTH:
        return False, f"Chain depth would be {depth + 1}, exceeds max {MAX_CHAIN_DEPTH}"
    return True, ""


def _create_card_from_chain_template(
    template: dict, parent_id: str, depth: int, ts: str
) -> dict:
    """Create a new card dict from a chain_next template."""
    return {
        "id": template["id"],
        "title": template["title"],
        "backlog_ref": template.get("backlog_ref"),
        "column": "in_progress",
        "priority": template["priority"],
        "agent": template["agent"],
        "model": template.get("model"),
        "started_at": ts,
        "completed_at": None,
        "commit": None,
        "rollback_commit": None,
        "phase": "running",
        "execution_mode": template["execution_mode"],
        "run_ref": None,
        "job_ref": None,
        "session_ref": None,
        "process_ref": None,
        "waiting_on": None,
        "next_event": None,
        "next_check_at": None,
        "on_success": template.get("on_success"),
        "on_failure": template.get("on_failure"),
        "escalate_to": template.get("escalate_to"),
        "last_signal_at": ts,
        "notes": template.get("notes", ""),
        "chain_next": template.get("chain_next", []),
        "chain_depth": depth + 1,
        "chained_from": parent_id,
    }


def _block_for_chain_approval(task: dict, reason: str, ts: str):
    """Move a completing card into chain_blocked waiting state."""
    task["column"] = "under_review"
    task["phase"] = "chain_blocked"
    task["waiting_on"] = "chain_approval"
    task["next_event"] = "chain_approval_decision"
    task["next_check_at"] = None
    _append_task_note(task, f"Chain blocked @ {_format_timestamp(ts, 'compact')}: {reason}")


def _log_chain_to_digest(parent_id: str, new_card: dict, guardrails_ok: bool, depth: int):
    """Log an auto-chained card creation to digest.json."""
    entries = _read_digest()
    entry = {
        "id": f"chain-{parent_id}-{new_card['id']}",
        "title": f"Auto-chained: {parent_id} → {new_card['id']}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "session_type": "auto_chain",
        "emoji": "🔗",
        "status": "completed",
        "summary": f"Card {new_card['id']} ({new_card['title']}) auto-created from {parent_id}. Chain depth: {depth}. All guardrails passed: {guardrails_ok}.",
        "work_done": [
            f"Source card: {parent_id}",
            f"New card: {new_card['id']} — {new_card['title']}",
            f"Agent: {new_card.get('agent')}",
            f"Priority: {new_card.get('priority')}",
            f"Chain depth: {depth}",
        ],
        "ideas": [],
        "commit": None,
    }
    entries.insert(0, entry)
    _write_digest(entries)


def _try_chain_next(task: dict, signal: str, tasks: list, ts: str) -> dict | None:
    """Evaluate chain_next after a completion signal. Returns new card or None.

    Mutates task (removes chain_next[0] on success, blocks on guardrail failure).
    Appends new card to tasks list on success.
    """
    # G2: success signals only
    if signal not in _CHAIN_SUCCESS_SIGNALS:
        return None
    chain = task.get("chain_next")
    if not chain or not isinstance(chain, list) or len(chain) == 0:
        return None

    template = chain[0]
    if not template.get("id") or not template.get("title"):
        return None

    depth = task.get("chain_depth", 0)
    ok, reason = _check_chain_guardrails(template, task, depth)

    if not ok:
        _block_for_chain_approval(task, reason, ts)
        return None

    # All guardrails pass — create the chained card
    new_card = _create_card_from_chain_template(template, task["id"], depth, ts)

    # Check for ID collision
    existing_ids = {t.get("id") for t in tasks}
    if new_card["id"] in existing_ids:
        _block_for_chain_approval(task, f"Card ID {new_card['id']} already exists on the board", ts)
        return None

    # Remove consumed template from parent
    task["chain_next"] = chain[1:]

    # Append to board
    tasks.append(new_card)

    # Log to digest
    _log_chain_to_digest(task["id"], new_card, True, depth + 1)

    _append_task_note(task, f"Auto-chained → {new_card['id']} ({new_card['title']}) @ {_format_timestamp(ts, 'compact')}")

    return new_card


# ---------------------------------------------------------------------------
# Workflow signal application
# ---------------------------------------------------------------------------

def _apply_workflow_signal(task: dict, signal: str, detail: str = "", at: str | None = None, tasks: list | None = None, handle_updates: dict | None = None):
    """Apply a workflow signal to a task. If tasks list is provided, chain_next evaluation runs on completion signals.
    handle_updates: optional dict with run_ref/job_ref/session_ref/process_ref to set on the task."""
    ts = at or datetime.now(timezone.utc).isoformat()
    task["last_signal_at"] = ts
    _normalize_visible_result(task)

    # Propagate any execution handle updates from the signal payload
    if handle_updates:
        _set_handle_from_signal(task, handle_updates)

    if signal == "worker_started":
        task["column"] = "in_progress"
        task["phase"] = "running"
        task["started_at"] = task.get("started_at") or ts
    elif signal in {"worker_progress", "cron_progress"}:
        task["column"] = "in_progress"
        task["phase"] = task.get("phase") or "running"
    elif signal in {"worker_completed", "cron_completed"}:
        visible_result = str(task.get("visible_result") or task.get("on_success") or "").strip()
        if task.get("on_success") and "review" in str(task.get("on_success", "")).lower():
            task["column"] = "under_review"
            task["phase"] = "under_review"
        elif not visible_result:
            task["column"] = "in_progress"
            task["phase"] = "blocked"
            task["waiting_on"] = "missing_visible_result"
            task["next_event"] = "define_visible_result_or_name_blocker"
            task["next_check_at"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        else:
            task["column"] = "completed"
            task["phase"] = "completed"
            task["completed_at"] = task.get("completed_at") or ts
            task["visible_result_confirmed_at"] = task.get("visible_result_confirmed_at") or ts
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
    elif signal == "rate_limited":
        task["column"] = "in_progress"
        task["phase"] = "blocked"
        task["waiting_on"] = "rate_limit_reset"
        task["next_event"] = "retry_after_reset"
    elif signal == "review_rejected":
        task["column"] = "in_progress"
        task["phase"] = "blocked"
        task["waiting_on"] = "rework"
        task["next_event"] = "worker_started"
    if detail:
        _append_task_note(task, f"Signal {signal} @ {_format_timestamp(ts, 'compact')}: {detail}")

    # chain_next evaluation — only when tasks list is available
    if tasks is not None:
        _try_chain_next(task, signal, tasks, ts)


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


def _recent_commits(since_hours: int = 24) -> list[dict]:
    """Return recent git commits as [{hash, subject, timestamp_utc}]."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--format=%H|%s|%aI", "--no-merges"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=5,
        )
        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"hash": parts[0][:7], "subject": parts[1], "timestamp": parts[2]})
        return commits
    except Exception:
        return []


def _match_commit_to_task(commit_subject: str, backlog_ref: str | None) -> bool:
    """Check if a commit subject references a backlog item."""
    if not backlog_ref:
        return False
    # Match "B32", "B-32", "B32:" etc. in commit subject (case-insensitive)
    # Also match full refs like "MC-006A"
    ref = backlog_ref.strip()
    pattern = re.compile(r'(?:^|[\s:/(])' + re.escape(ref) + r'(?:[\s:)/,.]|$)', re.IGNORECASE)
    return bool(pattern.search(commit_subject))


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
                import sys
                print(
                    f"[MC] OpenClaw cron API returned {resp.status_code}: {resp.text[:200]}",
                    file=sys.stderr,
                )
                return []
            return resp.json().get("jobs", [])
    except Exception as exc:
        import sys
        print(f"[MC] OpenClaw cron API unreachable: {exc}", file=sys.stderr)
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

    task_id = body.get("task_id")
    if task_id:
        kanban = _read_kanban()
        for task in kanban.get("tasks", []):
            if task.get("id") == task_id:
                signal = body.get("signal") or ("worker_completed" if entry["status"] == "completed" else "worker_progress")
                detail = body.get("signal_detail") or f"Digest entry added: {entry['title']}"
                _apply_workflow_signal(task, signal, detail=detail, at=datetime.now(timezone.utc).isoformat(), tasks=kanban.get("tasks", []))
                _write_kanban(kanban)
                break

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
    workflow_updates = []
    kanban = _read_kanban()
    task_index = {t.get("id"): t for t in kanban.get("tasks", [])}
    for ev in events:
        ev.setdefault("ts", now_str)
        ev.setdefault("ts_raw", datetime.now(timezone.utc).isoformat())
        _append_activity(ev)
        task_id = ev.get("task_id")
        if task_id and task_id in task_index:
            signal = ev.get("signal") or "worker_progress"
            detail = ev.get("detail") or ev.get("message") or "Activity event logged"
            _apply_workflow_signal(task_index[task_id], signal, detail=detail, at=ev.get("ts_raw"), tasks=kanban.get("tasks", []))
            workflow_updates.append({"task_id": task_id, "signal": signal})
    if workflow_updates:
        _write_kanban(kanban)
    return JSONResponse({"ok": True, "added": len(events), "workflow_updates": workflow_updates})


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
# Routes — Card Detail (MC-014: slideout panel)
# ---------------------------------------------------------------------------

@app.get("/api/kanban/card/{task_id}", response_class=HTMLResponse)
async def card_detail(request: Request, task_id: str):
    """Return an HTML fragment for the card detail slideout."""
    kanban = _read_kanban()
    task = next((t for t in kanban.get("tasks", []) if t.get("id") == task_id), None)
    if not task:
        return HTMLResponse("<p class='text-red-400 p-4'>Card not found.</p>", status_code=404)
    return templates.TemplateResponse("card_detail.html", {
        "request": request,
        "task": task,
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
                _apply_workflow_signal(task, "review_rejected", detail="Manual rollback/reject from board", at=datetime.now(timezone.utc).isoformat())
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
        "agent": body.get("agent"),
        "model": body.get("model"),
        "started_at": None,
        "completed_at": None,
        "commit": None,
        "rollback_commit": None,
        "phase": body.get("phase", "backlog"),
        "execution_mode": body.get("execution_mode"),
        "run_ref": body.get("run_ref"),
        "job_ref": body.get("job_ref"),
        "session_ref": body.get("session_ref"),
        "process_ref": body.get("process_ref"),
        "waiting_on": body.get("waiting_on"),
        "next_event": body.get("next_event"),
        "next_check_at": body.get("next_check_at"),
        "on_success": body.get("on_success"),
        "on_failure": body.get("on_failure"),
        "visible_result": body.get("visible_result") or body.get("on_success"),
        "visible_result_confirmed_at": body.get("visible_result_confirmed_at"),
        "escalate_to": body.get("escalate_to"),
        "last_signal_at": body.get("last_signal_at"),
        "handoff_ready": body.get("handoff_ready", False),
        "handoff_checklist": body.get("handoff_checklist", {}),
        "spec_path": body.get("spec_path"),
        "handoff_contract": body.get("handoff_contract"),
        "card_type": body.get("card_type", "task"),  # "task" (finishable) or "loop" (persistent operational)
        "persistent_state": body.get("persistent_state"),
        "persistent_state_reason": body.get("persistent_state_reason"),
        "notes": body.get("notes", ""),
        "chain_next": body.get("chain_next", []),
        "chain_depth": body.get("chain_depth", 0),
        "chained_from": body.get("chained_from"),
        # Risk metadata (MC-019 — Crusty-first escalation policy)
        "risk_tier": body.get("risk_tier"),            # tier0_auto | tier1_crusty_review | tier2_crusty_decide | tier3_dj_required
        "risk_reason": body.get("risk_reason"),
        "blast_radius": body.get("blast_radius"),
        "reversibility": body.get("reversibility"),
        "external_effects": body.get("external_effects"),
        "cost_scope": body.get("cost_scope"),
        "dj_decision_required": body.get("dj_decision_required", False),
        "dj_decision_question": body.get("dj_decision_question"),
        # Crusty decision outcome (MC-019)
        "crusty_decision": body.get("crusty_decision"),   # approve | approve_with_guardrails | reroute | elevate_to_dj
        "crusty_rationale": body.get("crusty_rationale"),
        "crusty_guardrails": body.get("crusty_guardrails"),
        "crusty_rollback_plan": body.get("crusty_rollback_plan"),
        "crusty_dj_question": body.get("crusty_dj_question"),
        # Discord operating metadata (MC-023)
        "discord_anchor_channel": body.get("discord_anchor_channel"),
        "discord_anchor_message_id": body.get("discord_anchor_message_id"),
        "discord_thread_id": body.get("discord_thread_id"),
        "discord_thread_needed": body.get("discord_thread_needed"),
        "discord_thread_state": body.get("discord_thread_state"),
        "discord_blocked_message_id": body.get("discord_blocked_message_id"),
        "discord_shiplog_message_id": body.get("discord_shiplog_message_id"),
    }
    kanban["tasks"].append(task)
    _write_kanban(kanban)
    return JSONResponse({"ok": True, "task": task})


# Allowlisted fields for PATCH updates (MC-019 risk + crusty decision + general card fields)
_PATCHABLE_FIELDS = {
    "title", "priority", "agent", "model", "notes", "phase", "column", "card_type",
    "execution_mode", "escalate_to", "on_success", "on_failure",
    "visible_result", "visible_result_confirmed_at",
    "waiting_on", "next_event", "next_check_at",
    "spec_path", "handoff_contract", "handoff_ready",
    "persistent_state", "persistent_state_reason",
    # Risk metadata (MC-019)
    "risk_tier", "risk_reason", "blast_radius", "reversibility",
    "external_effects", "cost_scope", "dj_decision_required", "dj_decision_question",
    # Crusty decision outcome (MC-019)
    "crusty_decision", "crusty_rationale", "crusty_guardrails",
    "crusty_rollback_plan", "crusty_dj_question",
    # Discord operating metadata (MC-023)
    "discord_anchor_channel", "discord_anchor_message_id", "discord_thread_id",
    "discord_thread_needed", "discord_thread_state", "discord_blocked_message_id",
    "discord_shiplog_message_id",
}


@app.patch("/api/kanban/card/{task_id}")
async def kanban_update_card(task_id: str, request: Request):
    """Update allowlisted fields on an existing card (MC-019)."""
    body = await request.json()
    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") == task_id:
            changed = []
            for key, value in body.items():
                if key in _PATCHABLE_FIELDS:
                    task[key] = value
                    changed.append(key)
            if not changed:
                return JSONResponse({"error": "no patchable fields provided"}, status_code=400)
            _write_kanban(kanban)
            return JSONResponse({"ok": True, "task_id": task_id, "updated": changed})
    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


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

    # Extract execution handle updates from the signal payload (MC-006B)
    handle_updates = {}
    for field in HANDLE_TYPES:
        if field in body:
            handle_updates[field] = body[field]

    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") == task_id:
            _apply_workflow_signal(task, signal, detail=detail, at=at, tasks=kanban.get("tasks", []), handle_updates=handle_updates or None)
            _write_kanban(kanban)
            discord_hooks = _discord_hook_plan(task, signal=signal)
            discord_execution = None
            try:
                discord_execution = await _maybe_auto_execute_discord(task, signal, kanban)
            except DiscordAdapterError as exc:
                discord_execution = {
                    "attempted": True,
                    "ok": False,
                    "error": str(exc),
                    "hooks": discord_hooks,
                    "config": _discord_config_status(),
                }
            return JSONResponse({
                "ok": True,
                "task_id": task_id,
                "signal": signal,
                "phase": task.get("phase"),
                "column": task.get("column"),
                "handles": _get_execution_handles(task),
                "discord_hooks": discord_hooks,
                "discord_execution": discord_execution,
            })
    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.get("/api/discord/plan/{task_id}")
async def discord_plan(task_id: str):
    """Preview the Discord actions Mission Control would like to take for a card (MC-023)."""
    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") == task_id:
            return JSONResponse({
                "ok": True,
                "task_id": task_id,
                "hooks": _discord_hook_plan(task),
                "thread_needed": _discord_thread_needed(task),
                "thread_name": _discord_thread_slug(task) if _discord_thread_needed(task) else None,
            })
    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.post("/api/discord/execute/{task_id}")
async def discord_execute(task_id: str, request: Request):
    """Execute the derived Discord hook plan for a card and persist returned Discord ids."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    dry_run = body.get("dry_run")
    if dry_run is None:
        dry_run = True
    signal = body.get("signal")

    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") != task_id:
            continue

        plan = _discord_hook_plan(task, signal=signal)
        if not plan:
            return JSONResponse({"ok": True, "task_id": task_id, "dry_run": dry_run, "executed": [], "message": "no discord actions for this card"})

        if not dry_run and not _discord_adapter_enabled():
            return JSONResponse({
                "error": "Discord writes are disabled. Set MISSION_CONTROL_DISCORD_ENABLE_WRITES=1 to allow live posting.",
                "task_id": task_id,
                "hooks": plan,
                "config": _discord_config_status(),
            }, status_code=400)

        try:
            results = await _execute_discord_hook_plan(task, plan, dry_run=dry_run)
        except DiscordAdapterError as exc:
            failure_config = _discord_config_status()
            return JSONResponse({
                "error": str(exc),
                "task_id": task_id,
                "hooks": plan,
                "config": failure_config,
                "first_missing_live_write_gate": failure_config.get("first_missing"),
                "discord_state": _discord_state_snapshot(task),
            }, status_code=502)

        if not dry_run:
            _write_kanban(kanban)

        return JSONResponse({
            "ok": True,
            "task_id": task_id,
            "dry_run": dry_run,
            "hooks": plan,
            "executed": results,
            "discord_state": {
                "discord_anchor_channel": task.get("discord_anchor_channel"),
                "discord_anchor_message_id": task.get("discord_anchor_message_id"),
                "discord_thread_id": task.get("discord_thread_id"),
                "discord_thread_state": task.get("discord_thread_state"),
                "discord_blocked_message_id": task.get("discord_blocked_message_id"),
                "discord_shiplog_message_id": task.get("discord_shiplog_message_id"),
            },
        })
    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.get("/api/workflow/handles")
async def workflow_handles():
    """Return all active execution handles across the board (MC-006B).
    Useful for: which cards have live workers, what's stale, what's orphaned."""
    kanban = _read_kanban()
    now = datetime.now(timezone.utc)
    result = []
    for task in kanban.get("tasks", []):
        handles = _get_execution_handles(task)
        if not handles:
            continue
        stale = _is_handle_stale(task, now)
        result.append({
            "task_id": task.get("id"),
            "title": task.get("title"),
            "column": task.get("column"),
            "phase": task.get("phase"),
            "agent": task.get("agent"),
            "handles": handles,
            "stale": stale,
            "last_signal_at": task.get("last_signal_at"),
        })
    return JSONResponse({"ok": True, "cards_with_handles": result, "count": len(result)})


@app.post("/api/workflow/chain/approve")
async def workflow_chain_approve(request: Request):
    """Approve a blocked chain — create the chained card and unblock the parent."""
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id is required"}, status_code=400)

    kanban = _read_kanban()
    all_tasks = kanban.get("tasks", [])
    for task in all_tasks:
        if task.get("id") == task_id:
            if task.get("phase") != "chain_blocked" or task.get("waiting_on") != "chain_approval":
                return JSONResponse({"error": f"task {task_id} is not in chain_blocked state"}, status_code=400)

            chain = task.get("chain_next")
            if not chain or not isinstance(chain, list) or len(chain) == 0:
                return JSONResponse({"error": f"task {task_id} has no chain_next template"}, status_code=400)

            template = chain[0]
            ts = datetime.now(timezone.utc).isoformat()
            depth = task.get("chain_depth", 0)

            # Check for ID collision
            existing_ids = {t.get("id") for t in all_tasks}
            if template.get("id") in existing_ids:
                return JSONResponse({"error": f"Card ID {template.get('id')} already exists"}, status_code=409)

            new_card = _create_card_from_chain_template(template, task["id"], depth, ts)
            task["chain_next"] = chain[1:]

            # Complete the parent (it was blocked mid-completion)
            task["column"] = "completed"
            task["phase"] = "completed"
            task["completed_at"] = task.get("completed_at") or ts
            _clear_wait_fields(task)
            _append_task_note(task, f"Chain approved → {new_card['id']} @ {_format_timestamp(ts, 'compact')}")

            all_tasks.append(new_card)
            _log_chain_to_digest(task["id"], new_card, True, depth + 1)
            _write_kanban(kanban)

            return JSONResponse({
                "ok": True,
                "parent_id": task_id,
                "new_card_id": new_card["id"],
                "new_card_title": new_card["title"],
                "chain_depth": new_card["chain_depth"],
            })

    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.post("/api/workflow/chain/reject")
async def workflow_chain_reject(request: Request):
    """Reject a blocked chain — complete the parent without chaining."""
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id is required"}, status_code=400)

    kanban = _read_kanban()
    for task in kanban.get("tasks", []):
        if task.get("id") == task_id:
            if task.get("phase") != "chain_blocked" or task.get("waiting_on") != "chain_approval":
                return JSONResponse({"error": f"task {task_id} is not in chain_blocked state"}, status_code=400)

            ts = datetime.now(timezone.utc).isoformat()
            task["column"] = "completed"
            task["phase"] = "completed"
            task["completed_at"] = task.get("completed_at") or ts
            _clear_wait_fields(task)
            _append_task_note(task, f"Chain rejected — completed without chaining @ {_format_timestamp(ts, 'compact')}")
            _write_kanban(kanban)

            return JSONResponse({"ok": True, "task_id": task_id, "action": "chain_rejected"})

    return JSONResponse({"error": f"task {task_id} not found"}, status_code=404)


@app.post("/api/workflow/reconcile")
async def workflow_reconcile():
    kanban = _read_kanban()
    jobs = await _cron_jobs_raw()
    jobs_by_id = {j.get("id"): j for j in jobs}
    recent_commits = _recent_commits(since_hours=24)
    now = datetime.now(timezone.utc)
    updates = []

    all_tasks = kanban.get("tasks", [])
    for task in list(all_tasks):  # iterate over copy since chain_next may append
        task_id = task.get("id")
        if task.get("column") == "completed":
            continue

        _normalize_visible_result(task)

        # Source 0 (MC-027): every active card needs a last-mile next event, visible result, or named blocker
        gaps = _last_mile_gaps(task)
        if gaps:
            _block_for_last_mile_gap(task, gaps, now.isoformat())
            updates.append({"task_id": task_id, "signal": "last_mile_gap", "source": "workflow_audit", "gaps": gaps})
            continue

        # Source 1: OpenClaw cron job state
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
                    if status == "error" and _is_rate_limit_error(detail):
                        retry_at = _retry_time_from_error(detail, fallback_at=(datetime.fromtimestamp(state.get("nextRunAtMs") / 1000, tz=timezone.utc).isoformat() if state.get("nextRunAtMs") else None))
                        task["next_check_at"] = retry_at
                        if retry_at:
                            detail = f"{detail} Retry/reset window: {_format_timestamp(retry_at, 'compact')}"
                        signal = "rate_limited"
                    _apply_workflow_signal(task, signal, detail=detail, at=last_run_dt.isoformat(), tasks=all_tasks)
                    updates.append({"task_id": task_id, "signal": signal, "source": "cron"})
                    continue

        # Source 2: Git commit matching via backlog_ref
        backlog_ref = task.get("backlog_ref")
        if backlog_ref and not task.get("commit"):
            last_signal = _parse_timestamp(task.get("last_signal_at"))
            for commit in recent_commits:
                if _match_commit_to_task(commit["subject"], backlog_ref):
                    commit_ts = commit.get("timestamp", now.isoformat())
                    commit_dt = _parse_timestamp(commit_ts)
                    # Only signal if commit is newer than last signal
                    if last_signal and commit_dt and commit_dt.astimezone(timezone.utc) <= last_signal.astimezone(timezone.utc):
                        continue
                    task["commit"] = commit["hash"]
                    detail = f"Git commit {commit['hash']}: {commit['subject']}"
                    _apply_workflow_signal(task, "worker_completed", detail=detail, at=commit_ts, tasks=all_tasks)
                    updates.append({"task_id": task_id, "signal": "worker_completed", "source": "git_commit", "commit": commit["hash"]})
                    break

        # Source 3: Timer expiry
        next_check = _parse_timestamp(task.get("next_check_at"))
        if next_check and next_check.astimezone(timezone.utc) <= now and task.get("phase") not in {"completed", "under_review"}:
            _apply_workflow_signal(task, "timer_expired", detail="Checkpoint expired without a newer completion signal", at=now.isoformat(), tasks=all_tasks)
            updates.append({"task_id": task_id, "signal": "timer_expired", "source": "timer"})

        # Source 4 (MC-006B): Execution handle staleness detection
        if _is_handle_stale(task, now) and task.get("phase") not in {"blocked", "completed", "under_review"}:
            handles = _get_execution_handles(task)
            handle_summary = ", ".join(f"{h['label']}={h['value'][:8]}" for h in handles)
            _apply_workflow_signal(task, "worker_failed", detail=f"Execution handles stale (>6h no signal): {handle_summary}", at=now.isoformat(), tasks=all_tasks)
            updates.append({"task_id": task_id, "signal": "worker_failed", "source": "handle_staleness", "handles": [h["value"] for h in handles]})

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
