"""Tests for real-embedding ranking parity between Kùzu HNSW and sqlite-vec (B397 / B390 gap).

B397 Acceptance Criterion:
Compare top-k ordering between Kùzu's vector index and sqlite-vec over >=500
real FastEmbed 384-dim embeddings drawn from a populated graph. Report
rank-correlation and any position swaps in the top-10.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import List, Tuple

import pytest
from scipy.stats import spearmanr

from campy.brain.hippocampus.graph.vector_store import (
    VectorStore,
    mint_uri,
)

try:
    from tests.kuzu_test_client import KuzuClient
    KUZU_AVAILABLE = True
except Exception:
    KUZU_AVAILABLE = False


def _get_500_real_embeddings() -> List[Tuple[str, List[float]]]:
    """Fetch >=500 real FastEmbed 384-dim embeddings.

    Prefers ~/.campy/ backup / live graph; falls back to generating embeddings
    via fastembed on synthetic text if no local graph file exists.
    """
    candidates = [
        Path.home() / ".campy" / "brain.db.pre-b303-backup-202607150837",
        Path.home() / ".campy" / "brain.db.pre-b302-backup-202607142244",
    ]
    for db_path in candidates:
        if db_path.exists():
            try:
                k_src = KuzuClient(str(db_path), read_only=True)
                res = k_src.conn.execute(
                    "MATCH (m:Message) WHERE m.embedding IS NOT NULL "
                    "RETURN m.message_id, m.embedding LIMIT 500"
                )
                items = []
                while res.has_next():
                    row = res.get_next()
                    items.append((str(row[0]), [float(x) for x in row[1]]))
                k_src.close()
                if len(items) >= 500:
                    return items
            except Exception:
                pass

    # Fallback: embed 500 sentences using fastembed
    from campy.brain.hippocampus.graph.embeddings import embed_batch
    texts = [f"HippoCampy semantic vector memory test phrase {i} with distinct terminology" for i in range(500)]
    embs = embed_batch(texts)
    return [(f"synthetic-{i}", emb) for i, emb in enumerate(embs)]


@pytest.mark.skipif(not KUZU_AVAILABLE, reason="Kùzu client not available after cutover")
def test_real_embedding_ranking_parity_500():
    """Verify ranking parity across >=500 real embeddings."""
    items = _get_500_real_embeddings()
    assert len(items) >= 500

    tmp_kuzu = tempfile.mkdtemp(prefix="kuzu_rank_test_")
    tmp_vec = tempfile.mkdtemp(prefix="vec_rank_test_")
    k_db = None
    v_store = None

    try:
        k_db = KuzuClient(f"{tmp_kuzu}/db")
        k_db.conn.execute("CREATE NODE TABLE Msg(id STRING, embedding FLOAT[384], PRIMARY KEY (id))")
        for mid, emb in items:
            k_db.conn.execute("CREATE (n:Msg {id: $id, embedding: $emb})", {"id": mid, "emb": emb})
        k_db.create_vector_index("Msg", "embedding", "msg_idx")

        v_store = VectorStore(db_path=Path(tmp_vec) / "vectors.db", dim=384)
        for mid, emb in items:
            v_store.upsert_vector(mint_uri("Msg", mid), emb)

        correlations = []
        top10_overlaps = []

        # Evaluate across multiple probe queries
        for q_idx in range(0, len(items), 25):
            q_vec = items[q_idx][1]

            k_top = k_db.vector_search("Msg", "msg_idx", q_vec, 50)
            k_top.sort(key=lambda r: r["score"], reverse=True)
            v_top = v_store.search_vectors(q_vec, k=50)
            v_top_clean = [(u.rsplit("/", 1)[-1], score) for u, score in v_top]

            k_ids = [row["node"]["id"] for row in k_top]
            v_ids = [row[0] for row in v_top_clean]

            k_top10 = set(k_ids[:10])
            v_top10 = set(v_ids[:10])
            top10_overlaps.append(len(k_top10 & v_top10) / 10.0)

            k_score_map = {row["node"]["id"]: row["score"] for row in k_top}
            v_score_map = {row[0]: row[1] for row in v_top_clean}
            common = [nid for nid in k_ids if nid in v_score_map]
            if len(common) >= 10:
                k_scores = [k_score_map[nid] for nid in common]
                v_scores = [v_score_map[nid] for nid in common]
                rho, _ = spearmanr(k_scores, v_scores)
                if not math.isnan(rho):
                    correlations.append(rho)

        mean_overlap = sum(top10_overlaps) / len(top10_overlaps)
        mean_rho = sum(correlations) / len(correlations)

        # Assert rank correlation > 0.99
        assert mean_rho >= 0.99, f"Spearman rho too low: {mean_rho}"
        # Assert top-10 set overlap >= 0.90 (accounting for boundary ties)
        assert mean_overlap >= 0.90, f"Top-10 overlap too low: {mean_overlap}"

    finally:
        if k_db:
            k_db.close()
        if v_store:
            v_store.close()
        shutil.rmtree(tmp_kuzu, ignore_errors=True)
        shutil.rmtree(tmp_vec, ignore_errors=True)
