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


async def _capture_turn(answer: str, session_id: str, db, config: dict) -> None:
    """Send the ask response through notify_turn for passive ingestion."""
    try:
        from campy.brain.thalamus.tools import notify_turn
        await notify_turn(
            params={"role": "assistant", "content": answer, "session_id": session_id},
            db=db,
            config=config,
        )
    except Exception as exc:
        _logger.warning("ask: capture_turn failed (non-fatal): %s", exc)


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
) -> str:
    """
    Full ask pipeline: augment → compress → send → capture.
    Returns the LLM answer as a string.
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

    # 4. Capture
    await _capture_turn(answer, session_id, db, config)

    return answer
