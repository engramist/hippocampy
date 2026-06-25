"""
campy/brain/thalamus/ask.py — Augmented Inference Orchestrator

Pipeline: augment → classify → compress → send → capture

This module is the single implementation shared by:
  - campy/cli/ask.py  (Typer CLI: human calls `campy ask "..."`)
  - campy/brain/thalamus/tools/__init__.py  (MCP tool: agent calls `ask`)

Both front doors call run_ask(). Neither duplicates logic.

COMPRESSION IS ALWAYS-ON (Option B):
  - Structured data (exact_fact, tabular): always compressed via TOON
  - Graph/semantic nodes: always scored + pruned via GraphBundleCompressor
  - Prose (summary): compressed via LLMCompressor only when prose is present
  - Code (code): compressed via ASTCodeCompressor only when code is present
"""

from __future__ import annotations
import logging
from typing import Optional, TYPE_CHECKING

from campy.brain.thalamus.bundle_compiler import compile_bundle  # noqa: F401 — kept at module level for patch targets

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


def _get_llm(config: dict):
    """Return LLMClient for main inference. Returns None if unavailable."""
    try:
        from mcp_engine.llm.provider import create_llm_client
        return create_llm_client(config)
    except Exception:
        return None


async def _capture_one(role: str, content: str, session_id: str, db, config: dict) -> None:
    """Capture a single turn.

    Tries a direct notify_turn first (works in-daemon where `db` is writable).
    Kuzu is single-writer, so the CLI front door opens the DB read-only and a
    direct write raises — in that case we route to the daemon (the single
    writer) over the brain transport. Both paths are best-effort: capture must
    never fail the answer the user already has.
    """
    params = {"role": role, "content": content, "session_id": session_id}
    try:
        from campy.brain.thalamus.tools import notify_turn
        await notify_turn(params=params, db=db, config=config)
        return
    except Exception as direct_exc:
        try:
            from campy.brain_transport import call_brain
            # Short timeout: notify_turn returns as soon as the daemon queues
            # the turn, so this can't hang the response for long.
            await call_brain("notify_turn", params, timeout=3.0)
        except Exception as transport_exc:
            _logger.warning(
                "ask: capture failed for role=%s (direct=%s; transport=%s)",
                role, direct_exc, transport_exc,
            )


async def _capture_turn(query: str, answer: str, session_id: str, db, config: dict) -> None:
    """Close the loop: capture both the user's question and the answer.

    The question is captured first — it's often the richer signal (what the
    project is being asked about) and should land even if the answer write
    fails. Entered as normal-confidence turns; Campy's confidence/decay
    machinery down-weights unconfirmed material, so a wrong answer self-corrects
    rather than locking in.
    """
    await _capture_one("user", query, session_id, db, config)
    await _capture_one("assistant", answer, session_id, db, config)


def _bundle_to_prompt(bundle, query: str) -> str:
    """Flatten compressed bundle sections into a single prompt string."""
    parts = [f"Query: {query}\n\nContext from memory:\n"]
    for section in bundle.sections:
        section_type = section.section_type
        for item in section.content:
            if not isinstance(item, dict):
                continue
            if "compact" in item:
                parts.append(f"[{section_type}]\n{item['compact']}")
            elif "toon" in item:
                parts.append(f"[{section_type}]\n{item['toon']}")
            elif "text" in item:
                parts.append(f"[{section_type}]\n{item['text']}")
            elif "source" in item:
                parts.append(f"[code]\n{item['source']}")
    return "\n\n".join(parts)


async def run_ask(
    query: str,
    session_id: str,
    db,
    config: dict,
    token_budget: int = 32000,
    capture: bool = True,
) -> str:
    """
    Full ask pipeline: augment → compress → send → capture.
    Returns the LLM answer as a string.

    capture: when True (default), the question + answer are written back into
    the graph so asking teaches the brain. Set False (--no-capture) for
    throwaway queries.
    """
    # 1. Augment
    bundle = await compile_bundle(
        query=query,
        db=db,
        config=config,
        token_budget=token_budget,
    )

    # 2. Compress (always-on, Option B)
    from campy.brain.thalamus.compression import build_default_registry
    _, router = build_default_registry(config)
    compressed_sections = [
        router.compress_section(section, query, config)
        for section in bundle.sections
    ]
    bundle.sections = compressed_sections

    # 3. Build prompt and send
    prompt = _bundle_to_prompt(bundle, query)
    llm = _get_llm(config)
    if llm is None:
        return "[Error: LLM unavailable. Check campy.toml [llm] configuration.]"

    messages = [
        {
            "role": "system",
            "content": (
                "You are Campy, an AI memory assistant. Answer the user's question "
                "using only the provided memory context. If the context does not "
                "contain enough information, say so explicitly."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    answer = llm.chat(messages)

    # 4. Capture (closed loop) — both the question and the answer
    if capture:
        await _capture_turn(query, answer, session_id, db, config)

    return answer
