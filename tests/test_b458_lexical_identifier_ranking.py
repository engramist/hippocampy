"""B458: an exact identifier match must win over near-identical notes.

Found by campy-benchmarks' MemoryGym suite (2026-09-30): 20 notes of the form
"Observation at Step 0 for memgym_mysterypath_epN: ... path ...". A query
naming one episode got another episode's note back from current_truth.

Two causes, both in current_truth's RRF fusion:
- The FTS query is an OR of content words, so notes matching only the words
  every note shares (bm25 ~0: no lexical evidence) came back as lexical
  ranks 2..N, and rank-only RRF gave them full credit.
- A lexical-only hit and a vector-only hit at the same rank fuse to the same
  score; the tie fell to insertion order, where vector sources come first.

These tests use a real OxigraphClient (real FTS5 bm25) and hand-built
embeddings that, like all-MiniLM-L6-v2 on these notes, can't tell the
episodes apart and rank the target note low.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

import campy.brain.thalamus.tools as tools_mod
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

DIM = 384
EPISODES = 12
CONFIG = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}


def _vec(sim: float) -> list[float]:
    """Unit vector with cosine `sim` to the query vector e0."""
    v = [0.0] * DIM
    v[0], v[1] = sim, math.sqrt(max(0.0, 1.0 - sim * sim))
    return v


def _note(ep: int) -> str:
    path = " -> ".join(f"({ep}, {i})" for i in range(6))
    return (f"Observation at Step 0 for memgym_mysterypath_ep{ep}: "
            f"MysteryPath navigation sequence is: {path}")


@pytest.fixture()
def db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="b458_")
    client = OxigraphClient(f"{tmp}/db")
    if not client.has_fts():
        client.close()
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip("FTS not available in this environment")
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed",
                        lambda text, model_name=None: _vec(1.0))
    yield client
    client.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _store_episodes(db: OxigraphClient, target: int, target_sim: float) -> None:
    """All notes are near-identical to the query vector except the target,
    which the vector search ranks well down the list."""
    now = datetime.now(timezone.utc).isoformat()
    for ep in range(EPISODES):
        sim = target_sim if ep == target else 0.95 - 0.01 * ep
        db.write_node("Message", {
            "message_id": f"msg-ep{ep}", "text_raw": _note(ep), "role": "user",
            "confidence": 0.5, "confidence_low": True, "pathway_strength": 0.0,
            "archived": False, "created_at": now, "embedding": _vec(sim),
        })
    db.create_fts_index("Message", "message_fts_idx", ["text_raw"])


async def _top_id(db: OxigraphClient, target: int) -> str:
    res = await tools_mod.current_truth(
        {"query": f"MysteryPath navigation sequence for memgym_mysterypath_ep{target}",
         "session_id": "unknown"},
        db, CONFIG,
    )
    return res["results"][0]["node_id"]


async def test_exact_identifier_beats_similar_notes_ranked_higher_by_vectors(db):
    # Target is 6th in the vector ranking (inside the top 10), below notes
    # that also collect zero-evidence lexical credit; pre-B458 one of those
    # won.
    _store_episodes(db, target=7, target_sim=0.905)
    assert await _top_id(db, 7) == "msg-ep7"


async def test_exact_identifier_wins_when_outside_the_vector_top_n(db):
    # Target is outside current_truth's per-table vector limit, so it is a
    # lexical-only hit tied with the top vector-only hit (pre-B458 the tie
    # went to the vector hit).
    _store_episodes(db, target=7, target_sim=0.05)
    assert await _top_id(db, 7) == "msg-ep7"


def test_drop_weak_lexical_removes_zero_evidence_hits_only():
    from campy.brain.thalamus.tools._shared import _drop_weak_lexical

    rows = [{"id": "exact", "score": 2.5}, {"id": "partial", "score": 0.8},
            {"id": "noise", "score": 1e-6}]
    assert [r["id"] for r in _drop_weak_lexical(rows)] == ["exact", "partial"]


def test_drop_weak_lexical_keeps_everything_when_no_hit_has_evidence():
    from campy.brain.thalamus.tools._shared import _drop_weak_lexical

    # Tiny stores: bm25 IDF degenerates and every hit scores ~0.
    rows = [{"id": "a", "score": 1e-6}, {"id": "b", "score": 0.0}]
    assert _drop_weak_lexical(rows) == rows
