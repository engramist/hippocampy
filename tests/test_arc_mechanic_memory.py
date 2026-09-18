import pytest
from pathlib import Path
from campy.brain.hippocampus.graph.oxigraph_client import CAMPY_NS, OxigraphClient
from campy.brain.thalamus.tools.arc_mechanics import publish_mechanic_summary, recall_mechanic_priors

def _make_db(tmp_path: Path) -> OxigraphClient:
    # B427: migrated off KuzuClient. The original Kuzu version had to
    # explicitly CREATE NODE/REL TABLE for the ArcMechanic subset before any
    # write -- OxigraphClient needs no such step: NODE_COLUMNS/REL_COLUMNS
    # are derived from schema.py globally, not from a per-database catalog.
    return OxigraphClient(str(tmp_path / "brain.db"))

def _count_arc_mechanics(db: OxigraphClient) -> int:
    rows = list(db.store.query(
        f'PREFIX campy: <{CAMPY_NS}> SELECT (COUNT(*) AS ?n) WHERE {{ ?m a campy:ArcMechanic . }}'
    ))
    return int(rows[0]["n"].value)

@pytest.mark.asyncio
async def test_publish_mechanic_and_recall(tmp_path):
    db = _make_db(tmp_path)

    summary = {
        "name": "Gravity Drop",
        "task_id": "arc_eval_001",
        "action_set_signature": "ACTION6",
        "confidence": 0.9,
        "hypotheses": [
            {"signature": "h1", "action_count": 1, "confidence": 0.8}
        ],
        "effects": [
            {"signature": "e1", "effect_class": "motion", "terminal_trend": "down", "confidence": 0.85}
        ],
        "failure_modes": [
            {"name": "blocked", "recovery_policies": [{"name": "slide", "confidence": 0.7}]}
        ]
    }

    # 1. Publish
    res = await publish_mechanic_summary({"summary": summary}, db, {})
    assert res["ok"] is True
    mech_id = res["mechanic_id"]

    # Verify graph
    assert _count_arc_mechanics(db) == 1

    # 2. Recall
    recall_res = await recall_mechanic_priors({
        "signature": {"action_set": "ACTION6"},
        "min_confidence": 0.5
    }, db, {})

    assert len(recall_res["results"]) == 1
    mech = recall_res["results"][0]
    assert mech["name"] == "Gravity Drop"
    assert len(mech["action_patterns"]) == 1
    assert len(mech["effect_patterns"]) == 1
    assert len(mech["failure_modes"]) == 1
    assert len(mech["failure_modes"][0]["recovery_policies"]) == 1
    assert mech["failure_modes"][0]["recovery_policies"][0]["name"] == "slide"

@pytest.mark.asyncio
async def test_publish_idempotency(tmp_path):
    db = _make_db(tmp_path)
    summary = {"name": "Test", "task_id": "t1"}

    await publish_mechanic_summary({"summary": summary}, db, {})
    await publish_mechanic_summary({"summary": summary}, db, {})

    assert _count_arc_mechanics(db) == 1

    rows = list(db.store.query(
        f'PREFIX campy: <{CAMPY_NS}> SELECT ?ec WHERE {{ ?m a campy:ArcMechanic ; campy:evidence_count ?ec . }}'
    ))
    assert int(rows[0]["ec"].value) == 2

@pytest.mark.asyncio
async def test_recall_empty_db(tmp_path):
    db = _make_db(tmp_path)
    res = await recall_mechanic_priors({"signature": {"action_set": "ACTION6"}}, db, {})
    assert res["results"] == []

@pytest.mark.asyncio
async def test_recall_filters_by_confidence(tmp_path):
    db = _make_db(tmp_path)
    await publish_mechanic_summary({"summary": {"name": "Low", "confidence": 0.2}}, db, {})
    await publish_mechanic_summary({"summary": {"name": "High", "confidence": 0.8}}, db, {})

    res = await recall_mechanic_priors({"min_confidence": 0.5}, db, {})
    assert len(res["results"]) == 1
    assert res["results"][0]["name"] == "High"
