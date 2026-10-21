"""B499: rule-based supersession of attribute Observations.

Real Oxigraph store, no model. Pins:
- an older and a newer value for the same subject + attribute: the older is
  superseded (column + DEPRECATED_BY edge), the newer stays current;
- out-of-order ingest marks the incoming (older) row instead;
- other attributes, other subjects, other speakers' "I", non-attribute
  predicates, unparseable objects: untouched;
- flag off (the default): nothing changes;
- rendering marks a superseded row, and the bundle keeps it only with the flag on.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
QUESTION = "What is my personal best 5K time?"


def _vec(cos: float, axis: int) -> list[float]:
    v = [0.0] * DIM
    v[0], v[axis] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b499.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def attr(self, obj, date, *, supersede=True, speaker="Alex", subject="I",
                   predicate="has_attribute", polarity="asserted", subject_id=None):
        self.n += 1
        mid = f"m{self.n}"
        quote = f"{subject} thinks about {obj}" if subject != "I" else f"I think about {obj}"
        text = f"Hello. {quote}. Bye."
        await self.gw.run(
            "capture.create_message", message_id=mid, text_raw=text, embedding=None,
            embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
            created_at=f"{date}T12:00:00+00:00")
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker,
                          occurred_at=f"{date}T12:00:00+00:00")
        res = await obs.record_observation(self.db, obs.ObservationDraft(
            evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate=predicate,
            object_text=obj, extraction_method="llm", confidence=0.9, polarity=polarity,
            speaker=speaker, subject_id=subject_id, text_raw=f"{speaker} - {predicate} - {obj}",
            embedding=_vec(0.8, 10 + self.n)), supersede=supersede)
        assert res.status == "created", res
        return res.observation_id

    async def row(self, oid):
        return await obs.get_observation(self.db, oid)


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


async def _edges(db):
    rows = db._execute_and_collect(
        "SELECT ?a ?b WHERE { ?a <https://campy.dev/ns#DEPRECATED_BY> ?b }")
    return [(str(r["a"]).rsplit("/", 1)[-1], str(r["b"]).rsplit("/", 1)[-1]) for r in rows]


# --- the rule ---------------------------------------------------------------------

async def test_newer_value_supersedes_older(db, store):
    old = await store.attr("personal best 5K: 27:12", "2023-05-01")
    new = await store.attr("Personal  Best 5k: 25:50", "2023-06-10")
    o, n = await store.row(old), await store.row(new)
    assert o["superseded_by"] == new
    assert str(o["superseded_at"])[:10] == "2023-06-10"
    assert not n.get("superseded_by")
    assert await _edges(db) == [(old, new)]


async def test_out_of_order_ingest_supersedes_the_incoming_row(db, store):
    new = await store.attr("personal best 5K: 25:50", "2023-06-10")
    old = await store.attr("personal best 5K: 27:12", "2023-05-01")
    assert (await store.row(old))["superseded_by"] == new
    assert not (await store.row(new)).get("superseded_by")
    assert await _edges(db) == [(old, new)]


async def test_chain_leaves_only_the_latest_live(db, store):
    a = await store.attr("job: student", "2023-01-01")
    b = await store.attr("job: nurse", "2023-02-01")
    c = await store.attr("job: doctor", "2023-03-01")
    assert (await store.row(a))["superseded_by"] == b
    assert (await store.row(b))["superseded_by"] == c
    assert not (await store.row(c)).get("superseded_by")


@pytest.mark.parametrize("kwargs", [
    {"obj": "favourite colour: blue"},                       # different attribute
    {"obj": "personal best 5K: 25:50", "speaker": "Bea"},    # another speaker's "I"
    {"obj": "personal best 5K: 25:50", "subject": "Maya", "speaker": "Alex"},  # another subject
    {"obj": "personal best 5K: 25:50", "polarity": "negated"},
    {"obj": "personal best 5K: 25:50", "predicate": "owns"},
    {"obj": "no colon here"},
])
async def test_unrelated_claims_are_not_superseded(db, store, kwargs):
    first = await store.attr("personal best 5K: 27:12", "2023-05-01")
    kwargs = {**{"obj": ""}, **kwargs}
    other = await store.attr(kwargs.pop("obj"), "2023-06-10", **kwargs)
    assert not (await store.row(first)).get("superseded_by")
    assert not (await store.row(other)).get("superseded_by")
    assert await _edges(db) == []


async def test_subject_id_keys_the_subject(db, store, gw):
    for cid in ("c-maya",):
        await gw.run("temporal_lobe.dict_create_concept", cid=cid, text="Maya", emb=_vec(0.0, 300),
                     gist="Agent", stype="Person", now=__import__("datetime").datetime(2023, 1, 1))
    a = await store.attr("city: Oslo", "2023-01-01", subject="Maya", subject_id="c-maya")
    b = await store.attr("city: Bergen", "2023-02-01", subject="Maya", subject_id="c-maya")
    assert (await store.row(a))["superseded_by"] == b


async def test_flag_off_changes_nothing(db, store):
    a = await store.attr("personal best 5K: 27:12", "2023-05-01", supersede=False)
    b = await store.attr("personal best 5K: 25:50", "2023-06-10", supersede=False)
    assert not (await store.row(a)).get("superseded_by")
    assert not (await store.row(b)).get("superseded_by")
    assert await _edges(db) == []


def test_flag_default_off_and_env_override():
    assert _DEFAULT_CONFIG["observations"]["supersede"] is False
    assert obs.observations_supersede_enabled({}) is False
    assert obs.observations_supersede_enabled(_DEFAULT_CONFIG) is False
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_SUPERSEDE": "1"})["observations"]["supersede"] is True
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_SUPERSEDE": "0"})["observations"]["supersede"] is False
    assert "supersede" not in apply_env_overrides({}, {}).get("observations", {})


# --- rendering and retrieval ----------------------------------------------------------

def test_render_marks_a_superseded_row():
    row = {"speaker": "user", "observed_at": "2023-05-01T12:00:00", "predicate": "has_attribute",
           "subject_text": "I", "object_text": "personal best 5K: 27:12", "polarity": "asserted",
           "superseded_by": "x", "superseded_at": "2023-06-10T12:00:00"}
    assert bc.render_observation(row) == \
        "[user, 2023-05-01] (superseded 2023-06-10) has attribute: personal best 5K: 27:12"
    live = {k: v for k, v in row.items() if not k.startswith("superseded")}
    assert "superseded" not in bc.render_observation(live)


async def test_bundle_keeps_superseded_row_only_with_flag(db, store):
    await store.attr("personal best 5K: 27:12", "2023-05-01")
    await store.attr("personal best 5K: 25:50", "2023-06-10")
    base = {"observations": {"retrieval": True, "observation_limit": 8},
            "retrieval": {"conversation_token_budget": 0}}

    def lines(bundle):
        return [c["text"] for s in bundle.sections if getattr(s, "variant", "") == "observations"
                for c in s.content]

    off = lines(await bc.compile_bundle(QUESTION, db, base))
    assert len(off) == 1 and "25:50" in off[0]
    on = lines(await bc.compile_bundle(
        QUESTION, db, {**base, "observations": {**base["observations"], "supersede": True}}))
    assert len(on) == 2
    assert "(superseded 2023-06-10)" in on[0] and "27:12" in on[0]
    assert "superseded" not in on[1] and "25:50" in on[1]
