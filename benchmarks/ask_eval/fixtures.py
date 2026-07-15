"""B304 — deterministic fixture graph for the ask-eval harness.

Writes known content through the REAL tool handlers (register_plan,
report_outcome, upsert_lesson, notify_turn) — never raw Cypher — so the eval
exercises genuine pipeline output, not a hand-rolled shortcut.
"""

from __future__ import annotations

from campy.brain.thalamus.tools import (
    notify_turn,
    register_plan,
    report_outcome,
    upsert_lesson,
)

_SEED_SESSION_ID = "eval-seed-session"

_PLANS = [
    {
        "goal": (
            "Implement B292 by splitting campy/brain/thalamus/tools/__init__.py into "
            "focused domain modules while preserving behavior and exports"
        ),
        "steps": [
            "Create shared utility module",
            "Create domain modules with mechanical moves",
            "Rewrite __init__ as thin aggregator",
            "Run parity checks and tests",
        ],
    },
    {
        "goal": (
            "Implement B293 so the MCP tool surface is schema-first with generated "
            "extension definitions and CI drift protection"
        ),
        "steps": [
            "Derive EXPECTED_TOOLS from tool_schemas",
            "Add generator script",
            "Wire generated definitions into index.ts",
            "Add CI drift check",
        ],
    },
    {
        "goal": (
            "Implement B298 Claude auto-memory piggyback capture into Campy via "
            "notify_turn with non-blocking hooks"
        ),
        "steps": [
            "Parse memory frontmatter",
            "Wire PostToolUse hook",
            "Add idempotency key",
            "Add tests",
        ],
    },
]

_LESSONS = [
    {
        "text": (
            "When adding a new MCP tool, register it in tool_schemas.TOOLS and "
            "TOOL_HANDLERS, then regenerate extension entries with "
            "scripts/generate_extension_tools.py"
        ),
        "domain": "tooling",
        "lesson_type": "architecture-principle",
    },
    {
        "text": (
            "Kuzu is single-writer: stop the daemon before any direct-DB maintenance "
            "command or it fails with a lock error"
        ),
        "domain": "operations",
        "lesson_type": "edge-case",
    },
]

_MESSAGES = [
    {"role": "user", "content": "let's use Apache-2.0 for the license"},
    {"role": "assistant", "content": "Confirmed — Apache-2.0 it is."},
    {"role": "user", "content": "the daemon port stays 7799"},
    {"role": "assistant", "content": "Got it, daemon port stays 7799."},
]


async def seed_fixture_graph(db, config: dict) -> None:
    """Seed a deterministic fixture graph via the real tool handlers.

    3 plans (each with 4 steps reported succeeded, then a final plan-level
    outcome), 2 lessons, and 4 alternating user/assistant messages.
    """
    for plan in _PLANS:
        result = await register_plan(
            {
                "goal": plan["goal"],
                "steps": plan["steps"],
                "session_id": _SEED_SESSION_ID,
            },
            db,
            config,
        )
        plan_id = result["plan_id"]

        for step_number, _ in enumerate(plan["steps"], start=1):
            await report_outcome(
                {
                    "plan_id": plan_id,
                    "step_number": step_number,
                    "outcome": "succeeded",
                    "valence": 0.9,
                    "valence_source": "explicit",
                    "session_id": _SEED_SESSION_ID,
                },
                db,
                config,
            )

        await report_outcome(
            {
                "plan_id": plan_id,
                "outcome": "all steps complete, tests green",
                "valence": 0.9,
                "valence_source": "explicit",
                "session_id": _SEED_SESSION_ID,
            },
            db,
            config,
        )

    for lesson in _LESSONS:
        await upsert_lesson(
            {
                "text": lesson["text"],
                "domain": lesson["domain"],
                "lesson_type": lesson["lesson_type"],
                "session_id": _SEED_SESSION_ID,
            },
            db,
            config,
        )

    for message in _MESSAGES:
        await notify_turn(
            {
                "role": message["role"],
                "content": message["content"],
                "session_id": _SEED_SESSION_ID,
            },
            db,
            config,
        )
