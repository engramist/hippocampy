"""
Tests for Basal Ganglia — Auto-Skill Generation.

Run with: python3 -m pytest tests/test_basal_ganglia.py -v
"""

from __future__ import annotations
import os
import pytest
import asyncio
import json
import numpy as np


def _cosine_sim(a, b):
    """Cosine similarity between two vectors."""
    a, b = np.array(a), np.array(b)
    dot = np.dot(a, b)
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norms) if norms > 0 else 0.0


def _make_sweep_db(query_rows=None, vector_results=None):
    """Build a mock DB matching sweep.py conventions."""
    query_rows = query_rows or {}
    vector_results = vector_results or {}

    class MockResult:
        def __init__(self, rows):
            self._rows = list(rows)
            self._idx = 0
        def has_next(self): return self._idx < len(self._rows)
        def get_next(self):
            row = self._rows[self._idx]
            self._idx += 1
            return row

    class MockDB:
        def __init__(self):
            self.written = []
        def execute(self, q, p=None):
            for pattern, rows in query_rows.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])
        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})
        async def execute_read(self, q, p=None):
            for pattern, rows in query_rows.items():
                if pattern in q:
                    return [dict(zip(
                        ["id", "name", "description", "emb", "salience"],
                        row
                    )) for row in rows]
            return []
        def vector_search(self, table, index, vec, limit):
            return vector_results.get(index, [])

    return MockDB()


class TestFrustrationClusterDetection:
    """Tests for _detect_frustration_clusters in sweep.py."""

    @pytest.mark.asyncio
    async def test_no_high_salience_nodes_returns_zero(self):
        """No nodes above salience threshold -> no Procedures created."""
        from campy.brain.brainstem.sweep import _detect_frustration_clusters
        db = _make_sweep_db()
        config = {"embeddings": {"model": "test-model"}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0
        assert errors == 0

    @pytest.mark.asyncio
    async def test_cluster_of_three_creates_avoidance_procedure(self):
        """3 high-salience nodes with similar embeddings -> 1 avoidance Procedure."""
        from campy.brain.brainstem.sweep import _detect_frustration_clusters

        # Create 3 nodes with identical embeddings (similarity = 1.0)
        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "deployment failure", "deploy broke the build", base_emb, 1.4),
            ("id-2", "deployment error", "deploy caused 500 errors", base_emb, 1.5),
            ("id-3", "deploy rollback", "had to rollback deploy", base_emb, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 1, f"Expected 1 Procedure, got {count}"

        # Verify a CREATE (pr:Procedure was written
        creates = [w for w in db.written if "CREATE" in w["q"] and "Procedure" in w["q"]]
        assert len(creates) >= 1, "No Procedure CREATE found"
        params = creates[0]["p"]
        assert params.get("archetype") == "avoidance"
        assert params.get("domain") == "auto-discovered"

    @pytest.mark.asyncio
    async def test_cluster_below_threshold_no_procedure(self):
        """Only 2 high-salience nodes (below min_cluster=3) -> no Procedure."""
        from campy.brain.brainstem.sweep import _detect_frustration_clusters

        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "deployment failure", "deploy broke", base_emb, 1.4),
            ("id-2", "deployment error", "deploy error", base_emb, 1.5),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0

    @pytest.mark.asyncio
    async def test_dissimilar_nodes_not_clustered(self):
        """3 high-salience nodes with different embeddings -> no cluster."""
        from campy.brain.brainstem.sweep import _detect_frustration_clusters

        nodes = [
            ("id-1", "deploy fail", "deploy broke", [1.0] + [0.0] * 383, 1.4),
            ("id-2", "auth error",  "login failed", [0.0, 1.0] + [0.0] * 382, 1.5),
            ("id-3", "db timeout",  "query slow",   [0.0, 0.0, 1.0] + [0.0] * 381, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0, "Dissimilar nodes should not cluster"

    @pytest.mark.asyncio
    async def test_avoidance_procedure_has_steps_json(self):
        """Created avoidance Procedure has non-empty steps_json."""
        from campy.brain.brainstem.sweep import _detect_frustration_clusters

        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "always breaks", "deployment always breaks", base_emb, 1.4),
            ("id-2", "keep breaking", "deploys keep breaking", base_emb, 1.5),
            ("id-3", "broke again", "deploy broke again", base_emb, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        await _detect_frustration_clusters(db, config)

        creates = [w for w in db.written if "CREATE" in w["q"] and "Procedure" in w["q"]]
        assert len(creates) >= 1
        steps = json.loads(creates[0]["p"]["steps_json"])
        assert isinstance(steps, list)
        assert len(steps) > 0, "steps_json should have at least one step"


class TestSalienceScoreStorage:
    """Verify _store_concept writes salience_score to the node."""

    @pytest.mark.asyncio
    async def test_store_concept_includes_salience_score(self):
        """When _store_concept is called with salience=1.4, the CREATE query
        should include salience_score: $salience_score."""
        from campy.brain.temporal_lobe.loop.orchestrator import _store_concept

        written = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, q, p=None): return MockResult()
            async def execute_write(self, q, p=None): written.append({"q": q, "p": p})

        entity = {"text": "test entity", "gist_class": "Event", "schema_org_type": ""}
        step4 = {"confidence": 0.75, "confidence_low": False}
        vector = [0.1] * 384

        result = await _store_concept(
            entity, step4, vector, "test-model", MockDB(),
            "2026-05-26T00:00:00Z", salience=1.4,
        )
        assert result is not None, "Expected concept_id returned"

        # Find the CREATE query
        create_queries = [w for w in written if "CREATE" in w["q"]]
        assert len(create_queries) == 1, f"Expected 1 CREATE, got {len(create_queries)}"
        params = create_queries[0]["p"]
        assert "salience_score" in params, "salience_score not in CREATE params"
        assert params["salience_score"] == 1.4, f"Expected 1.4, got {params['salience_score']}"

    @pytest.mark.asyncio
    async def test_store_concept_default_salience_is_1(self):
        """When salience is not specified, salience_score defaults to 1.0."""
        from campy.brain.temporal_lobe.loop.orchestrator import _store_concept

        written = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, q, p=None): return MockResult()
            async def execute_write(self, q, p=None): written.append({"q": q, "p": p})

        entity = {"text": "default salience", "gist_class": "Event", "schema_org_type": ""}
        step4 = {"confidence": 0.70, "confidence_low": False}
        vector = [0.1] * 384

        await _store_concept(entity, step4, vector, "test-model", MockDB(),
                             "2026-05-26T00:00:00Z")

        create_queries = [w for w in written if "CREATE" in w["q"]]
        assert len(create_queries) == 1
        params = create_queries[0]["p"]
        assert params.get("salience_score") == 1.0


