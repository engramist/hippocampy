"""B506: a claim's `object` returned as a JSON object/list is rendered structurally,
never stored as a Python repr. Shapes seen in the R72 LongMemEval stores."""

from __future__ import annotations

import pytest

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex

from tests.test_b472_observation_worker import (  # noqa: F401  (fixtures + helpers)
    FakeLLM, JOB, _message, _no_embedder, _reply, db, gw,
)


@pytest.mark.parametrize("obj,expected", [
    ({"name": "tripod options", "value": "Manfrotto MT057CXPRO4"}, "tripod options: Manfrotto MT057CXPRO4"),
    ({"attribute": "completed", "value": "20 videos"}, "completed: 20 videos"),
    ({"key": "reading", "amount": 3}, "reading: 3"),
    ({"field": "city", "value": "Denver"}, "city: Denver"),
    ({"to-watch list": "25"}, "to-watch list: 25"),
    ({"watched 5 MCU films": None}, "watched 5 MCU films"),
    ({"name": "reading", "value": None}, "reading"),
    (["a", "b", 3], "a; b; 3"),
    ("job: nurse", "job: nurse"),
])
def test_renders_known_shapes(obj, expected):
    assert ex._render_object(obj) == expected


@pytest.mark.parametrize("obj", [
    {"relation": "person", "value": "I"},          # unknown key shape
    {"name": "x", "value": "y", "extra": "z"},     # extra keys
    {"name": {"a": 1}, "value": "y"},              # nested
    {"attribute": "x", "value": ["a"]},            # nested value
    {"k": ["a"]},                                  # nested single-key value
    {}, [], [{"a": 1}], [["a"]],
])
def test_unrenderable_is_none(obj):
    assert ex._render_object(obj) is None


def test_clean_never_stringifies_containers():
    assert ex._clean({"a": 1}) is None and ex._clean(["a"]) is None
    assert ex._clean(" a  b ") == "a b" and ex._clean(5) == "5"


@pytest.mark.asyncio
async def test_dict_object_is_stored_rendered_and_unknown_dict_is_rejected(db, gw):
    await _message(gw)
    good = {**JOB, "object": {"attribute": "job", "value": "nurse"}}
    bad = {**JOB, "object": {"relation": "person", "value": "I"}}
    stats = ex.ObservationWorkerStats()
    n = await ex.process_turn(db, {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600}},
                              FakeLLM(_reply(good, bad)), "m1", stats)
    assert n == 1
    rows = await obs.observations_for_message(db, "m1")
    assert [r["object_text"] for r in rows] == ["job: nurse"]
    assert stats.rejected["object_unrenderable"] == 1
