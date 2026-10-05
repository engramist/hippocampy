"""B463: a question that names a category must still reach the current value.

Found by campy-benchmarks' LoCoMo fixture: p1_current_db, "What is our active
production database engine and version?", was answered "Primary database" in
every real-model run. No user message contains any of the question's words,
"CRITICAL UPDATE: We have completely migrated from PostgreSQL 14 to PostgreSQL
16 ..." scores 0.253 against the 0.30 floor (all-MiniLM-L6-v2), and the only
vector hits are the two assistant turns (0.339, 0.318), which are never
evidence (ISSUE-024). The graph holds "PostgreSQL 16 REPLACES PostgreSQL 14"
(B460), but nothing went from the question to it.

The conversation stage now follows REPLACES edges from what its on-topic
messages name to the head of the chain, and adds the user's own statements
naming that head. Embeddings are hand-built to the measured similarities, so
the tests don't depend on the embedding model.
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
DB_Q = "What is our active production database engine and version?"

PG14_USER = ("Our service uses PostgreSQL 14 hosted on AWS RDS. Constraint: all tables "
             "must use UUID primary keys.")
PG14_ACK = "Noted. Primary database is PostgreSQL 14 with UUID primary keys across all tables."
BIGINT = ("We noticed high index bloat with random UUIDs. Update constraint: new analytics "
          "tables should use BIGINT sequence IDs.")
PG16_USER = ("CRITICAL UPDATE: We have completely migrated from PostgreSQL 14 to PostgreSQL 16. "
             "Constraint: do NOT use PostgreSQL 14 anymore, all new deployments target "
             "PostgreSQL 16.")
PG16_ACK = ("Acknowledged. PostgreSQL 14 is deprecated. All deployments must strictly target "
            "PostgreSQL 16.")
REDIS_USER = "Memcached retired. Redis on port 6379 is now the active cache and lock store."


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b463.db"), REGISTRY)


class _Store:
    """Messages at a chosen cosine similarity to QUERY_EMB (each on its own
    orthogonal axis), and Concepts / REPLACES edges as consolidation writes them."""

    def __init__(self, gw):
        self.gw, self.n, self.c, self.ids = gw, 0, 0, {}

    async def msg(self, text: str, role: str, cos: float) -> None:
        self.n += 1
        emb = [0.0] * DIM
        emb[0], emb[self.n] = cos, math.sqrt(1.0 - cos * cos)
        await self.gw.run(
            "capture.create_message",
            message_id=f"m{self.n}", text_raw=text, embedding=emb, embedding_model="m",
            embedding_dim=DIM, role=role, byte_end=len(text),
            created_at=f"2026-10-02T10:{self.n:02d}:00+00:00",
        )

    async def concept(self, name: str, flagged: bool = False) -> str:
        self.c += 1
        emb = [0.0] * DIM
        emb[DIM - self.c] = 1.0  # orthogonal to the query: never a vector hit
        cid = self.ids[name] = f"c{self.c}"
        await self.gw.run(
            "orchestrator.create_concept",
            concept_id=cid, text_raw=name, embedding=emb, embedding_model="m",
            embedding_dim=DIM, gist_class="", schema_org_type="", confidence=0.9,
            confidence_low=False, pathway_strength=0.6, salience_score=1.0,
            anomaly_type="", flagged_for_review=flagged,
            created_at="2026-10-02T09:00:00+00:00",
        )
        return cid

    async def replaces(self, new: str, old: str) -> None:
        await self.gw.run(
            "orchestrator.merge_semantic_rel_replaces",
            hid=new, tid=old, confidence=0.85, inferred_by="step1b",
            now="2026-10-02T11:00:00+00:00",
        )


async def _bundle(gw, query: str = DB_Q) -> list[str]:
    rows = await gw.run("thalamus.bundle_conversation",
                        query_embedding=QUERY_EMB, query_text=query, limit=6)
    return [r["text"] for r in rows]


async def _db_store(gw, edge: bool = True) -> _Store:
    """LoCoMo's locomo_01_db_migration at the similarities MiniLM gave it, with
    the concepts the real-model store holds."""
    s = _Store(gw)
    await s.msg(PG14_USER, "user", 0.21)
    await s.msg(PG14_ACK, "assistant", 0.339)
    await s.msg(BIGINT, "user", 0.12)
    await s.msg("Acknowledged BIGINT sequence IDs for new analytics tables.", "assistant", 0.15)
    await s.msg(PG16_USER, "user", 0.253)
    await s.msg(PG16_ACK, "assistant", 0.318)
    await s.msg(REDIS_USER, "user", 0.05)
    await s.concept("PostgreSQL")
    await s.concept("Primary database")
    pg14 = await s.concept("PostgreSQL 14")
    pg16 = await s.concept("PostgreSQL 16")
    if edge:
        await s.replaces(pg16, pg14)
    return s


@pytest.mark.asyncio
async def test_category_question_reaches_the_statement_of_the_current_value(gw):
    await _db_store(gw)
    texts = await _bundle(gw)
    assert PG16_USER in texts


@pytest.mark.asyncio
async def test_assistant_text_still_never_becomes_evidence(gw):
    # The assistant turns choose which entity to follow; the bundle holds only
    # what the user said.
    await _db_store(gw)
    texts = await _bundle(gw)
    assert PG14_ACK not in texts and PG16_ACK not in texts
    rows = await gw.run("thalamus.bundle_conversation",
                        query_embedding=QUERY_EMB, query_text=DB_Q, limit=6)
    assert all(r["role"] == "user" for r in rows)


@pytest.mark.asyncio
async def test_without_a_replaces_edge_nothing_is_added(gw):
    # No graph evidence of supersession: the stage behaves as before (B459's
    # test pins that this store yields no user statement).
    await _db_store(gw, edge=False)
    assert await _bundle(gw) == []


@pytest.mark.asyncio
async def test_unrelated_supersession_is_not_pulled_in(gw):
    # "Redis REPLACES Memcached" is in the graph, but no on-topic message names
    # Memcached, so the cache statement stays out of a database bundle.
    s = await _db_store(gw)
    redis, memcached = await s.concept("Redis"), await s.concept("Memcached")
    await s.replaces(redis, memcached)
    texts = await _bundle(gw)
    assert PG16_USER in texts
    assert REDIS_USER not in texts


@pytest.mark.asyncio
async def test_a_name_inside_a_longer_concept_name_is_not_followed(gw):
    # Two conversations: api_format went JSON REST -> GraphQL, rpc_framework
    # went REST -> gRPC. "we use JSON REST" names the concept "JSON REST", not
    # "REST", so the gRPC statement stays out of the api_format bundle.
    s = _Store(gw)
    await s.msg("Acknowledged JSON REST for api_format.", "assistant", 0.45)
    graphql = "Final decision: JSON REST has been replaced by GraphQL for api_format."
    grpc = "Final decision: REST has been replaced by gRPC for rpc_framework."
    await s.msg(graphql, "user", 0.10)
    await s.msg(grpc, "user", 0.02)
    json_rest, gql = await s.concept("JSON REST"), await s.concept("GraphQL")
    rest, grpc_c = await s.concept("REST"), await s.concept("gRPC")
    await s.replaces(gql, json_rest)
    await s.replaces(grpc_c, rest)
    texts = await _bundle(gw, "Which interface style do we expose?")
    assert graphql in texts
    assert grpc not in texts


@pytest.mark.asyncio
async def test_follows_the_chain_to_its_head(gw):
    s = _Store(gw)
    await s.msg("Acknowledged Jaeger standalone for tracing.", "assistant", 0.45)
    await s.msg("Constraint for tracing: we use Jaeger standalone.", "user", 0.10)
    zipkin_stmt = "Update: Jaeger standalone is deprecated; migrate to Zipkin."
    otel_stmt = "Final decision: Zipkin has been replaced by OpenTelemetry OTel."
    await s.msg(zipkin_stmt, "user", 0.10)
    await s.msg(otel_stmt, "user", 0.10)
    jaeger = await s.concept("Jaeger standalone")
    zipkin = await s.concept("Zipkin")
    otel = await s.concept("OpenTelemetry OTel")
    await s.replaces(zipkin, jaeger)
    await s.replaces(otel, zipkin)
    texts = await _bundle(gw, "Which observability product do we run?")
    assert otel_stmt in texts
    # the intermediate value is not the current one; only the head is followed
    assert zipkin_stmt not in texts


@pytest.mark.asyncio
async def test_flagged_head_is_not_followed(gw):
    s = await _db_store(gw, edge=False)
    pg17 = await s.concept("PostgreSQL 17", flagged=True)
    await s.msg("Maybe PostgreSQL 17 someday.", "user", 0.01)
    await s.replaces(pg17, s.ids["PostgreSQL 14"])
    assert await _bundle(gw) == []


@pytest.mark.asyncio
async def test_at_most_the_two_newest_statements_per_head(gw):
    s = await _db_store(gw)
    for i in range(4):
        await s.msg(f"Reminder {i}: staging also runs PostgreSQL 16 now.", "user", 0.01)
    texts = await _bundle(gw)
    bridged = [t for t in texts if "PostgreSQL 16" in t]
    assert len(bridged) == 2
    assert bridged == ["Reminder 2: staging also runs PostgreSQL 16 now.",
                       "Reminder 3: staging also runs PostgreSQL 16 now."]


def test_search_phrase_needs_adjacent_words_within_prefixes(tmp_path):
    vs = VectorStore(tmp_path / "v.db")
    msg = "https://campy.dev/id/Message/"
    vs.index_text(msg + "1", "we migrated from PostgreSQL 14 to PostgreSQL 16.")
    vs.index_text(msg + "2", "PostgreSQL 14 is pinned at version 16 of the chart")
    vs.index_text("https://campy.dev/id/Concept/3", "PostgreSQL 16")
    assert vs.search_phrase("PostgreSQL 16", k=10, uri_prefixes=(msg,)) == [msg + "1"]
    assert set(vs.search_phrase("postgresql 16", k=10)) == {msg + "1", "https://campy.dev/id/Concept/3"}
    assert vs.search_phrase("", k=10) == []
