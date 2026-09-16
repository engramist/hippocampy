"""
tests/test_basal_ganglia_real_kuzu.py — Real-database regression tests for B277.

tests/test_basal_ganglia.py's `_make_sweep_db()` is a hand-rolled MockDB
whose execute_write just appends {"q": query, "p": params} to a list - it
never parses Cypher or validates against a schema, so a `!=` syntax error
or a reference to a nonexistent column can never surface there. All 26 of
its tests pass while three of these write paths were confirmed broken
against a real Kuzu database during the 2026-08-03 re-verification. These
tests run against a real OxigraphClient built with the full production
schema (init_schema) — B427: migrated off KuzuClient. sweep.py,
frustration_clusters.py, and reward_predictor.py are all fully
GraphGateway-routed (no raw Cypher bypass), so this now validates the
same named-query write paths against the shipped engine, the only way to
catch drift on that path (cf. B430/B431, found via this exact kind of
swap).
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import CAMPY_NS, OxigraphClient
from campy.brain.hippocampus.schema import init_schema

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_SEED_EXAMPLES_PATH = "campy/data/GistSeedExamples.md"


@pytest.fixture(scope="module")
def real_db():
    """Full production schema - needed because these bugs are all about
    real column/rel-table definitions, not just Cypher syntax in isolation.
    Module-scoped since init_schema() is expensive; tests use disjoint ids.
    """
    tmp = tempfile.mkdtemp(prefix="basal_ganglia_real_")
    db = OxigraphClient(f"{tmp}/db")
    init_schema(db, _SEED_EXAMPLES_PATH, EMBEDDING_MODEL)
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _create_procedure(db, pid, application_count, success_rate, maturity_stage, pathway_strength=0.6):
    now = datetime.now(timezone.utc).isoformat()
    db.write_node("Procedure", {
        "procedure_id": pid, "name": pid, "domain": "test",
        "archetype": "automation", "description": "", "steps_json": "[]",
        "embedding": [0.1] * 384, "embedding_model": EMBEDDING_MODEL, "embedding_dim": 384,
        "success_count": 0, "application_count": application_count, "success_rate": success_rate,
        "confidence": 0.8, "pathway_strength": pathway_strength, "maturity_stage": maturity_stage,
        "archived": False, "created_at": now,
    })


def _get_procedure(db, pid):
    rows = list(db.store.query(
        f'PREFIX campy: <{CAMPY_NS}> '
        f'SELECT ?maturity_stage ?archived ?pathway_strength ?salience_score WHERE {{ '
        f'  ?p campy:procedure_id "{pid}" . '
        f'  OPTIONAL {{ ?p campy:maturity_stage ?maturity_stage }} '
        f'  OPTIONAL {{ ?p campy:archived ?archived }} '
        f'  OPTIONAL {{ ?p campy:pathway_strength ?pathway_strength }} '
        f'  OPTIONAL {{ ?p campy:salience_score ?salience_score }} '
        f'}}'
    ))
    row = rows[0]
    stage = row["maturity_stage"].value if row["maturity_stage"] else None
    archived = row["archived"].value == "true" if row["archived"] else None
    pathway_strength = float(row["pathway_strength"].value) if row["pathway_strength"] else None
    salience = float(row["salience_score"].value) if row["salience_score"] else None
    return stage, archived, pathway_strength, salience


class TestProcedureMaturityRealKuzu:
    """B277 bug 1: sweep.py's _update_procedure_maturity used `!=`, which
    Kuzu's Cypher dialect does not support - every real invocation raised
    a Parser exception on both the promote and degrade queries, silently
    swallowed with no logging at all. The entire maturity lifecycle never
    worked against a real database."""

    async def test_promotes_to_mature_without_errors(self, real_db):
        from campy.brain.brainstem.sweep import _update_procedure_maturity

        db = real_db
        _create_procedure(db, "bg-mature-1", application_count=5, success_rate=0.9, maturity_stage="nascent")

        result = await _update_procedure_maturity(db, {})

        assert result["errors"] == 0, f"expected no errors, got {result}"
        stage, archived, _, _ = _get_procedure(db, "bg-mature-1")
        assert stage == "mature"

    async def test_degrades_low_success_procedure(self, real_db):
        from campy.brain.brainstem.sweep import _update_procedure_maturity

        db = real_db
        _create_procedure(db, "bg-degrade-1", application_count=5, success_rate=0.1,
                          maturity_stage="developing", pathway_strength=0.8)

        result = await _update_procedure_maturity(db, {})

        assert result["errors"] == 0
        stage, archived, pathway_strength, _ = _get_procedure(db, "bg-degrade-1")
        assert stage == "degraded"
        assert pathway_strength == pytest.approx(0.4)  # halved from 0.8

    async def test_archives_deeply_degraded_procedure(self, real_db):
        from campy.brain.brainstem.sweep import _update_procedure_maturity

        db = real_db
        _create_procedure(db, "bg-archive-1", application_count=5, success_rate=0.1, maturity_stage="degraded")

        result = await _update_procedure_maturity(db, {})

        assert result["errors"] == 0
        stage, archived, _, _ = _get_procedure(db, "bg-archive-1")
        assert archived is True


class TestFrustrationClustersRealKuzu:
    """B277 bug 2 (+ an additional bug found while verifying it): the
    Procedure CREATE set salience_score, a property that didn't exist on
    Procedure at all - every avoidance-Procedure synthesis failed. Fixing
    only that then exposes a second, real bug: DISTILLED_FROM was only
    ever declared FROM Procedure TO Plan, but frustration_clusters.py
    tries to link Procedure -> Concept/Decision/Constraint, and the edge
    creation hardcoded the :Concept label regardless of which table the
    clustered node actually came from."""

    def _concept(self, db, cid, text, salience, emb):
        now = datetime.now(timezone.utc).isoformat()
        db.write_node("Concept", {
            "concept_id": cid, "text_raw": text, "embedding": emb,
            "embedding_model": EMBEDDING_MODEL, "embedding_dim": 384, "salience_score": salience,
            "confidence": 0.8, "pathway_strength": 0.6, "archived": False, "created_at": now,
        })

    def _decision(self, db, did, text, salience, emb):
        now = datetime.now(timezone.utc).isoformat()
        db.write_node("Decision", {
            "decision_id": did, "text_raw": text, "embedding": emb,
            "embedding_model": EMBEDDING_MODEL, "embedding_dim": 384, "salience_score": salience,
            "confidence": 0.8, "pathway_strength": 0.6, "archived": False, "created_at": now,
        })

    async def test_high_salience_node_query_does_not_error(self, real_db, monkeypatch):
        """B277 (found while verifying bug 2, not itself in the original
        audit): the initial high-salience-node query aliased a column to
        `desc`, a reserved keyword in Kuzu's Cypher dialect (collides with
        ORDER BY ... DESC) - it errored on every single call, meaning this
        was never even reaching the CREATE step in production."""
        from campy.brain.basal_ganglia.frustration_clusters import detect_frustration_clusters

        db = real_db
        # One-hot direction, orthogonal to the other tests' embeddings in
        # this module-scoped DB - cosine similarity across tests must stay
        # near 0 so nodes from different tests never accidentally cluster
        # together (they'd otherwise all be parallel "uniform positive
        # vector" directions with cosine similarity 1.0 regardless of
        # magnitude).
        desc_check_emb = [1.0] + [0.0] * 383
        monkeypatch.setattr(
            "campy.brain.hippocampus.graph.embeddings.embed",
            lambda text, model_name=None: desc_check_emb,
        )
        self._concept(db, "fc-desc-check", "isolated node, no cluster partner", 1.5, desc_check_emb)

        # min_cluster_size defaults to 3, so this lone node won't form a
        # cluster - the point of this test is that the query itself
        # doesn't raise, not that a Procedure gets created.
        count, errors = await detect_frustration_clusters(db, {})

        assert errors == 0, f"expected the query to succeed even with 0 clusters formed, got {errors} errors"

    @pytest.mark.xfail(
        reason="B433: basal_ganglia.frustration_get_concept's sparql= can never bind ?emb "
               "(embeddings live in vector_store, not RDF triples) — detect_frustration_clusters "
               "always finds 0 clusters against OxigraphClient until B433 is fixed.",
        strict=True,
    )
    async def test_creates_procedure_with_salience_score_from_concept_cluster(self, real_db, monkeypatch):
        from campy.brain.basal_ganglia.frustration_clusters import detect_frustration_clusters

        db = real_db
        emb = [0.0, 1.0] + [0.0] * 382  # orthogonal direction, see comment above
        monkeypatch.setattr(
            "campy.brain.hippocampus.graph.embeddings.embed",
            lambda text, model_name=None: emb,
        )
        self._concept(db, "fc-c1", "repeated failure one", 1.5, emb)
        self._concept(db, "fc-c2", "repeated failure two", 1.6, emb)

        count, errors = await detect_frustration_clusters(
            db, {"sweep": {"basal_ganglia": {"min_cluster_size": 2}}}
        )

        assert errors == 0, f"expected no errors, got {errors}"
        assert count == 1

        rows = list(db.store.query(
            f'PREFIX campy: <{CAMPY_NS}> '
            f'SELECT ?procedure_id ?salience_score WHERE {{ '
            f'  ?p a campy:Procedure ; campy:archetype "avoidance" ; '
            f'     campy:procedure_id ?procedure_id ; campy:created_at ?created_at . '
            f'  OPTIONAL {{ ?p campy:salience_score ?salience_score }} '
            f'}} ORDER BY DESC(?created_at) LIMIT 1'
        ))
        pid = rows[0]["procedure_id"].value
        salience = float(rows[0]["salience_score"].value) if rows[0]["salience_score"] else None
        assert salience is not None
        assert salience == pytest.approx(1.55, abs=0.01)

        # DISTILLED_FROM edge to the Concept sources must exist.
        edges = list(db.store.query(
            f'PREFIX campy: <{CAMPY_NS}> '
            f'SELECT ?concept_id WHERE {{ '
            f'  ?p campy:procedure_id "{pid}" ; campy:DISTILLED_FROM ?c . '
            f'  ?c a campy:Concept ; campy:concept_id ?concept_id . '
            f'}}'
        ))
        linked = {row["concept_id"].value for row in edges}
        assert linked == {"fc-c1", "fc-c2"}

    @pytest.mark.xfail(
        reason="B433: basal_ganglia.frustration_get_decision's sparql= can never bind ?emb "
               "(embeddings live in vector_store, not RDF triples) — detect_frustration_clusters "
               "always finds 0 clusters against OxigraphClient until B433 is fixed.",
        strict=True,
    )
    async def test_creates_distilled_from_edge_to_decision_source(self, real_db, monkeypatch):
        """Regression guard for the hardcoded-:Concept-label bug: a cluster
        built entirely from Decision nodes must still get a working
        DISTILLED_FROM edge to its real source table, not silently fail."""
        from campy.brain.basal_ganglia.frustration_clusters import detect_frustration_clusters

        db = real_db
        emb = [0.0, 0.0, 1.0] + [0.0] * 381  # orthogonal direction, see comment above
        monkeypatch.setattr(
            "campy.brain.hippocampus.graph.embeddings.embed",
            lambda text, model_name=None: emb,
        )
        self._decision(db, "fc-d1", "recurring bad decision one", 1.5, emb)
        self._decision(db, "fc-d2", "recurring bad decision two", 1.6, emb)

        count, errors = await detect_frustration_clusters(
            db, {"sweep": {"basal_ganglia": {"min_cluster_size": 2}}}
        )

        # Note: this is a module-scoped DB shared across tests in this
        # class, and detect_frustration_clusters rescans all source tables
        # (including earlier tests' still-present Concept nodes) on every
        # call, so `count` may exceed 1 - assert on this test's own
        # decision-source edges specifically, not the total cluster count.
        assert errors == 0
        assert count >= 1

        rows = list(db.store.query(
            f'PREFIX campy: <{CAMPY_NS}> '
            f'SELECT ?decision_id WHERE {{ '
            f'  ?p a campy:Procedure ; campy:archetype "avoidance" ; campy:DISTILLED_FROM ?d . '
            f'  ?d a campy:Decision ; campy:decision_id ?decision_id . '
            f'}}'
        ))
        linked = {row["decision_id"].value for row in rows}
        assert linked == {"fc-d1", "fc-d2"}


class TestRewardPredictorRealKuzu:
    """B277 bug 3: predicted_valence/actual_valence/prediction_error were
    never added to the Plan schema at all, despite being written on every
    call. The write silently failed (caught, logged, but never persisted),
    so exploration_policy.py's read of plan.prediction_error could never
    fire in production. This function is live-reachable from
    campy/brain/thalamus/tools/arc_queries.py, not dead code."""

    async def test_persists_rpe_fields_on_real_plan_node(self, real_db):
        from campy.brain.basal_ganglia.reward_predictor import record_reward_prediction_error

        db = real_db
        now = datetime.now(timezone.utc).isoformat()
        db.write_node("Plan", {
            "plan_id": "bg-plan-1", "goal": "test goal", "strategy": "s",
            "step_count": 1, "valence": 0.0, "status": "completed", "confidence": 0.8,
            "confidence_low": False, "pathway_strength": 0.6, "archived": False,
            "created_at": now,
        })

        result = await record_reward_prediction_error(db, "bg-plan-1", predicted_valence=0.2, actual_valence=0.8)

        assert result["prediction_error"] == pytest.approx(0.6)
        assert result["direction"] == "positive"

        rows = list(db.store.query(
            f'PREFIX campy: <{CAMPY_NS}> '
            f'SELECT ?predicted_valence ?actual_valence ?prediction_error WHERE {{ '
            f'  ?p campy:plan_id "bg-plan-1" ; '
            f'     campy:predicted_valence ?predicted_valence ; '
            f'     campy:actual_valence ?actual_valence ; '
            f'     campy:prediction_error ?prediction_error . '
            f'}}'
        ))
        predicted = float(rows[0]["predicted_valence"].value)
        actual = float(rows[0]["actual_valence"].value)
        error = float(rows[0]["prediction_error"].value)
        assert predicted == pytest.approx(0.2)
        assert actual == pytest.approx(0.8)
        assert error == pytest.approx(0.6)
