"""B498: a node derived from a turn carries the turn's event time (occurred_at),
and relative dates resolve against it -- never against the capture time.

The capture time (created_at) is when Campy stored the turn; for an imported or
replayed history it can be years after the turn was said. Observations are the
derived nodes that render a date ([speaker, date]) and resolve time phrases, so
they are pinned here end to end: stored turn -> worker -> Observation -> render.
"""

from __future__ import annotations

import json

import pytest

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.thalamus.bundle_compiler import render_observation

EMB = [0.05] * 384
CAPTURED = "2026-10-20T09:00:00+00:00"      # when Campy stored the turn
SAID = "2023-05-08T12:00:00+00:00"          # when the turn was said
CFG = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600}}
TEXT = "I ran my charity 5K on May 6th and I visited the clinic last Saturday."


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply


def _fact(obj, time, quote):
    return {"subject": "I", "predicate": "did", "object": obj, "time": time,
            "polarity": "asserted", "quote": quote, "confidence": 0.9}


@pytest.fixture(autouse=True)
def _no_embedder(monkeypatch):
    monkeypatch.setattr(ex.emb, "embed", lambda text, model_name=None: EMB)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b498.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _turn(gw, occurred_at):
    await gw.run("capture.create_message", message_id="m1", text_raw=TEXT, embedding=None,
                 embedding_model="m", embedding_dim=384, role="user", byte_end=len(TEXT),
                 created_at=CAPTURED)
    if occurred_at:
        await gw.run("capture.set_message_source", message_id="m1", speaker="Melanie",
                     occurred_at=occurred_at)


async def _run(db):
    llm = FakeLLM(json.dumps([
        _fact("ran a charity 5K", "May 6th", "I ran my charity 5K on May 6th"),
        _fact("visited the clinic", "last Saturday", "I visited the clinic last Saturday"),
    ]))
    await ex.process_turn(db, CFG, llm, "m1", ex.ObservationWorkerStats())
    rows = await obs.observations_for_message(db, "m1")
    return llm, {r["object_text"]: r for r in rows}


@pytest.mark.asyncio
async def test_observations_take_the_source_turns_event_time_not_the_capture_time(db, gw):
    await _turn(gw, SAID)
    llm, by_obj = await _run(db)
    assert len(by_obj) == 2
    for row in by_obj.values():
        assert str(row["observed_at"]).startswith("2023-05-08")
        assert "2026" not in render_observation(row).split("]")[0]
        assert render_observation(row).startswith("[Melanie, 2023-05-08]")
    # the model is told the turn's date, not the capture date
    assert "2023-05-08" in llm.calls[0][-1]["content"] and "2026-10-20" not in llm.calls[0][-1]["content"]


@pytest.mark.asyncio
async def test_relative_and_yearless_dates_resolve_against_the_event_time(db, gw):
    await _turn(gw, SAID)
    _, by_obj = await _run(db)
    yearless = render_observation(by_obj["ran a charity 5K"])
    relative = render_observation(by_obj["visited the clinic"])
    assert "2023-05-06" in yearless and "2026" not in yearless
    assert "2023-05-06" in relative and "2026" not in relative      # last Saturday before Mon 2023-05-08


@pytest.mark.asyncio
async def test_without_an_event_time_the_capture_time_is_the_fallback(db, gw):
    await _turn(gw, None)
    _, by_obj = await _run(db)
    row = by_obj["ran a charity 5K"]
    assert str(row["observed_at"]).startswith("2026-10-20")
    assert "2026-05-06" in render_observation(row)
