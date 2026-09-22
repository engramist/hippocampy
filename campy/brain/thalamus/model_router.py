"""
campy/brain/thalamus/model_router.py — B382 Dynamic Phase-Aware Model Router.

Advisory only: Campy never calls a cloud model itself. `route_task()`
inspects graph state and returns a recommendation
`{tier, recommended_model, provider, context_bundle, rationale}` for the
caller (a coding agent or harness) to act on. Memory stays local; a
frontier model, if the caller chooses to use one, is purely ephemeral
compute from Campy's point of view.

Phase heuristic anchors on real, general-purpose status-bearing entities
(see backlog/B382.md's "Completion Notes" for the correction to the
card's original design, which named `Decision`/`ActionItem` status
fields that don't exist in the schema, and `Hypothesis`, which is
ARC-AGI-specific):

- `Plan.status = 'active'` targeting the quest (real `TARGETS` edge,
  `Plan`->`MainQuest`) => an unfinalized plan exists => Planning phase.
- `TaskGraph.status = 'active'` for the session, with `TaskNode`s still
  `pending`/`active` => locked-in execution DAG in progress =>
  Implementation phase.
- No active Plan and no TaskGraph at all => cold start, nothing locked
  in yet => Planning phase (matches "when in doubt, use the smarter
  model" default).
- A small deterministic keyword match against the task description
  (formatting/lint/syntax-check terms) => Reflex, checked first as a
  fast path that never touches the graph.
"""

from __future__ import annotations

import re
import time

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


# Matches the card's proposed [routing] shape exactly. Merged with any
# caller-supplied config in _resolve_routing_config -- an absent
# [routing] section in campy.toml changes nothing.
DEFAULT_ROUTING_CONFIG = {
    "enabled": True,
    "default_tier": "economy",
    "tiers": {
        "frontier": {
            "provider": "anthropic",
            "model": "claude-opus-5",
            "trigger_phases": ["planning"],
        },
        "economy": {
            "provider": "ollama",
            "model": "llama3.1:8b",
            "trigger_phases": ["implementation"],
        },
        "local_reflex": {
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "trigger_phases": ["reflex"],
        },
    },
}

_REFLEX_KEYWORDS = re.compile(
    r"\b(format(?:ting)?|lint(?:ing)?|syntax[\s-]*check|whitespace|"
    r"prettier|gofmt|black|isort|autopep8)\b",
    re.IGNORECASE,
)


def _is_reflex_task(task_description: str) -> bool:
    return bool(_REFLEX_KEYWORDS.search(task_description or ""))


def row_get(row, key: str, index: int):
    """Duck-typed row access -- RowDict-style `.get(key)` or a positional
    tuple/list, matching the access pattern used throughout thalamus
    tools for NamedQuery results."""
    if hasattr(row, "get"):
        return row.get(key)
    return row[index] if len(row) > index else None


async def resolve_quest_id(gw, session_id: str, quest_id: str | None) -> str:
    if quest_id:
        return quest_id
    if not session_id or session_id == "unknown":
        return ""
    try:
        rows = await gw.run("retrieval.get_main_quest_for_session", sid=session_id)
        if rows:
            return row_get(rows[0], "q.quest_id", 0) or ""
    except Exception:
        pass
    return ""


async def get_active_plans(gw, quest_id: str) -> list[dict]:
    if not quest_id:
        return []
    try:
        rows = await gw.run("model_router.get_active_plans_for_quest", qid=quest_id)
    except Exception:
        return []
    plans = []
    for r in (rows or []):
        plans.append({
            "plan_id": row_get(r, "plan_id", 0),
            "goal": row_get(r, "goal", 1),
            "confidence": row_get(r, "confidence", 2),
        })
    return plans


async def get_active_task_graph_status(gw, session_id: str) -> dict | None:
    if not session_id or session_id == "unknown":
        return None
    try:
        rows = await gw.run("model_router.get_active_task_graph_for_session", sid=session_id)
    except Exception:
        return None
    if not rows:
        return None
    graph_id = row_get(rows[0], "graph_id", 0)
    if not graph_id:
        return None
    try:
        task_rows = await gw.run("task_graph.get_graph_tasks", gid=graph_id)
    except Exception:
        task_rows = []
    statuses = [row_get(t, "status", 3) for t in (task_rows or [])]
    return {
        "graph_id": graph_id,
        "pending_or_active": sum(1 for s in statuses if s in ("pending", "active")),
        "complete": sum(1 for s in statuses if s == "complete"),
        "total": len(statuses),
    }


async def detect_phase(db, session_id: str, quest_id: str | None = None) -> dict:
    """
    Bounded, indexed phase detection anchored on one quest/session.

    Returns:
        {
            "phase": "planning" | "implementation",
            "quest_id": str,
            "active_plans": list[dict],
            "task_graph_status": dict | None,
        }
    """
    gw = _gateway(db)
    resolved_quest_id = await resolve_quest_id(gw, session_id, quest_id)

    active_plans = await get_active_plans(gw, resolved_quest_id)
    task_graph_status = await get_active_task_graph_status(gw, session_id)

    if active_plans:
        phase = "planning"
    elif task_graph_status and task_graph_status["pending_or_active"] > 0:
        phase = "implementation"
    else:
        # Cold start: nothing locked into a Plan or TaskGraph yet --
        # default to Planning rather than guessing at execution.
        phase = "planning"

    return {
        "phase": phase,
        "quest_id": resolved_quest_id,
        "active_plans": active_plans,
        "task_graph_status": task_graph_status,
    }


