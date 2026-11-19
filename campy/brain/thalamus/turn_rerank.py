"""
campy/brain/thalamus/turn_rerank.py -- B578: a cross-encoder reranks the conversation section's turns.

The conversation stage picks its turns by fused vector and lexical rank (plus the B548 graph vote). ND-5
(offline, the 809) showed the gold turns the section misses are mostly in a wider vector pool, ranked low by the
question's vector. This stage takes the section's turns plus the top `POOL` Messages by vector score
(`thalamus.bundle_conversation_rerank_candidates`), scores each as "<speaker>: <text>" against the question with a
cross-encoder, and keeps the section's own turn count (replace mode). Nothing else changes:

- the turns the graph vote proposed (B548) keep their slots; the scorer fills the others (a query result is not
  overridden by a model score);
- the kept turns are presented in the section's order ("time": oldest first; "rank": pinned first, then by score);
- other sections are not touched; turns stay verbatim Message nodes;
- nothing is written: the scores live only for this bundle compile.

Two modes, `[retrieval] turn_rerank_mode` (env `CAMPY_TURN_RERANK_MODE`):

- "replace" (default; the B578 gate killed it, -2.2 points): keep the section's own turn count, as above. It drops
  the turns next to the evidence, which the answer needs;
- "add" (ruled 2026-11-19; offline sizing ND-6): keep every turn the section already has and add the top `ADD_K`
  candidates that are not in it, each with the section's own neighbour window (the existing session windows,
  `thalamus.bundle_conversation_seed_windows`). Nothing is dropped, so the graph-vote turns stay too.

`[retrieval] turn_rerank` (default false; env `CAMPY_TURN_RERANK=1`), in no profile until gated.
`turn_rerank_model` names the fastembed cross-encoder, and `turn_rerank_path` is the local folder that holds it.
There is no download: a missing or unreadable model leaves the rows unchanged, with one warning.
The pool (100) and the batch size are fixed at ND-5's values; nothing is tuned on the benchmark.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, Sequence

_logger = logging.getLogger(__name__)

POOL = 100          # ND-5's candidate pool (top Messages by vector score); fixed
BATCH_SIZE = 32
THREADS = 4
DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
ADD_K = 5           # add mode: new turns per question; fixed by the ruling (ND-3's registered add value)
MODES = ("replace", "add")

Scorer = Callable[[str, Sequence[str]], Sequence[float]]

_lock = threading.Lock()
_scorers: dict[tuple[str, str], Optional[Scorer]] = {}
_warned: set[str] = set()


def turn_rerank_enabled(config: dict | None) -> bool:
    """`[retrieval] turn_rerank` (default false; env `CAMPY_TURN_RERANK=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("turn_rerank", False))


def turn_rerank_mode(config: dict | None) -> str:
    """`[retrieval] turn_rerank_mode`: "replace" (default) or "add"; anything else is "replace", with one warning."""
    mode = str(((config or {}).get("retrieval") or {}).get("turn_rerank_mode") or "replace").strip().lower()
    if mode not in MODES:
        _warn_once("mode:" + mode, "turn_rerank_mode %r is not one of %s; using 'replace'", mode, MODES)
        return "replace"
    return mode


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        _logger.warning(msg, *args)


def load_scorer(config: dict) -> Optional[Scorer]:
    """The cross-encoder from the configured local folder, loaded once per process; None when unavailable."""
    r = (config.get("retrieval") or {})
    model = str(r.get("turn_rerank_model") or DEFAULT_MODEL)
    path = str(r.get("turn_rerank_path") or "").strip()
    key = (model, path)
    with _lock:
        if key in _scorers:
            return _scorers[key]
        scorer: Optional[Scorer] = None
        if not path:
            _warn_once("nopath", "turn_rerank is on but [retrieval] turn_rerank_path is not set; turns not reranked")
        else:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                ce = TextCrossEncoder(model, specific_model_path=path, threads=THREADS)
                scorer = lambda q, docs: list(ce.rerank(q, list(docs), batch_size=BATCH_SIZE))
            except Exception as e:  # missing folder, bad files, no onnxruntime: fail soft
                _warn_once("load:" + path, "turn_rerank: cross-encoder %r at %r not loaded (%s); turns not reranked",
                           model, path, e)
        _scorers[key] = scorer
        return scorer


def _doc(row: Any) -> str:
    get = row.get if hasattr(row, "get") else (lambda k, d=None: d)
    speaker = str(get("speaker") or "").strip()
    text = str(get("text") or "").strip()
    return f"{speaker}: {text}" if speaker else text


def rerank_rows(rows: list, candidates: list, query: str, scorer: Scorer, *, pinned: set[str],
                order: str = "time") -> list:
    """Replace mode: keep len(rows) turns out of rows + candidates (deduplicated by node id).
    Rows whose node id is in `pinned` keep their place; the scorer ranks the rest."""
    n = len(rows)
    if n == 0:
        return rows
    seen: set[str] = set()
    pool: list = []
    for r in list(rows) + list(candidates):
        nid = str(r.get("node_id") or "")
        if not nid or nid in seen or not r.get("text"):
            continue
        seen.add(nid)
        pool.append(r)
    keep_pinned = [r for r in rows if str(r.get("node_id") or "") in pinned]
    free = [r for r in pool if str(r.get("node_id") or "") not in pinned]
    slots = max(0, n - len(keep_pinned))
    scores = list(scorer(query, [_doc(r) for r in free])) if free and slots else []
    best = [r for _, _, r in sorted(((-float(s), i, r) for i, (s, r) in enumerate(zip(scores, free))),
                                    key=lambda x: (x[0], x[1]))][:slots]
    if order == "rank":
        return keep_pinned + best
    kept = keep_pinned + best
    return sorted(kept, key=lambda r: (str(r.get("created_at") or ""), str(r.get("node_id") or "")))


def add_seeds(rows: list, candidates: list, query: str, scorer: Scorer, *, k: int = ADD_K) -> list:
    """Add mode, step 1: the top `k` candidates (by the scorer) that are not already in `rows`, best first."""
    have = {str(r.get("node_id") or "") for r in rows}
    seen: set[str] = set()
    fresh: list = []
    for r in candidates:
        nid = str(r.get("node_id") or "")
        if not nid or nid in have or nid in seen or not r.get("text"):
            continue
        seen.add(nid)
        fresh.append(r)
    if not fresh or k <= 0:
        return []
    scores = list(scorer(query, [_doc(r) for r in fresh]))
    ranked = sorted(((-float(s), i, r) for i, (s, r) in enumerate(zip(scores, fresh))), key=lambda x: (x[0], x[1]))
    return [r for _, _, r in ranked[:k]]


def merge_added(rows: list, added: list, *, order: str = "time") -> list:
    """Add mode fallback (the windows query failed): the section's rows, all kept, plus the added turns not already
    in them. "time": one stable sort by time; "rank": the section, then the added turns in the order given. The
    normal path orders by session sequence in the gateway (`thalamus.bundle_conversation_seed_windows`)."""
    have = {str(r.get("node_id") or "") for r in rows}
    extra, seen = [], set()
    for r in added:
        nid = str(r.get("node_id") or "")
        if nid and nid not in have and nid not in seen and r.get("text"):
            seen.add(nid)
            extra.append(r)
    if not extra:
        return rows
    out = list(rows) + extra
    if order == "rank":
        return out
    return sorted(out, key=lambda r: str(r.get("created_at") or ""))


async def rerank_conversation(db, rows: list, query: str, query_embedding, config: dict, *,
                              graph_turns: Sequence[str] = (), order: str = "time",
                              scorer: Optional[Scorer] = None, neighbours: int = 0, neighbour_cap: int = 0) -> list:
    """The conversation stage's rows, reranked when the flag is on; the rows unchanged otherwise or on failure."""
    if not turn_rerank_enabled(config) or not rows:
        return rows
    try:
        scorer = scorer or load_scorer(config)
        if scorer is None:
            return rows
        from campy.brain.hippocampus.graph.gateway import GRAPH_VOTE_TOP, get_gateway

        candidates = await get_gateway(db).run(
            "thalamus.bundle_conversation_rerank_candidates", query_embedding=query_embedding, limit=POOL)
        if turn_rerank_mode(config) == "add":
            seeds = add_seeds(list(rows), list(candidates or []), query, scorer, k=ADD_K)
            if not seeds:
                return rows
            merged = await get_gateway(db).run(
                "thalamus.bundle_conversation_seed_windows", rows=list(rows), seeds=seeds, query_text=query,
                neighbours=neighbours, neighbour_cap=neighbour_cap or ADD_K * 2 * neighbours, order=order)
            have = {str(r.get("node_id") or "") for r in rows}
            if merged and have <= {str(r.get("node_id") or "") for r in merged}:
                return list(merged)
            return merge_added(list(rows), seeds, order=order)  # fallback: seeds only, no window
        pinned = {str(u) for u in list(graph_turns)[:GRAPH_VOTE_TOP]}
        return rerank_rows(list(rows), list(candidates or []), query, scorer, pinned=pinned, order=order)
    except Exception as e:
        _logger.warning("Error in turn_rerank; the conversation section is unchanged: %s", e)
        return rows
