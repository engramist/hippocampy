import pytest
from pathlib import Path
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import NODE_TABLES, REL_TABLES
from mcp_engine.tools.arc_mechanics import publish_mechanic_summary, recall_mechanic_priors

def _init_mechanic_schema(db: KuzuClient) -> None:
    tables = [
        "ArcMechanic", "ArcActionPattern", "ArcEffectPattern", 
        "ArcPrecondition", "ArcFailureMode", "ArcRecoveryPolicy"
    ]
    for table in tables:
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({NODE_TABLES[table]})")
    for ddl in REL_TABLES:
        if any(rel in ddl for rel in (
            "ARC_MECHANIC_HAS_ACTION_PATTERN",
            "ARC_MECHANIC_CAUSES_EFFECT_PATTERN",
            "ARC_MECHANIC_REQUIRES",
            "ARC_MECHANIC_FAILS_AS",
            "ARC_FAILURE_RECOVERED_BY"
        )):
            db.execute(ddl)

def _make_db(tmp_path: Path) -> KuzuClient:
    db = KuzuClient(str(tmp_path / "brain.db"))
    _init_mechanic_schema(db)
    return db

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
    count = db.execute("MATCH (m:ArcMechanic) RETURN count(m)").get_next()[0]
    assert count == 1
    
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
    
    count = db.execute("MATCH (m:ArcMechanic) RETURN count(m)").get_next()[0]
    assert count == 1
    
    evidence = db.execute("MATCH (m:ArcMechanic) RETURN m.evidence_count").get_next()[0]
    assert evidence == 2

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