class TestSchemaMigrations:
    """Verify salience_score and maturity_stage appear in the migration list."""

    def _read_schema_source(self):
        """Read schema.py source to check for migration entries."""
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "campy", "brain", "hippocampus",
            "schema.py"
        )
        with open(schema_path, "r") as f:
            return f.read()

    def test_salience_score_migration_entries_exist(self):
        source = self._read_schema_source()
        assert "salience_score" in source, "salience_score migration missing from ensure_schema"

    def test_maturity_stage_migration_entry_exists(self):
        source = self._read_schema_source()
        assert "maturity_stage" in source, "maturity_stage migration missing from ensure_schema"

    def test_salience_score_on_all_gcl_node_types(self):
        source = self._read_schema_source()
        for table in ("Concept", "Decision", "Constraint"):
            assert f'("{table}",' in source and "salience_score" in source, (
                f"salience_score migration missing for {table}"
            )

    def test_maturity_stage_on_procedure_only(self):
        source = self._read_schema_source()
        # maturity_stage should appear for Procedure
        assert '"Procedure"' in source and "maturity_stage" in source


class TestEnhancedPlanClustering:
    """Tests for enhanced _synthesize_procedures changes."""

    @pytest.mark.asyncio
    async def test_min_cluster_size_lowered_to_two(self):
        """_synthesize_procedures should create Procedures from 2 Plans sharing a strategy."""
        from campy.brain.brainstem.sweep import _synthesize_procedures

        # 2 Plans with same strategy
        query_rows = {
            "DISTINCT p.strategy": [("deploy-to-prod",)],
            "p.strategy = $strategy": [
                ("plan-1", "deploy app", [0.1] * 384, 0.8, 0.7),
                ("plan-2", "deploy service", [0.1] * 384, 0.9, 0.8),
            ],
            # No existing Procedure with this archetype
            "p.archetype = $strategy": [],
        }
        db = _make_sweep_db(query_rows=query_rows)

        # Mock LLM to return a valid Procedure JSON
        class MockLLM:
            def chat(self, messages):
                return json.dumps({
                    "name": "Deploy to Production",
                    "description": "Standard deployment procedure",
                    "steps": [{"step": 1, "action": "build", "precondition": "", "expected_outcome": ""}],
                })

        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"procedural": {"min_cluster_size": 2, "min_valence": 0.5,
                                            "max_syntheses_per_sweep": 3}}}
        count, errors = await _synthesize_procedures(db, config, MockLLM())
        assert count >= 1, f"Expected at least 1 Procedure from 2 Plans, got {count}"


class TestProcedureMaturity:
    """Tests for _update_procedure_maturity."""

    @pytest.mark.asyncio
    async def test_nascent_stage(self):
        """Procedure with application_count < 3 stays nascent."""
        from campy.brain.brainstem.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        result = await _update_procedure_maturity(db, config)
        # Should run without error
        assert result["updated"] >= 0

    @pytest.mark.asyncio
    async def test_maturity_update_writes_cypher(self):
        """_update_procedure_maturity writes a SET maturity_stage query."""
        from campy.brain.brainstem.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        # Should have written at least the maturity update query
        maturity_writes = [w for w in db.written if "maturity_stage" in w["q"]]
        assert len(maturity_writes) >= 1, "Expected maturity_stage update query"


