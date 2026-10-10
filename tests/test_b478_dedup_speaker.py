"""B478: the conversation stage's de-dup keys on (speaker, text), not text alone.

Two speakers saying the same sentence are two statements; one speaker
repeating a sentence is still collapsed to the newest copy.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b478.db"), REGISTRY)


async def _add(gw, n, text, speaker, created, cos=0.8):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at=created)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker,
                 occurred_at=created)


async def _rows(gw):
    return await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text="zzqx", limit=6, order="time")


@pytest.mark.asyncio
async def test_two_speakers_saying_the_same_thing_both_survive(gw):
    await _add(gw, 1, "I love hiking in the mountains", "Caroline", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "I love hiking in the mountains", "Melanie", "2023-05-02T10:00:00+00:00")
    rows = await _rows(gw)
    assert sorted(r["speaker"] for r in rows) == ["Caroline", "Melanie"]


@pytest.mark.asyncio
async def test_one_speaker_repeating_keeps_the_newest(gw):
    await _add(gw, 1, "I love hiking in the mountains", "Caroline", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "I love hiking in the mountains", "Caroline", "2023-05-09T10:00:00+00:00")
    rows = await _rows(gw)
    assert [r["node_id"].rsplit("/", 1)[-1] for r in rows] == ["m2"]
