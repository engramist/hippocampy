"""Object-text matching: question words resolved to the object text of the subject's own live facts, by vector.

For the question's subject, each filtered question term is matched by sentence vector against the distinct
`object_text` of the subject's live Observations (`query_hits.object_texts_of_subject`); the top `TOP_K` texts per
term with cosine >= `THRESHOLD` are returned. The facts that carry those texts are then read by the subject-anchored
`query_hits.facts*` queries (their `texts` parameter), so which facts there are, how many, and which is latest are
computed in SPARQL. Python here only filters terms, embeds, and ranks vectors; it never counts, filters or joins
rows. Nothing is written to the graph or to vectors.db; the vectors live in a bounded in-process cache.

Read by `graph_facts.build_graph_facts_section` behind `[retrieval] object_text_match` (env
`CAMPY_OBJECT_TEXT_MATCH`, default off, in no profile).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from array import array
from collections import OrderedDict
from math import sqrt

_logger = logging.getLogger(__name__)

THRESHOLD = 0.75        # cosine at or above which a pool text is a match (a module constant, not a config key)
TOP_K = 3               # texts kept per question term
_CACHE_MAX = 4096       # vectors held in process: 384 dims x 8 bytes, about 13 MB at the cap
_CHUNK = 256            # texts per embedding call

_cache: "OrderedDict[tuple[str, str], array]" = OrderedDict()
_lock = threading.Lock()


def object_text_match_enabled(config: dict | None) -> bool:
    """`[retrieval] object_text_match` (default false; env `CAMPY_OBJECT_TEXT_MATCH=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("object_text_match", False))


def filtered_terms(pairs, subject_label: str | None) -> list[str]:
    """The question's terms (as (term, position) pairs) worth matching: lower-cased, whitespace-normalised, each once,
    longer than two characters, not made only of stop words, and not the subject's own label. Terms that equal a
    Concept label are removed afterwards by `query_hits.labels_in`; those are the exact-label read's."""
    from spacy.lang.en.stop_words import STOP_WORDS

    out: list[str] = []
    for t, _ in pairs:
        low = " ".join(str(t).lower().split())
        if low in out or len(low) <= 2 or all(w in STOP_WORDS for w in low.split()):
            continue
        if subject_label and low == subject_label.lower():
            continue
        out.append(low)
    return out


def _unit(vec) -> array:
    n = sqrt(sum(x * x for x in vec)) or 1.0
    return array("d", [x / n for x in vec])


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _vectors(texts: list[str]) -> list[array]:
    """The unit vector of each text, in order; texts not in the cache are embedded (in chunks) and cached."""
    from campy.brain.hippocampus.graph import embeddings

    model = getattr(embeddings, "MODEL_NAME", "")
    with _lock:
        miss = [t for t in dict.fromkeys(texts) if (model, t) not in _cache]
    for i in range(0, len(miss), _CHUNK):
        chunk = miss[i:i + _CHUNK]
        vecs = embeddings.embed_batch(chunk)
        with _lock:
            for t, v in zip(chunk, vecs):
                _cache[(model, t)] = _unit(v)
                _cache.move_to_end((model, t))
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    out = []
    with _lock:
        for t in texts:
            v = _cache.get((model, t))
            if v is not None:
                _cache.move_to_end((model, t))
            out.append(v)
    # a text evicted between embedding and reading (only when one call needs more than the cap) is embedded again
    for i, v in enumerate(out):
        if v is None:
            out[i] = _unit(embeddings.embed_batch([texts[i]])[0])
    return out


def top_matches(qvec, pool: dict[str, array]) -> list[tuple[float, str]]:
    """The `TOP_K` pool texts nearest the term vector, as (cosine, text), best first; ties go to the larger text."""
    return sorted(((_dot(qvec, v), text) for text, v in pool.items()), reverse=True)[:TOP_K]


async def resolve_object_texts(gw, sid: str, pairs, subject_label: str | None) -> list[str]:
    """The object texts of the subject's live facts that the question's words match by vector (see module docstring),
    each once. `pairs` is `query_hits.question_terms(question)`. Empty when nothing matches."""
    cand = filtered_terms(pairs, subject_label)
    if not cand:
        return []
    known = {str(r["term"]) for r in await gw.run("query_hits.labels_in", terms=cand)}
    terms = [t for t in cand if t not in known]
    if not terms:
        return []
    pool_texts = [str(r["object_text"]) for r in await gw.run("query_hits.object_texts_of_subject", sid=sid)]
    if not pool_texts:
        return []
    vecs = await asyncio.to_thread(_vectors, terms + pool_texts)
    pool = dict(zip(pool_texts, vecs[len(terms):]))
    out: list[str] = []
    for qvec in vecs[:len(terms)]:
        out += [text for score, text in top_matches(qvec, pool) if score >= THRESHOLD]
    return list(dict.fromkeys(out))
