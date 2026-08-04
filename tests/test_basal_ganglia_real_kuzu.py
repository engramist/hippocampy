"""
tests/test_basal_ganglia_real_kuzu.py — Real-Kuzu regression tests for B277.

tests/test_basal_ganglia.py's `_make_sweep_db()` is a hand-rolled MockDB
whose execute_write just appends {"q": query, "p": params} to a list - it
never parses Cypher or validates against a schema, so a `!=` syntax error
or a reference to a nonexistent column can never surface there. All 26 of
its tests pass while three of these write paths were confirmed broken
against a real Kuzu database during the 2026-08-03 re-verification. These
tests run the real Cypher against a real Kuzu DB built with the full
production schema (init_schema), the only way to catch this class of bug.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
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
    db = KuzuClient(f"{tmp}/db")
    init_schema(db, _SEED_EXAMPLES_PATH, EMBEDDING_MODEL)
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _create_procedure(db, pid, application_count, success_rate, maturity_stage, pathway_strength=0.6):
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "CREATE (p:Procedure {procedure_id: $pid, name: $name, domain: 'test', "
        "archetype: 'automation', description: '', steps_json: '[]', "
        "embedding: $emb, embedding_model: $model, embedding_dim: 384, "
        "success_count: 0, application_count: $ac, success_rate: $sr, "
        "confidence: 0.8, pathway_strength: $ps, maturity_stage: $stage, "
        "archived: false, created_at: timestamp($now)})",
        {
            "pid": pid, "name": pid, "emb": [0.1] * 384, "model": EMBEDDING_MODEL,
            "ac": application_count, "sr": success_rate, "ps": pathway_strength,
            "stage": maturity_stage, "now": now,
        },
    )


def _get_procedure(db, pid):
    r = db.execute(
        "MATCH (p:Procedure {procedure_id: $pid}) "
        "RETURN p.maturity_stage, p.archived, p.pathway_strength, p.salience_score",
        {"pid": pid},
    )
    return r.get_next()


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
        db.execute(
            "CREATE (n:Concept {concept_id: $id, text_raw: $t, embedding: $e, "
            "embedding_model: $m, embedding_dim: 384, salience_score: $s, "
            "confidence: 0.8, pathway_strength: 0.6, archived: false, created_at: timestamp($now)})",
            {"id": cid, "t": text, "e": emb, "m": EMBEDDING_MODEL, "s": salience, "now": now},
        )

    def _decision(self, db, did, text, salience, emb):
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "CREATE (n:Decision {decision_id: $id, text_raw: $t, embedding: $e, "
            "embedding_model: $m, embedding_dim: 384, salience_score: $s, "
            "confidence: 0.8, pathway_strength: 0.6, archived: false, created_at: timestamp($now)})",
            {"id": did, "t": text, "e": emb, "m": EMBEDDING_MODEL, "s": salience, "now": now},
        )

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

        r = db.execute(
            "MATCH (p:Procedure {archetype: 'avoidance'}) "
            "RETURN p.procedure_id, p.salience_score ORDER BY p.created_at DESC LIMIT 1"
        )
        pid, salience = r.get_next()
        assert salience is not None
        assert salience == pytest.approx(1.55, abs=0.01)

        # DISTILLED_FROM edge to the Concept sources must exist.
        edges = db.execute(
            "MATCH (p:Procedure {procedure_id: $pid})-[:DISTILLED_FROM]->(c:Concept) "
            "RETURN c.concept_id",
            {"pid": pid},
        )
        linked = set()
        while edges.has_next():
            linked.add(edges.get_next()[0])
        assert linked == {"fc-c1", "fc-c2"}

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

        r = db.execute(
            "MATCH (p:Procedure {archetype: 'avoidance'})-[:DISTILLED_FROM]->(d:Decision) "
            "RETURN d.decision_id"
        )
        linked = set()
        while r.has_next():
            linked.add(r.get_next()[0])
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
        db.execute(
            "CREATE (p:Plan {plan_id: 'bg-plan-1', goal: 'test goal', strategy: 's', "
            "step_count: 1, valence: 0.0, status: 'completed', confidence: 0.8, "
            "confidence_low: false, pathway_strength: 0.6, archived: false, "
            "created_at: timestamp($now)})",
            {"now": now},
        )

        result = await record_reward_prediction_error(db, "bg-plan-1", predicted_valence=0.2, actual_valence=0.8)

        assert result["prediction_error"] == pytest.approx(0.6)
        assert result["direction"] == "positive"

        r = db.execute(
            "MATCH (p:Plan {plan_id: 'bg-plan-1'}) "
            "RETURN p.predicted_valence, p.actual_valence, p.prediction_error"
        )
        predicted, actual, error = r.get_next()
        assert predicted == pytest.approx(0.2)
        assert actual == pytest.approx(0.8)
        assert error == pytest.approx(0.6)
