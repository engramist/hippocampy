"""B460 item 1 — the calibrated Step 4 gate model: features, prediction,
the Step 4 hook (opt-in via [save_gate] model_path), and training."""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph import embeddings as emb_mod
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.temporal_lobe import save_gate_model as sgm
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step2_gist import GIST_CLASSES
from campy.brain.temporal_lobe.loop.step4_pattern import (
    ASSISTANT_CAP, HARD_LOCK, NOISE_FLOOR, classify_artifact,
)
from campy.brain.temporal_lobe.save_gate_model import FeatureSpec, GateModel, featurize

SMALL = FeatureSpec(ngram_dims=16, signals=True)
EMB = [0.0] * 383 + [1.0]


def biased(label: str, strength: float = 10.0, spec: FeatureSpec = SMALL, temperature=1.0) -> GateModel:
    """A model that ignores its input and favours one label."""
    bias = [strength if lab == label else 0.0 for lab in sgm.LABELS]
    return GateModel(spec, [[0.0] * spec.size for _ in sgm.LABELS], bias, temperature)


# --- features and prediction ----------------------------------------------------

def test_gist_classes_match_step2():
    assert list(sgm.GIST_FEATURE_CLASSES) == GIST_CLASSES


def test_featurize_is_deterministic_and_sized():
    spec = FeatureSpec(ngram_dims=64, signals=True, gist=True, embedding=True)
    x = featurize("We decided to use Postgres.", spec, "Category", EMB)
    assert x == featurize("We decided to use Postgres.", spec, "Category", EMB)
    assert max(x) < spec.size
    # the decision keyword signal is set; the gist one-hot points at Category
    sig = spec.ngram_dims
    assert x[sig] > 0 and x[sig + 1] == 1.0
    gist_off = sig + 8
    assert x[gist_off + sgm.GIST_FEATURE_CLASSES.index("Category")] == 1.0
    with pytest.raises(ValueError):
        featurize("x", spec, "Category", None)   # embedding required by this spec


def test_predict_proba_and_temperature():
    m = biased("decision", strength=2.0)
    p = m.predict_proba("anything")
    assert sum(p.values()) == pytest.approx(1.0)
    assert p["decision"] == pytest.approx(math.exp(2) / (math.exp(2) + 4))
    hot = biased("decision", strength=2.0, temperature=2.0).predict_proba("anything")
    assert hot["decision"] < p["decision"]      # higher temperature, less confident


def test_round_trip_and_validation(tmp_path):
    m = biased("constraint")
    m.metadata = {"trained_on": "test"}
    path = tmp_path / "m.json"
    m.save(path)
    back = GateModel.load(path)
    assert back.predict_proba("x") == m.predict_proba("x") and back.metadata == m.metadata
    with pytest.raises(ValueError):
        GateModel(SMALL, [[0.0] * 3 for _ in sgm.LABELS], [0.0] * 5)   # wrong width


def test_load_gate_model(tmp_path):
    assert sgm.load_gate_model({}) is None
    assert sgm.load_gate_model({"save_gate": {"model_path": str(tmp_path / "missing.json")}}) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert sgm.load_gate_model({"save_gate": {"model_path": str(bad)}}) is None
    good = tmp_path / "good.json"
    biased("decision").save(good)
    cfg = {"save_gate": {"model_path": str(good)}}
    assert sgm.load_gate_model(cfg) is sgm.load_gate_model(cfg)   # cached per path+mtime


# --- the Step 4 hook --------------------------------------------------------------

TEXT = "We could maybe look at the job queue later."   # no keyword signal


def test_no_model_is_unchanged():
    assert classify_artifact(TEXT, "PhysicalThing", "Product", "job queue") == \
        classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", gate_model=None)


def test_model_probability_drives_the_gate():
    r = classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", gate_model=biased("decision"))
    assert r["artifact_type"] == "decision" and r["confidence"] > HARD_LOCK
    assert r["should_proceed"] and not r["confidence_low"] and "probs" in r

    # the model says "none": the best artifact class is improbable -> below the floor
    r = classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", gate_model=biased("none"))
    assert r["confidence"] < NOISE_FLOOR and not r["should_proceed"]

    # keywords no longer set the score: a keyword-heavy sentence the model doubts stays low
    r = classify_artifact("We decided and finalized it: we chose Redis.", "Category", "Thing",
                          "Redis", gate_model=biased("none"))
    assert not r["should_proceed"]


