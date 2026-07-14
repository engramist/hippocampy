"""Shared helpers and state for thalamus tool handlers."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Optional

from campy.brain.temporal_lobe.dictionary import (
    DICTIONARY_PATHS,
    find_dictionary,
    ingest_dictionary,
    load_dictionary,
)

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.quest import (
    create_side_quest,
    get_or_create_main_quest,
    get_or_create_session,
    get_quest_context,
)
from campy.brain.hippocampus.table_registry import get_table, pk_for, tables_with

_logger = logging.getLogger(__name__)

def _with_phase(phase: str, fn):
    """Wrap a tool handler to set phase during execution."""
    async def wrapper(params=None, db=None, config=None, **kw):
        from campy.brain.brainstem.phase import set_phase
        set_phase(phase)
        try:
            return await fn(params=params, db=db, config=config, **kw)
        finally:
            set_phase("idle")
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

try:
    from campy.brain.temporal_lobe.loop.step4_pattern import (
        detect_ordered_plan_steps,
        has_plan_signal,
        infer_outcome_valence,
    )
except ModuleNotFoundError as exc:
    if exc.name != "campy.brain.temporal_lobe.loop.step4_pattern":
        raise
    _PLAN_SIGNALS = [
        r"(?:^|\n)\s*(?:step\s+)?\d+[\.\):]",
        r"\bmy (?:approach|plan|strategy)\b",
        r"\bhere(?:'s| is) (?:the|my) plan\b",
        r"\bi(?:'ll| will) (?:start by|begin with|first)\b",
        r"\bthe steps (?:are|would be)\b",
    ]
    _SUCCESS_SIGNALS = [
        r"\bperfect\b", r"\bgreat job\b", r"\bexactly (?:right|what)\b",
        r"\bship it\b", r"\bapproved\b", r"\blooks good\b", r"\bwell done\b",
        r"\bnailed it\b", r"\ball tests pass\b", r"\bmerged?\b",
    ]
    _FAILURE_SIGNALS = [
        r"\bthat(?:'s| is) wrong\b", r"\brevert\b", r"\bundo\b",
        r"\bthat broke\b", r"\bfailed\b", r"\brollback\b",
        r"\bnot what i (?:asked|wanted|meant)\b", r"\bstart over\b",
        r"\btry again\b", r"\bwrong approach\b",
    ]

    def detect_ordered_plan_steps(text: str) -> list[str]:
        if not text:
            return []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        steps: list[str] = []
        numbered = re.compile(r"^(?:step\s+)?\d+[\.\):]\s+(.+)$", re.IGNORECASE)
        bullet = re.compile(r"^[-]\s+(.+)$")
        ordered_words = re.compile(r"^(?:first|then|next|finally)\b[:\-]?\s*(.+)$", re.IGNORECASE)
        for line in lines:
            m_num = numbered.match(line)
            if m_num:
                steps.append(m_num.group(1).strip())
                continue
            m_ord = ordered_words.match(line)
            if m_ord:
                steps.append(m_ord.group(1).strip())
                continue
            m_bul = bullet.match(line)
            if m_bul and ordered_words.match(m_bul.group(1).strip()):
                steps.append(m_bul.group(1).strip())
        seen = set()
        clean: list[str] = []
        for step in steps:
            key = step.lower()
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            clean.append(step)
        return clean

    def has_plan_signal(text: str) -> bool:
        lower = (text or "").lower()
        return any(re.search(p, lower) for p in _PLAN_SIGNALS)

    def infer_outcome_valence(text: str) -> float | None:
        lower = (text or "").lower()
        success_hits = sum(1 for p in _SUCCESS_SIGNALS if re.search(p, lower))
        failure_hits = sum(1 for p in _FAILURE_SIGNALS if re.search(p, lower))
        if success_hits == 0 and failure_hits == 0:
            return None
        if success_hits > failure_hits:
            return 0.8
        if failure_hits > success_hits:
            return -0.8
        return None

_loop_queue: Optional[asyncio.Queue] = None

def init_loop_queue(queue: asyncio.Queue) -> None:
    """Called once by BrainDaemon.start() after the event loop is running."""
    global _loop_queue
    _loop_queue = queue


def get_loop_queue() -> Optional[asyncio.Queue]:
    return _loop_queue


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _normalize_steps(raw_steps: list[str]) -> list[str]:
    steps: list[str] = []
    seen = set()
    for step in raw_steps:
        text = (step or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        steps.append(text)
    return steps


def _safe_result_dict(node) -> dict:
    """Defensive cast for Kuzu node records that behave like dicts."""
    try:
        return dict(node)
    except Exception:
        return node if isinstance(node, dict) else {}


_CONCEPT_TABLE = get_table("Concept")
_LESSON_TABLE = get_table("Lesson")
_PLAN_TABLE = get_table("Plan")
_PROCEDURE_TABLE = get_table("Procedure")

assert _CONCEPT_TABLE is not None and _CONCEPT_TABLE.vector_index is not None
assert _LESSON_TABLE is not None and _LESSON_TABLE.vector_index is not None
assert _PLAN_TABLE is not None and _PLAN_TABLE.vector_index is not None
assert _PROCEDURE_TABLE is not None and _PROCEDURE_TABLE.vector_index is not None

_CONCEPT_INDEX = _CONCEPT_TABLE.vector_index
_LESSON_INDEX = _LESSON_TABLE.vector_index
_PLAN_INDEX = _PLAN_TABLE.vector_index
_PROCEDURE_INDEX = _PROCEDURE_TABLE.vector_index

RRF_K = 60
PATHWAY_CAP = 5.0
VALENCE_WEIGHT = 0.2

def _rrf_fuse(source_lists: dict[str, list[dict]], limit: int) -> list[dict]:
    """Reciprocal Rank Fusion across ranked source lists."""
    fused: dict[str, dict] = {}
    for source, ranked in source_lists.items():
        for rank, cand in enumerate(ranked):
            nid = cand.get("node_id")
            if not nid:
                continue
            entry = fused.setdefault(nid, {
                "cand": cand,
                "rrf": 0.0,
                "sources": {},
            })
            entry["rrf"] += 1.0 / (RRF_K + rank + 1)
            entry["sources"][source] = {
                "rank": rank,
                "score": cand.get("score"),
            }
            if cand.get("score", 0.0) > entry["cand"].get("score", 0.0):
                entry["cand"] = cand
    _ = limit
    return sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)


def _apply_fusion_adjustments(
    fused_entries: list[dict],
    result_by_id: dict[str, dict],
    outcome_map: dict[str, tuple],
) -> list[dict]:
    """Apply bounded pathway/valence adjustments to fused RRF scores."""
    adjusted: list[dict] = []
    for entry in fused_entries:
        nid = entry["cand"].get("node_id", "")
        result = result_by_id.get(nid, dict(entry["cand"]))

        ps = max(0.0, min(float(result.get("pathway_strength") or 0.0), PATHWAY_CAP))
        valence = 0.0
        if nid in outcome_map:
            avg_valence, _signal_count = outcome_map[nid]
            if avg_valence is not None:
                valence = float(avg_valence)
        valence = max(-1.0, min(1.0, valence))

        final = entry["rrf"] * (1.0 + (ps / (2.0 * PATHWAY_CAP))) * (1.0 + VALENCE_WEIGHT * valence)
        adjusted.append({
            "node_id": nid,
            "result": result,
            "rrf": entry["rrf"],
            "final": final,
            "sources": entry["sources"],
            "pathway_multiplier": 1.0 + (ps / (2.0 * PATHWAY_CAP)),
            "valence_multiplier": 1.0 + VALENCE_WEIGHT * valence,
            "valence": valence,
        })
    return adjusted


def _session_active_plan_id(db, session_id: str) -> str:
    try:
        r = db.execute(
            "MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
            "WHERE p.status = 'active' "
            "RETURN p.plan_id "
            "ORDER BY p.created_at DESC LIMIT 1",
            {"sid": session_id},
        )
        if r.has_next():
            return r.get_next()[0] or ""
    except Exception:
        pass
    return ""


def _get_pk_for_node_type(node_type: str) -> str:
    """Map node table name to its primary key column name."""
    return pk_for(node_type) or "id"
