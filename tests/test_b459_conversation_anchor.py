"""B459: the conversation stage must not drop the statements that supersede
the one it found.

Found by campy-benchmarks' LoCoMo fixture (2026-10-02): "What is the current
required tool for tracing?" was answered "Jaeger standalone" -- the first of
three values -- in every run. The bundle held "Constraint for tracing: we use
Jaeger standalone." but neither "Update: ... migrate tracing to Zipkin" nor
"Final decision: ... OpenTelemetry OTel". Measured on the kept store with
all-MiniLM-L6-v2 (campy-benchmarks diag_conversation_stage.py), both scored
0.265 / 0.274 against the 0.30 similarity floor, and as lexical-only hits they
needed two query content words, but "tracing" was the only query word any
message contained.

The embeddings here are hand-built to those measured similarities, so the
tests don't depend on the embedding model.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.vector_store import VectorStore

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b459.db"), REGISTRY)


class _Store:
    """Adds messages whose embedding has a chosen cosine similarity to
    QUERY_EMB (each on its own orthogonal axis, so they don't interact)."""

    def __init__(self, gw):
        self.gw, self.n = gw, 0

    async def add(self, text: str, role: str, cos: float) -> None:
        self.n += 1
        emb = [0.0] * DIM
        emb[0], emb[self.n] = cos, math.sqrt(1.0 - cos * cos)
        await self.gw.run(
            "capture.create_message",
            message_id=f"m{self.n}", text_raw=text, embedding=emb, embedding_model="m",
            embedding_dim=DIM, role=role, byte_end=len(text),
            created_at=f"2026-10-02T10:{self.n:02d}:00+00:00",
        )


async def _bundle(gw, query: str) -> list[str]:
    rows = await gw.run("thalamus.bundle_conversation",
                        query_embedding=QUERY_EMB, query_text=query, limit=6, order="time")
    return [r["text"] for r in rows]


TRACING_Q = "What is the current required tool for tracing?"
UPDATE = "Update: Jaeger standalone is deprecated; migrate tracing to Zipkin."
FINAL = ("Final decision: Zipkin has been replaced by OpenTelemetry OTel. Constraint: strictly "
         "use OpenTelemetry OTel for tracing, do NOT use Jaeger standalone or Zipkin.")


async def _tracing_store(gw) -> None:
    s = _Store(gw)
    # LoCoMo's tracing scenario, at the similarities MiniLM gave it
    await s.add("Constraint for tracing: we use Jaeger standalone.", "user", 0.511)
    await s.add("Acknowledged Jaeger standalone for tracing.", "assistant", 0.454)
    await s.add(UPDATE, "user", 0.265)
    await s.add("Updated tracing to Zipkin.", "assistant", 0.400)
    await s.add(FINAL, "user", 0.274)
    await s.add("Confirmed OpenTelemetry OTel is now the current standard for tracing.", "assistant", 0.544)
    # "current" is a query word too, and more common in the store than "tracing"
    for i in range(8):
        await s.add(f"The current sprint {i} ends on Friday.", "user", 0.05)


@pytest.mark.asyncio
async def test_superseding_statements_reach_the_bundle(gw):
    await _tracing_store(gw)
    texts = await _bundle(gw, TRACING_Q)
    assert "Constraint for tracing: we use Jaeger standalone." in texts
    assert UPDATE in texts
    assert FINAL in texts
    assert texts.index(UPDATE) < texts.index(FINAL)  # chronological: the replacement reads last


@pytest.mark.asyncio
async def test_a_common_query_word_alone_is_still_not_evidence(gw):
    # "current" is in a top vector hit too, but it is not the query's rarest
    # word in the store ("tracing" is), so a message sharing only "current"
    # stays out.
    await _tracing_store(gw)
    texts = await _bundle(gw, TRACING_Q)
    assert not any("sprint" in t for t in texts)


@pytest.mark.asyncio
async def test_a_rare_query_word_the_vector_search_did_not_find_is_not_evidence(gw):
    # "active" is as rare as "database" here, but only "database" appears in
    # the messages the vector search ranked on topic. Without that
    # corroboration, an unrelated cache statement joins a database bundle.
    s = _Store(gw)
    await s.add("Noted. Primary database is PostgreSQL 14 with UUID primary keys across all tables.",
                "assistant", 0.339)
    await s.add("Acknowledged. PostgreSQL 14 is deprecated. All deployments must strictly target "
                "PostgreSQL 16.", "assistant", 0.318)
    await s.add("Memcached retired. Redis on port 6379 is now the active cache and lock store.",
                "user", 0.05)
    await s.add("We pinned the Python version to 3.11 for the search engine.", "user", 0.05)
    await s.add("Bump the TLS version and the template engine next week.", "user", 0.05)
    texts = await _bundle(gw, "What is our active production database engine and version?")
    assert not any("Redis" in t for t in texts)


def test_document_frequencies_counts_per_term_within_prefixes(tmp_path):
    vs = VectorStore(tmp_path / "v.db")
    vs.index_text("https://campy.dev/id/Message/1", "we use Jaeger for tracing")
    vs.index_text("https://campy.dev/id/Message/2", "migrate tracing to Zipkin")
    vs.index_text("https://campy.dev/id/Concept/3", "tracing")
    vs.index_text("https://campy.dev/id/Message_x/4", "tracing")  # `_` is literal, not a LIKE wildcard
    msgs = ("https://campy.dev/id/Message/",)
    assert vs.document_frequencies(["tracing", "zipkin", "nope"], msgs) == {
        "tracing": 2, "zipkin": 1, "nope": 0}
    assert vs.document_frequencies(["tracing"]) == {"tracing": 4}
    assert vs.document_frequencies(['tra"cing', "a b"], msgs) == {'tra"cing': 0, "a b": 0}
