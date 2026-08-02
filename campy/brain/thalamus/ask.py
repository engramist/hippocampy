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
import re
from typing import Optional, TYPE_CHECKING

from campy.brain.thalamus.bundle_compiler import compile_bundle  # noqa: F401 — kept at module level for patch targets

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


def _get_llm(config: dict):
    """Return LLMClient for main inference. Returns None if unavailable."""
    try:
        from campy.brain.llm.provider import create_llm_client
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


# B303: each bundle section type explained so the synthesis LLM knows what
# a non-empty section IS, instead of guessing (it was answering "memory is
# empty" with a populated plans section because nothing told it otherwise).
_SECTION_DESCRIPTIONS: dict[str, str] = {
    "exact_fact": "hard constraints and preferences that must be honored as ground truth",
    "plans": "documented work plans with per-step outcomes — completed or in-flight work, with recorded results",
    "semantic": "related concepts, decisions, constraints, and requirements",
    "graph": "graph relationships connecting the entities above",
    "tabular": "structured tabular data",
    "summary": "narrative summaries of prior work",
    "code": "source code extracts",
}


def _render_plan_item(item: dict) -> str:
    """Plan section items carry goal/status/valence/steps, not compact/toon/
    text/source — render them explicitly so they survive into the prompt."""
    lines = [f"Plan: {item.get('goal', '')}"]
    if item.get("status") is not None:
        lines.append(f"Status: {item['status']}")
    if item.get("valence") is not None:
        lines.append(f"Outcome valence: {item['valence']}")
    for step in item.get("steps") or []:
        if not isinstance(step, dict):
            continue
        desc = step.get("description", "")
        step_valence = step.get("valence")
        lines.append(f"  - Step: {desc} (valence={step_valence})")
    return "\n".join(lines)


def _bundle_to_prompt(bundle, query: str) -> str:
    """Flatten compressed bundle sections into a single prompt string."""
    parts = [f"Query: {query}\n\nContext from memory:\n"]
    has_content = False
    for section in bundle.sections:
        section_type = section.section_type
        description = _SECTION_DESCRIPTIONS.get(section_type, section_type)
        rendered_items = []
        for item in section.content:
            if not isinstance(item, dict):
                continue
            if "compact" in item:
                rendered_items.append(item["compact"])
            elif "toon" in item:
                rendered_items.append(item["toon"])
            elif section_type == "plans" and "goal" in item:
                rendered_items.append(_render_plan_item(item))
            elif "text" in item:
                rendered_items.append(item["text"])
            elif "source" in item:
                rendered_items.append(item["source"])
        if not rendered_items:
            continue
        has_content = True
        parts.append(f"[{section_type}: {description}]\n" + "\n\n".join(rendered_items))

    if has_content:
        parts.insert(
            1,
            "The sections below are NOT empty — relevant memory exists for this "
            "query and must be used to answer it. Do not claim memory is empty.",
        )
    return "\n\n".join(parts)


_ASK_SYSTEM_PROMPT = (
    "You are Campy, an AI memory assistant. Answer the user's question "
    "using only the provided memory context. If the context does not "
    "contain enough information, say so explicitly."
)

_EMPTY_CLAIM_RE = re.compile(r"(memory|context) is empty|no information", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"\bB\d+\b")


def _harness_variants(config: dict) -> set[str]:
    """B304: parse config["ask"]["harness_variant"] into a flag set.

    Default "H0" (baseline, no flags) keeps production behavior unchanged.
    Combined variants use "+" e.g. "H1+H2".
    """
    raw = (config.get("ask") or {}).get("harness_variant") or "H0"
    flags = {part.strip() for part in raw.split("+") if part.strip()}
    flags.discard("H0")
    return flags


def _extract_identifier_tokens(query: str) -> list[str]:
    """B304 H1: pull backlog-card-style identifiers (e.g. "B292") out of a query."""
    return _IDENTIFIER_RE.findall(query)


def _h1_identifier_fastpath(prompt: str, bundle, query: str) -> str:
    """B304 H1 — identifier fast-path.

    If the query names an identifier (e.g. "B292") and any plan/lesson item
    in the bundle contains that token, prepend a direct-match preamble
    instructing the LLM to base its answer on those items. No-op otherwise —
    keeps H0 behavior byte-identical when this isn't called.
    """
    tokens = _extract_identifier_tokens(query)
    if not tokens:
        return prompt

    matches: list[str] = []
    for section in bundle.sections:
        if section.section_type not in ("plans", "semantic"):
            continue
        for item in section.content:
            if not isinstance(item, dict):
                continue
            text_bits = []
            if "goal" in item:
                text_bits.append(str(item.get("goal", "")))
                for step in item.get("steps") or []:
                    if isinstance(step, dict):
                        text_bits.append(str(step.get("description", "")))
            if "text" in item:
                text_bits.append(str(item.get("text", "")))
            full_text = "\n".join(bit for bit in text_bits if bit)
            if full_text and any(token in full_text for token in tokens):
                matches.append(full_text)

    if not matches:
        return prompt

    preamble = (
        f"DIRECT MATCHES for {', '.join(tokens)}: " + " | ".join(matches) + "\n\n"
        "These items directly answer the question — base your answer on them.\n\n"
    )
    return preamble + prompt


def _h2_empty_claim_guard(answer: str, bundle, prompt: str, llm, meta: Optional[dict] = None) -> str:
    """B304 H2 — empty-claim guard.

    If the bundle was non-empty but the LLM claimed memory/context is empty,
    retry once with an explicit instruction that the context is NOT empty.
    Records meta["retried"] for eval-JSON reporting. No-op (no retry) when the
    bundle is empty or the answer doesn't make an empty-memory claim.
    """
    bundle_nonempty = any(section.content for section in bundle.sections)
    if bundle_nonempty and _EMPTY_CLAIM_RE.search(answer):
        retry_prompt = (
            prompt
            + "\n\nThe context above is NOT empty. List what the plans section "
            "contains, then answer the question from it."
        )
        retry_messages = [
            {"role": "system", "content": _ASK_SYSTEM_PROMPT},
            {"role": "user", "content": retry_prompt},
        ]
        answer = llm.chat(retry_messages)
        if meta is not None:
            meta["retried"] = True
    elif meta is not None:
        meta["retried"] = False
    return answer


async def run_ask(
    query: str,
    session_id: str,
    db,
    config: dict,
    token_budget: int = 32000,
    capture: bool = True,
    meta: Optional[dict] = None,
) -> str:
    """
    Full ask pipeline: augment → compress → send → capture.
    Returns the LLM answer as a string.

    capture: when True (default), the question + answer are written back into
    the graph so asking teaches the brain. Set False (--no-capture) for
    throwaway queries.

    meta: optional dict the caller can pass to receive harness-variant
    bookkeeping (e.g. meta["retried"] from H2). Unused by production callers.
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
    variants = _harness_variants(config)
    if "H1" in variants:
        prompt = _h1_identifier_fastpath(prompt, bundle, query)

    llm = _get_llm(config)
    if llm is None:
        return "[Error: LLM unavailable. Check campy.toml [llm] configuration.]"

    messages = [
        {"role": "system", "content": _ASK_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    answer = llm.chat(messages)

    if "H2" in variants:
        answer = _h2_empty_claim_guard(answer, bundle, prompt, llm, meta=meta)

    # 4. Capture (closed loop) — both the question and the answer
    if capture:
        await _capture_turn(query, answer, session_id, db, config)

    return answer
