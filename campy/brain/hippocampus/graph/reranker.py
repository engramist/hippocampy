"""B477: optional cross-encoder rerank of the conversation stage's candidates.

The conversation stage fuses the vector and FTS planes by reciprocal rank and
keeps the top `conversation_limit` turns. On LoCoMo-10 the turn that holds the
answer has median fused rank ~28, so a limit of 6 misses it, and raising the
limit raised recall but not accuracy while doubling latency (plan M2.1): the
bi-encoder ordering is too coarse. A cross-encoder reads (question, turn)
together and orders a short list much better, at the cost of one small model
pass over the candidates.

Backend: fastembed's `TextCrossEncoder` (ONNX Runtime) -- the same runtime
that already serves the embedding model (B355), so no PyTorch and no new
dependency. Default checkpoint to use with it: `Xenova/ms-marco-MiniLM-L-6-v2`
(MS MARCO MiniLM-L6 cross-encoder, 91 MB ONNX). Loaded lazily, once per
process, shared across threads. Any failure (package missing, model not
downloadable, offline cache miss, ONNX error) is logged ONCE and `score()`
returns None, which the caller treats as "keep the fused order".

`[retrieval] reranker = "none"` (default) never reaches this module.

Scoring input and blending (R34 gate). The first version scored each turn as
"<speaker>: <text>" and let the cross-encoder order REPLACE the fused order.
Gate result, eval_gate replay on golden stores, reranker on vs main:
LoCoMo-10 dev 0.317 -> 0.383 (gained 7, lost 3), a real gain; DMR dev
0.520 -> 0.400 (gained 2, lost 8), a regression. The lost DMR questions
(valid_18, 28, 31) read "Speaker 2 asks Speaker 1 ... what Speaker 1 said
earlier": scored with its speaker label, the cross-encoder matches the label in
the question's framing and promotes the OTHER speaker's turns ("Speaker 2:
Cute! Where do you hike? My pet ... is a cow") over the right one ("Speaker 1:
He is a black lab named trooper"). And replacing discarded the fused ranking's
speaker-aware embedding signal (B472 1b embeds the speaker with the turn).
So: (1) the cross-encoder scores the bare turn text, and (2)
`[retrieval] reranker_mode = "blend"` (default) orders the reranked window by
reciprocal rank fusion (k=60) of the fused rank and the cross-encoder rank;
"replace" keeps the cross-encoder order alone.

`CALLS` counts successful scoring passes in this process and the first one
logs "reranker active: <model> mode=<mode>" at INFO (local debugging aid).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

_logger = logging.getLogger(__name__)

NONE_VALUES = ("", "none", "off", "false", "0")
DEFAULT_CANDIDATES = 50
MODES = ("blend", "replace")
DEFAULT_MODE = "blend"
RRF_K = 60

CALLS = 0                         # successful score() passes this process
_announced = False

_lock = threading.Lock()          # guards _models/_failed and serialises scoring
_models: dict[str, Callable[[str, list[str]], list[float]]] = {}
_failed: set[str] = set()


def is_enabled(name: Any) -> bool:
    return str(name or "").strip().lower() not in NONE_VALUES


def _load(model_name: str) -> Callable[[str, list[str]], list[float]]:
    """Build a `(query, texts) -> scores` callable for `model_name`. Raises on
    failure. Tests replace this to inject a fake scorer."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from campy.brain.hippocampus.graph.embeddings import _is_offline_enabled

    model = TextCrossEncoder(
        model_name=model_name, providers=["CPUExecutionProvider"],
        local_files_only=_is_offline_enabled())
    # fastembed's rerank() is a lazy generator; materialise it here.
    return lambda query, texts: [float(s) for s in model.rerank(query, texts)]


def score(model_name: str, query: str, texts: list[str]) -> Optional[list[float]]:
    """Cross-encoder scores, one per text, higher = more relevant; None when
    the model is unavailable or failed (logged once per model). Blocking and
    CPU-bound: call from a worker thread (the gateway dispatches the reranked
    conversation query via `asyncio.to_thread`)."""
    if not texts:
        return []
    with _lock:
        if model_name in _failed:
            return None
        try:
            fn = _models.get(model_name)
            if fn is None:
                fn = _models[model_name] = _load(model_name)
            scores = fn(query, texts)
            if len(scores) != len(texts):
                raise ValueError(f"scorer returned {len(scores)} scores for {len(texts)} texts")
            global CALLS
            CALLS += 1
            return scores
        except Exception as e:
            _failed.add(model_name)
            _models.pop(model_name, None)
            _logger.warning(
                "[retrieval] reranker=%r unavailable (%s: %s); conversation stage keeps "
                "the fused vector+FTS order", model_name, type(e).__name__, e)
            return None


def normalize_mode(mode: Any) -> str:
    m = str(mode or "").strip().lower()
    return m if m in MODES else DEFAULT_MODE


def announce(model_name: str, mode: str) -> None:
    """Log once per process that the reranker is scoring."""
    global _announced
    if not _announced:
        _announced = True
        _logger.info("reranker active: %s mode=%s", model_name, mode)


def reset() -> None:
    """Forget loaded models, recorded failures and counters (tests)."""
    global CALLS, _announced
    with _lock:
        CALLS = 0
        _announced = False
        _models.clear()
        _failed.clear()