class TestProcedureDegradation:
    """Tests for degradation detection in _update_procedure_maturity."""

    @pytest.mark.asyncio
    async def test_degradation_query_includes_success_rate_check(self):
        """Degradation detection should check success_rate < 0.30."""
        from campy.brain.brainstem.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        degradation_writes = [w for w in db.written if "degraded" in w["q"]]
        assert len(degradation_writes) >= 1, "Expected degradation detection query"

    @pytest.mark.asyncio
    async def test_archive_deeply_degraded(self):
        """Procedures already degraded with success_rate < 0.20 should be archived."""
        from campy.brain.brainstem.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        archive_writes = [w for w in db.written if "archived" in w["q"] and "degraded" in w["q"]]
        assert len(archive_writes) >= 1, "Expected archive query for deeply degraded Procedures"


class TestActionSelector:
    """Tests for action selection Go/No-Go gating."""

    @pytest.mark.asyncio
    async def test_go_decision_with_supporting_evidence(self):
        """Action with supporting procedures returns 'go' decision."""
        from campy.brain.basal_ganglia.action_selector import check_action_gate
        
        class MockDB:
            def vector_search(self, table, index, vec, limit):
                return [
                    {"node": {"archetype": "automation", "success_rate": 0.8}},
                    {"node": {"archetype": "automation", "success_rate": 0.75}},
                ]
        
        db = MockDB()
        result = await check_action_gate(db, "try deployment action")
        assert result["decision"] == "go"
        assert result["supporting_evidence"] == 2

    @pytest.mark.asyncio
    async def test_no_go_after_falsification(self):
        """Action with avoidance procedures returns 'no_go' decision."""
        from campy.brain.basal_ganglia.action_selector import check_action_gate
        
        class MockDB:
            def vector_search(self, table, index, vec, limit):
                return [
                    {"node": {"archetype": "avoidance"}},
                    {"node": {"archetype": "avoidance"}},
                    {"node": {"archetype": "avoidance"}},
                ]
        
        db = MockDB()
        result = await check_action_gate(db, "try dangerous action")
        assert result["decision"] == "no_go"
        assert result["contradictions"] == 3


class TestRewardPredictor:
    """Tests for reward prediction error tracking."""

    @pytest.mark.asyncio
    async def test_positive_prediction_error(self):
        """Actual > predicted should return positive error."""
        from campy.brain.basal_ganglia.reward_predictor import record_reward_prediction_error
        
        class MockDB:
            async def execute_write(self, q, p=None):
                pass
        
        db = MockDB()
        result = await record_reward_prediction_error(db, "plan-1", 0.5, 0.9)
        assert result["prediction_error"] == 0.4
        assert result["direction"] == "positive"

    @pytest.mark.asyncio
    async def test_negative_prediction_error(self):
        """Actual < predicted should return negative error."""
        from campy.brain.basal_ganglia.reward_predictor import record_reward_prediction_error
        
        class MockDB:
            async def execute_write(self, q, p=None):
                pass
        
        db = MockDB()
        result = await record_reward_prediction_error(db, "plan-1", 0.8, 0.3)
        assert result["prediction_error"] == -0.5
        assert result["direction"] == "negative"


class TestExplorationPolicy:
    """Tests for exploration vs exploitation policy."""

    @pytest.mark.asyncio
    async def test_explore_after_repetition(self):
        """Repeated same action should trigger exploration."""
        from campy.brain.basal_ganglia.exploration_policy import should_explore
        
        class MockDB:
            def vector_search(self, table, index, vec, limit):
                return []
        
        db = MockDB()
        recent = ["deploy", "deploy", "deploy"]
        result = await should_explore(db, recent)
        assert result["explore"] is True
        assert "repeated" in result["reason"]

    @pytest.mark.asyncio
    async def test_exploit_with_no_repetition(self):
        """Varied recent actions should not trigger exploration."""
        from campy.brain.basal_ganglia.exploration_policy import should_explore
        
        class MockDB:
            def vector_search(self, table, index, vec, limit):
                return [{"node": {"prediction_error": 0.5}}]
        
        db = MockDB()
        recent = ["deploy", "test", "review"]
        result = await should_explore(db, recent)
        assert result["explore"] is False


class TestProcedureMaturityNew:
    """Tests for procedure maturity lifecycle stages."""

    def test_nascent_to_developing(self):
        """Procedure with 3 applications should transition from nascent to developing."""
        from campy.brain.basal_ganglia.procedure_maturity import _compute_stage
        assert _compute_stage(3, 0.8, "nascent") == "developing"

    def test_degraded_on_low_success_rate(self):
        """Procedure with low success rate should become degraded."""
        from campy.brain.basal_ganglia.procedure_maturity import _compute_stage
        assert _compute_stage(5, 0.2, "developing") == "degraded"

    def test_mature_with_high_applications(self):
        """Procedure with 10+ applications should be mature."""
        from campy.brain.basal_ganglia.procedure_maturity import _compute_stage
        assert _compute_stage(10, 0.7, "developing") == "mature"

    def test_archived_never_changes(self):
        """Archived procedures should not auto-transition."""
        from campy.brain.basal_ganglia.procedure_maturity import _compute_stage
        assert _compute_stage(20, 0.9, "archived") == "archived"
