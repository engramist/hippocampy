"""B470: a query word most Messages contain must not let the conversation
stage's FTS list double-count every vector hit.

Found by campy-benchmarks on LoCoMo-10 (R8-R11, 2026-10-06). The speaker
names are in ~80% of a conversation's turns, so "Where has Melanie camped?"
matched nearly every Message lexically. In the reciprocal-rank fusion every
vector hit then got a second term from the FTS list, and the evidence turn,
found only by FTS (its rare word at FTS rank 0, its similarity under the
0.30 floor), could not outscore them. Replayed on the kept store
(diag_locomo10_fusion.py), dropping terms in > 20% of the Messages from the
FTS query raised the stage's evidence recall at limit 6 from 0.319 to 0.377
and lost no question.

The embeddings are hand-built (as in test_b459), so the tests don't depend
on the embedding model.
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
EVIDENCE = "Caroline: we went camping by the lake last weekend."
QUESTION = "Where has Caroline gone camping?"


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b470.db"), REGISTRY)


class _Store:
    """Adds messages whose embedding has a chosen cosine similarity to
    QUERY_EMB (each on its own orthogonal axis)."""

    def __init__(self, gw):
        self.gw, self.n = gw, 0

    async def add(self, text: str, cos: float, role: str = "user") -> None:
        self.n += 1
        emb = [0.0] * DIM
        emb[0], emb[self.n % (DIM - 1) + 1] = cos, math.sqrt(1.0 - cos * cos)
        await self.gw.run(
            "capture.create_message",
            message_id=f"m{self.n}", text_raw=text, embedding=emb, embedding_model="m",
            embedding_dim=DIM, role=role, byte_end=len(text),
            created_at=f"2026-10-06T{self.n // 60:02d}:{self.n % 60:02d}:00+00:00",
        )


async def _bundle(gw, query: str) -> list[str]:
    rows = await gw.run("thalamus.bundle_conversation",
                        query_embedding=QUERY_EMB, query_text=query, limit=6, order="time")
    return [r["text"] for r in rows]


async def _chat(gw, filler: int) -> None:
    """A two-person chat: every turn names a speaker. 8 on-topic-sounding
    turns are vector hits (0.35-0.45) that also name Caroline; the evidence
    is the only turn with "camping" and sits under the similarity floor."""
    s = _Store(gw)
    for i in range(8):
        await s.add(f"Caroline: that sounds lovely, tell me more about it ({i}).", 0.45 - i * 0.01)
    await s.add(EVIDENCE, 0.25)
    for i in range(filler):
        who = "Caroline" if i % 2 else "Melanie"
        await s.add(f"{who}: chatting about the weekend plans, number {i}.", 0.05)


@pytest.mark.asyncio
async def test_the_rare_word_turn_beats_vector_hits_that_only_share_the_name(gw):
    await _chat(gw, filler=60)
    assert EVIDENCE in await _bundle(gw, QUESTION)


@pytest.mark.asyncio
async def test_a_small_store_keeps_the_whole_query(gw):
    # Under _COMMON_TERM_MIN_DOCS Messages a share means little, so the query
    # is unchanged: the name-sharing vector hits still fill the bundle.
    await _chat(gw, filler=10)
    texts = await _bundle(gw, QUESTION)
    assert len(texts) == 6 and EVIDENCE not in texts


def _lexical_query(gw, vs: VectorStore, question: str) -> str:
    from campy.brain.hippocampus.graph.vector_store import fts_content_terms

    gw._vector_store = vs
    prefixes = ("https://campy.dev/id/Message/",)
    terms = fts_content_terms(question)
    return gw._lexical_query(question, terms, vs.document_frequencies(terms, prefixes), prefixes)


def test_lexical_query_drops_common_single_words_and_possessives(gw, tmp_path):
    vs = VectorStore(tmp_path / "v.db")
    for i in range(60):
        vs.index_text(f"https://campy.dev/id/Message/{i}", f"Melanie said hello again {i}")
    vs.index_text("https://campy.dev/id/Message/x", "Melanie took the kids camping")
    assert _lexical_query(gw, vs, "Where has Melanie camped?") == "Where has camped?"
    assert _lexical_query(gw, vs, "What do Melanie's kids like?") == "What do kids like?"
    # every content word is common: the query stays whole
    assert _lexical_query(gw, vs, "Melanie said hello?") == "Melanie said hello?"
    # a multi-part id is never split or dropped
    assert _lexical_query(gw, vs, "Melanie note memgym_path_ep3") == "note memgym_path_ep3"


def test_count_documents_within_prefixes(tmp_path):
    vs = VectorStore(tmp_path / "v.db")
    vs.index_text("https://campy.dev/id/Message/1", "a")
    vs.index_text("https://campy.dev/id/Message/2", "b")
    vs.index_text("https://campy.dev/id/Concept/3", "c")
    assert vs.count_documents(("https://campy.dev/id/Message/",)) == 2
    assert vs.count_documents() == 3