def test_rules_after_scoring_still_apply():
    model = biased("decision")
    assert classify_artifact(TEXT, None, None, "job queue", gate_model=model)["artifact_type"] == "noise"
    single = classify_artifact(TEXT, "PhysicalThing", "Product", "queue", gate_model=model)
    assert single["confidence"] <= 0.60                       # B300 single-token cap
    asst = classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", role="assistant",
                             gate_model=model)
    assert asst["confidence"] <= ASSISTANT_CAP and asst["confidence_low"]


def test_failing_model_falls_back_to_keywords():
    needs_emb = biased("decision", spec=FeatureSpec(ngram_dims=16, embedding=True))
    r = classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", gate_model=needs_emb)
    assert "probs" not in r
    assert r == classify_artifact(TEXT, "PhysicalThing", "Product", "job queue")


def test_near_tie_is_logged(caplog):
    m = GateModel(SMALL, [[0.0] * SMALL.size for _ in sgm.LABELS], [1.0, 0.95, 0.0, 0.0, 0.0])
    with caplog.at_level("INFO"):
        classify_artifact(TEXT, "PhysicalThing", "Product", "job queue", gate_model=m)
    assert any("Gate:NearTie" in r.message and "step4" in r.message for r in caplog.records)


# --- end to end through run_loop (opt-in via config) ------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(emb_mod, "embed", lambda text, model_name=None, **kw: EMB)
    monkeypatch.setattr(emb_mod, "embed_batch",
                        lambda texts, model_name=None, **kw: [EMB for _ in texts])
    return OxigraphClient(tmp_path / "b460g.db")


ENTITY = {"text": "job queue", "gist_class": "PhysicalThing", "schema_org_type": "Product",
          "label": "PRODUCT"}


async def _run(db, config):
    return await orch.run_loop("m1", TEXT, db, None, config, {}, role="user",
                               precomputed={"entities": [ENTITY], "relations": []})


@pytest.mark.asyncio
async def test_run_loop_uses_configured_model(db, tmp_path):
    assert (await _run(db, {}))["reified"] == 0          # keyword path: gist prior 0.55, dropped
    path = tmp_path / "gate.json"
    biased("decision").save(path)
    summary = await _run(db, {"save_gate": {"model_path": str(path)}})
    assert summary["reified"] == 1 and summary["noise_count"] == 0


@pytest.mark.asyncio
async def test_run_loop_embeds_the_sentence_for_embedding_models(db, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(emb_mod, "embed", lambda text, model_name=None, **kw: seen.append(text) or EMB)
    path = tmp_path / "gate.json"
    biased("decision", spec=FeatureSpec(ngram_dims=16, embedding=True)).save(path)
    summary = await _run(db, {"save_gate": {"model_path": str(path)}})
    assert TEXT in seen and summary["reified"] == 1


# --- training ----------------------------------------------------------------------

def test_training_on_the_labeled_set(tmp_path):
    np = pytest.importorskip("numpy")
    from benchmarks.save_gate import train_gate as tg

    items = tg.load_gold()[::2]   # half the set keeps the test quick
    metrics, model = tg.run(items, FeatureSpec(ngram_dims=128, signals=True), folds=3)
    assert metrics["rows"] == len(items) and len(metrics["temperatures"]) == 3
    assert 0.0 <= metrics["calibration"]["ece"] <= 1.0
    assert {"reified_accuracy", "false_save_rate", "reliability"} <= set(metrics["gate"])
    assert model.temperature > 0 and model.metadata["items"] == len(items)
    # the saved model is usable by the Loop
    path = tmp_path / "m.json"
    model.save(path)
    p = GateModel.load(path).predict_proba("We decided to use Postgres.")
    assert sum(p.values()) == pytest.approx(1.0)


def test_temperature_fit_recovers_scale():
    np = pytest.importorskip("numpy")
    from benchmarks.save_gate import train_gate as tg

    rng = np.random.default_rng(0)
    true = rng.normal(size=(2000, 5)) * 2
    y = np.array([rng.choice(5, p=np.exp(z) / np.exp(z).sum()) for z in true])
    # logits 3x too sharp: the fitted temperature should undo that
    assert tg.fit_temperature(true * 3, y) == pytest.approx(3.0, rel=0.15)