def _resolve_routing_config(config: dict) -> dict:
    """Merge caller config over DEFAULT_ROUTING_CONFIG. Same shape as
    B375's warm_frontier config merge -- an absent [routing] section, or
    a partial one, still produces every default key."""
    routing_cfg = (config or {}).get("routing", {}) or {}
    caller_tiers = routing_cfg.get("tiers", {}) or {}

    merged_tiers = {}
    for tier_name, default_tier_cfg in DEFAULT_ROUTING_CONFIG["tiers"].items():
        merged_tiers[tier_name] = {**default_tier_cfg, **caller_tiers.get(tier_name, {})}
    for tier_name, tier_cfg in caller_tiers.items():
        if tier_name not in merged_tiers:
            merged_tiers[tier_name] = tier_cfg

    return {
        "enabled": routing_cfg.get("enabled", DEFAULT_ROUTING_CONFIG["enabled"]),
        "default_tier": routing_cfg.get("default_tier", DEFAULT_ROUTING_CONFIG["default_tier"]),
        "tiers": merged_tiers,
    }


def _tier_for_phase(routing_config: dict, phase: str) -> str:
    for tier_name, tier_cfg in routing_config["tiers"].items():
        if phase in (tier_cfg.get("trigger_phases") or []):
            return tier_name
    return routing_config["default_tier"]


def _build_context_bundle(query: str, phase_result: dict, token_budget: int) -> ContextBundle:
    sections: list[BundleSection] = []
    sources: list[str] = []

    active_plans = phase_result.get("active_plans") or []
    if active_plans:
        sections.append(BundleSection(
            section_type="plans",
            content=[
                {"plan_id": p["plan_id"], "goal": p["goal"], "confidence": p["confidence"]}
                for p in active_plans
            ],
            token_estimate=len(active_plans) * 40,
            source_node_ids=[p["plan_id"] for p in active_plans if p["plan_id"]],
        ))
        sources.extend(p["plan_id"] for p in active_plans if p["plan_id"])

    tgs = phase_result.get("task_graph_status")
    if tgs:
        sections.append(BundleSection(
            section_type="task_graph",
            content=[tgs],
            token_estimate=20,
            source_node_ids=[tgs["graph_id"]],
        ))
        sources.append(tgs["graph_id"])

    total_tokens = sum(s.token_estimate for s in sections)
    return ContextBundle(
        query=query,
        sections=sections,
        total_token_estimate=total_tokens,
        token_budget=token_budget,
        truncated=False,
        sources=sources,
    )


def _rationale(phase: str, tier: str, phase_result: dict, reflex: bool) -> str:
    if reflex:
        return "Task description matches a formatting/lint/syntax-check keyword — routed to local reflex tier without consulting graph state."
    if phase == "planning":
        active_plans = phase_result.get("active_plans") or []
        if active_plans:
            return (
                f"{len(active_plans)} active (unfinalized) Plan(s) target this quest — "
                f"routed to {tier} tier for architectural/trade-off reasoning."
            )
        return f"No active Plan or TaskGraph found for this quest — cold start, routed to {tier} tier."
    tgs = phase_result.get("task_graph_status") or {}
    return (
        f"TaskGraph {tgs.get('graph_id', '')!r} has {tgs.get('pending_or_active', 0)} "
        f"pending/active task(s) and no unfinalized Plan — routed to {tier} tier for execution."
    )


async def route_task(
    db,
    config: dict,
    task_description: str,
    session_id: str = "unknown",
    quest_id: str | None = None,
    token_budget: int = 4000,
) -> dict:
    """
    Recommend a model tier for `task_description`, given `session_id`'s
    graph state. Returns
    {tier, provider, recommended_model, phase, rationale, context_bundle,
     latency_ms}. Never raises for a missing/cold-start quest -- always
     returns a usable recommendation.
    """
    start = time.perf_counter()
    routing_config = _resolve_routing_config(config)

    if not routing_config["enabled"]:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "tier": "disabled",
            "provider": None,
            "recommended_model": None,
            "phase": None,
            "rationale": "Routing is disabled ([routing].enabled = false); caller should use its own default model.",
            "context_bundle": None,
            "latency_ms": round(latency_ms, 3),
        }

    if _is_reflex_task(task_description):
        tier = "local_reflex" if "local_reflex" in routing_config["tiers"] else routing_config["default_tier"]
        tier_cfg = routing_config["tiers"].get(tier, {})
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "tier": tier,
            "provider": tier_cfg.get("provider"),
            "recommended_model": tier_cfg.get("model"),
            "phase": "reflex",
            "rationale": _rationale("reflex", tier, {}, reflex=True),
            "context_bundle": None,
            "latency_ms": round(latency_ms, 3),
        }

    phase_result = await detect_phase(db, session_id, quest_id)
    phase = phase_result["phase"]
    tier = _tier_for_phase(routing_config, phase)
    tier_cfg = routing_config["tiers"].get(tier, {})

    bundle = _build_context_bundle(task_description, phase_result, token_budget)

    latency_ms = (time.perf_counter() - start) * 1000.0

    return {
        "tier": tier,
        "provider": tier_cfg.get("provider"),
        "recommended_model": tier_cfg.get("model"),
        "phase": phase,
        "rationale": _rationale(phase, tier, phase_result, reflex=False),
        "context_bundle": bundle.to_dict(),
        "latency_ms": round(latency_ms, 3),
    }
