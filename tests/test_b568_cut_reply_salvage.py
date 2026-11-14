"""B568: a reply cut off at the output token limit keeps its complete facts; a reply broken some other way stays
malformed. Made-up turns, scripted LLM, real Oxigraph store, no model."""

from __future__ import annotations

import json

import pytest

from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex
from tests.b564_helpers import NS, Q, World, cfg, claim, extract

TEXT = "I bought a red kayak and I adopted a puppy named Pip last spring."
A = claim("I bought a red kayak", "a red kayak", predicate="owns")
B = claim("I adopted a puppy named Pip", "a puppy named Pip")


def cut(*items, tail='{\n    "subject": "I",\n    "predicate": "did",\n    "obj'):
    """A JSON array of `items` cut off inside the next object, as a reply that hit the token limit looks."""
    body = ",\n  ".join(json.dumps(i, indent=2) for i in items)
    return "[\n  " + body + ",\n  " + tail


class Reply:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.raw


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b568.db")


@pytest.fixture
def world(db):
    return World(db, GraphGateway(db, REGISTRY))


def quotes(db):
    rows = db._execute_and_collect(f"SELECT ?q WHERE {{ ?o a {NS}Observation> ; {NS}evidence_text> ?q }}")
    return sorted(str(r["q"]) for r in rows)


def test_salvage_keeps_complete_objects_and_drops_the_partial_one():
    raw = cut(A, B)
    assert ex.parse_observations(raw) is None
    assert ex.salvage_cut_reply(raw) == [A, B]
    assert ex.salvage_cut_reply("```json\n" + raw) == [A, B]


def test_salvage_refuses_what_is_not_a_cut_array():
    stray = '[\n  {"subject": "I", "quote": ""Brave" is my song", "predicate": "prefers"}\n]'
    assert ex.salvage_cut_reply(stray) == []                     # closed array, broken inside: stays malformed
    assert ex.salvage_cut_reply('[\n  {"subject": "I", "predicate": "did", "obj') == []   # no complete object
    assert ex.salvage_cut_reply("Sorry, I cannot help.") == []
    assert ex.salvage_cut_reply(None) == []
    assert ex.salvage_cut_reply('[ {"a": 1}, oops {"b": 2}') == [{"a": 1}]          # stops at junk between items


async def test_cut_reply_writes_its_complete_facts(db, world):
    _mid, stats = await extract(db, cfg(), world, TEXT, Reply(cut(A, B)), speaker="Nora")
    assert quotes(db) == ["I adopted a puppy named Pip", "I bought a red kayak"]
    assert (stats.malformed, stats.cut_replies, stats.salvaged_items, stats.proposed) == (0, 1, 2, 2)


async def test_stray_quote_reply_stays_malformed(db, world):
    raw = '[\n  {"subject": "I", "predicate": "owns", "object": "a kayak", "quote": ""I bought" a kayak"}\n]'
    _mid, stats = await extract(db, cfg(), world, TEXT, Reply(raw), speaker="Nora")
    assert quotes(db) == [] and stats.malformed == 1 and stats.cut_replies == 0


async def test_cut_reply_items_go_through_the_same_rules(db, world):
    bad = claim("a quote that is not in the turn", "something", predicate="did")
    _mid, stats = await extract(db, cfg(), world, TEXT, Reply(cut(A, bad)), speaker="Nora")
    assert quotes(db) == ["I bought a red kayak"]
    assert stats.salvaged_items == 2 and stats.rejected.get("quote_not_found") == 1
