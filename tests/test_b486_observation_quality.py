"""B486: read-time quality filter for Observations.

Pure scoring rules (junk vs good examples taken from real extractions), config
and env wiring, and the stage: flag off is byte-identical, flag on drops junk
and backfills the slots with the next-best candidates."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.observation_quality import observation_quality as quality
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)


def _row(subject, predicate, obj, quote, speaker="Joanna", **kw):
    return {"subject_text": subject, "predicate": predicate, "object_text": obj,
            "evidence_text": quote, "speaker": speaker, "polarity": "asserted", **kw}


JUNK = [
    _row("I", "has_attribute", "people", "I'm lucky to have people like you in my life"),
    _row("Your day", "plans", "enjoy", "Enjoy your day!"),
    _row("I", "has_attribute", "made", "I made this stained glass window"),
    _row("I", "did", "wedding", "It must have been special at your wedding."),
    _row("Melanie", "relates_to", "people", "Melanie, thanks for all the people you introduced"),
    _row("you", "did", "take them out again", "They must've been over the moon when you could take them out again."),
    _row("this", "has_attribute", "{'name': 'strawberries and chocolate'}", "this!"),
    _row("I", "relates_to", "Andrew", "Hey Andrew!"),
]
GOOD = [
    _row("I", "did", "volunteer at an LGBTQ+ youth center", "I volunteer at an LGBTQ+ youth center on weekends"),
    _row("I", "did", "take my kids to a park", "I took my kids to a park yesterday", time_text="yesterday"),
    _row("I", "plans", "build my own family", "I want to build my own family one day"),
    _row("I", "prefers", "turtles", "I've always liked turtles since I was a boy"),
    _row("Pepper", "prefers", "lounging on the couch", "Pepper loves lounging on the couch"),
]


@pytest.mark.parametrize("row", JUNK)
def test_junk_scores_below_the_default_floor(row):
    score, reasons = quality(row)
    assert score < 0.7 and reasons, (row, score)


@pytest.mark.parametrize("row", GOOD)
def test_good_scores_above_the_default_floor(row):
    score, reasons = quality(row)
    assert score >= 0.7, (row, score, reasons)


def test_reasons_name_the_rules_that_fired():
    assert "bad_subject" in quality(_row("your day", "plans", "enjoy it", "Enjoy your day!"))[1]
    assert "quote_about_listener" in quality(JUNK[3])[1]
    assert "greeting_quote" in quality(JUNK[1])[1]
    assert "no_content_object" in quality(JUNK[0])[1]
    assert "name_only_attribute" in quality(JUNK[6])[1]
    assert "plan_without_future" in quality(_row("I", "plans", "a pastry", "I ate a pastry yesterday afternoon"))[1]
    assert "fragment_object" in quality(_row("I", "is_a", "where I practice and compete", "This is where I practice and compete"))[1]


def test_score_is_bounded_and_tolerates_missing_fields():
    assert 0.0 <= quality({})[0] <= 1.0
    s, _ = quality(_row("you", "relates_to", "it", "Hi!"))
    assert 0.0 <= s <= 1.0


def test_config_defaults_and_env():
    o = _DEFAULT_CONFIG["observations"]
    assert o["quality_filter"] is False and o["quality_min"] == 0.7
    assert obs.observations_quality_filter_enabled({}) is False
    assert obs.observations_quality_min({}) == 0.7
    assert obs.observations_quality_min({"observations": {"quality_min": "x"}}) == 0.7
    out = apply_env_overrides({}, {"CAMPY_OBSERVATIONS_QUALITY_FILTER": "1"})
    assert out["observations"]["quality_filter"] is True


# --- the stage --------------------------------------------------------------------

T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)


def _vec(cos: float, axis: int) -> list[float]:
    v = [0.0] * DIM
    v[0], v[axis] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b486.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _add(db, gw, n, row, cos):
    mid = f"m{n}"
    text = f"Filler. {row['evidence_text']} More."
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at="2023-05-08T12:00:00+00:00")
    await gw.run("capture.set_message_source", message_id=mid, speaker=row["speaker"],
                 occurred_at="2023-05-08T12:00:00+00:00")
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text=row["evidence_text"], subject_text=row["subject_text"],
        predicate=row["predicate"], object_text=row["object_text"], extraction_method="llm",
        confidence=0.9, speaker=row["speaker"], text_raw=f"{row['subject_text']} - {row['predicate']} - {row['object_text']}",
        embedding=_vec(cos, 10 + n)))
    assert res.ok, res


async def _seed(db, gw):
    # junk is the most similar to the question, so it takes every slot unless filtered
    for i, r in enumerate(JUNK[:4]):
        await _add(db, gw, i, r, 0.9 - 0.01 * i)
    for i, r in enumerate(GOOD[:3]):
        await _add(db, gw, 10 + i, r, 0.5 - 0.01 * i)


def _lines(section):
    return [c["text"] for c in section.content]


async def test_flag_off_is_unchanged_and_keeps_junk(db, gw):
    await _seed(db, gw)
    base = {"observations": {"retrieval": True, "observation_limit": 4}}
    off = {"observations": {"retrieval": True, "observation_limit": 4, "quality_filter": False}}
    a = await bc._stage_observations(db, "what happened", base)
    b = await bc._stage_observations(db, "what happened", off)
    assert _lines(a) == _lines(b)
    assert len(a.content) == 4 and not any("volunteer" in t for t in _lines(a))


async def test_flag_on_drops_junk_and_backfills(db, gw):
    await _seed(db, gw)
    cfg = {"observations": {"retrieval": True, "observation_limit": 4, "quality_filter": True}}
    section = await bc._stage_observations(db, "what happened", cfg)
    text = " ".join(_lines(section))
    assert len(section.content) == 3                       # only the three good ones pass
    assert "volunteer" in text and "build my own family" in text and "park" in text
    assert "Enjoy your day" not in text and "wedding" not in text


async def test_flag_on_respects_the_limit(db, gw):
    await _seed(db, gw)
    cfg = {"observations": {"retrieval": True, "observation_limit": 2, "quality_filter": True}}
    section = await bc._stage_observations(db, "what happened", cfg)
    assert len(section.content) == 2 and not any("Enjoy" in t for t in _lines(section))


async def test_flag_on_all_junk_falls_back(db, gw):
    for i, r in enumerate(JUNK[:3]):
        await _add(db, gw, i, r, 0.9)
    cfg = {"observations": {"retrieval": True, "observation_limit": 4, "quality_filter": True}}
    assert await bc._stage_observations(db, "what happened", cfg) is None


async def test_quality_min_is_configurable(db, gw):
    await _seed(db, gw)
    cfg = {"observations": {"retrieval": True, "observation_limit": 8, "quality_filter": True, "quality_min": 0.0}}
    assert len((await bc._stage_observations(db, "what happened", cfg)).content) == 7
