"""B471: a question about the assistant's own earlier words gets them, labelled
as the assistant's, in their own bundle section -- and no other question does.

Found by campy-benchmarks' LongMemEval (R10b, oracle, 35 questions):
single-session-assistant questions ("Which pasta shape did you suggest for
pesto?") had evidence recall 0.0, because the conversation stage keeps user
turns only (ISSUE-024). That rule stays for fact and decision bundles.

The embeddings are hand-built (as in test_b459), so the gateway tests don't
depend on the embedding model.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from campy.brain.thalamus.bundle_compiler import asks_about_assistant_words

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
SUGGESTION = "For pesto I'd go with trofie, the classic Ligurian shape; linguine works too."
QUESTION = "Which pasta shape did you suggest for pesto?"


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b471.db"), REGISTRY)


async def _add(gw, n: int, text: str, role: str, cos: float) -> None:
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run(
        "capture.create_message",
        message_id=f"m{n}", text_raw=text, embedding=emb, embedding_model="m",
        embedding_dim=DIM, role=role, byte_end=len(text),
        created_at=f"2026-10-06T10:{n:02d}:00+00:00",
    )


async def _pasta_chat(gw) -> None:
    await _add(gw, 1, "What pasta should I make with my pesto tonight?", "user", 0.62)
    await _add(gw, 2, SUGGESTION, "assistant", 0.55)
    await _add(gw, 3, "I'll make pesto with the basil from my garden.", "user", 0.48)
    await _add(gw, 4, "Garden basil is perfect; pick it just before blending.", "assistant", 0.41)
    await _add(gw, 5, "My train to work was late again today.", "assistant", 0.05)


async def _rows(gw, name: str, query: str, limit: int = 3) -> list[dict]:
    return await gw.run(name, query_embedding=QUERY_EMB, query_text=query, limit=limit)


@pytest.mark.asyncio
async def test_assistant_words_returns_only_on_topic_assistant_turns(gw):
    await _pasta_chat(gw)
    rows = await _rows(gw, "thalamus.bundle_assistant_words", QUESTION)
    texts = [r["text"] for r in rows]
    assert SUGGESTION in texts
    assert all(r["role"] == "assistant" for r in rows)
    assert not any("train" in t for t in texts)  # off topic
    assert not any("tonight" in t for t in texts)  # a user turn


@pytest.mark.asyncio
async def test_the_conversation_stage_still_keeps_user_turns_only(gw):
    # ISSUE-024 is unchanged for the fact/decision evidence.
    await _pasta_chat(gw)
    rows = await _rows(gw, "thalamus.bundle_conversation", QUESTION, limit=6)
    assert rows and SUGGESTION not in [r["text"] for r in rows]


@pytest.mark.parametrize("q", [
    QUESTION,
    "What was the name of the hotel you recommended?",
    "I remember you told me about a podcast, what was it?",
    "Did you mention any vegan restaurants?",
    "Can you remind me of your recommendation for running shoes?",
])
def test_questions_about_the_assistants_words(q):
    assert asks_about_assistant_words(q)


@pytest.mark.parametrize("q", [
    "Can you tell me where I live?",
    "Could you suggest a pasta shape for pesto?",
    "What did I say about my job?",
    "What is our production database engine?",
])
def test_other_questions(q):
    assert not asks_about_assistant_words(q)


class _FakeGateway:
    def __init__(self):
        self.calls = []

    async def run(self, name, **params):
        self.calls.append(name)
        return [{"text": SUGGESTION, "created_at": "2026-10-06T10:02:00+00:00", "node_id": "m2"}]


@pytest.fixture
def fake_gw(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    fake = _FakeGateway()
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: fake)
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return fake


@pytest.mark.asyncio
async def test_stage_labels_the_assistants_words_in_their_own_section(fake_gw):
    section = await bundle_compiler._stage_assistant_words(None, QUESTION, {})
    assert section.section_type == "assistant_said"
    assert section.content[0]["role"] == "assistant"
    assert section.content[0]["text"] == f"[assistant said, 2026-10-06 10:02] {SUGGESTION}"


@pytest.mark.asyncio
async def test_stage_is_skipped_for_other_questions_and_when_disabled(fake_gw):
    assert await bundle_compiler._stage_assistant_words(None, "What breed is my dog?", {}) is None
    cfg = {"retrieval": {"assistant_words_limit": 0}}
    assert await bundle_compiler._stage_assistant_words(None, QUESTION, cfg) is None
    assert fake_gw.calls == []


def test_ask_describes_the_section_as_the_assistants_words():
    from campy.brain.thalamus.ask import _SECTION_DESCRIPTIONS

    assert "not facts the user stated" in _SECTION_DESCRIPTIONS["assistant_said"]
