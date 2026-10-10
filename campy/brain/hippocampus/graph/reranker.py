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
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

_logger = logging.getLogger(__name__)

NONE_VALUES = ("", "none", "off", "false", "0")
DEFAULT_CANDIDATES = 50

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
            return scores
        except Exception as e:
            _failed.add(model_name)
            _models.pop(model_name, None)
            _logger.warning(
                "[retrieval] reranker=%r unavailable (%s: %s); conversation stage keeps "
                "the fused vector+FTS order", model_name, type(e).__name__, e)
            return None


def reset() -> None:
    """Forget loaded models and recorded failures (tests)."""
    with _lock:
        _models.clear()
        _failed.clear()
