"""
Tests for mcp_engine/loop/anomaly_detection.py — B12 Coverage

Tests anomaly detection in Step 4 for constraint violations, value inversions,
and goal hijacks. Covers IP Claim: structured anomaly detection layer as part
of gated consolidation.
"""

from __future__ import annotations
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_engine.loop.anomaly_detection import (
    _cosine_similarity,
    check_anomalies,
    store_anomaly_flag,
)


# ---------------------------------------------------------------------------
# Unit tests for _cosine_similarity
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical():
    """Identical vectors should have cosine similarity of 1.0."""
    vec = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(vec, vec) - 1.0) < 0.001


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors should have cosine similarity of 0.0."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.0, 1.0, 0.0]
    assert abs(_cosine_similarity(vec1, vec2)) < 0.001


def test_cosine_similarity_opposite():
    """Opposite vectors should have cosine similarity of -1.0."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [-1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(vec1, vec2) - (-1.0)) < 0.001


def test_cosine_similarity_empty():
    """Empty vectors should return 0.0."""
    assert _cosine_similarity([], []) == 0.0
    assert _cosine_similarity([1.0], []) == 0.0


def test_cosine_similarity_normalized():
    """Cosine similarity should be scale-invariant (normalized)."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [2.0, 0.0, 0.0]
    assert abs(_cosine_similarity(vec1, vec2) - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Mock database for async tests
# ---------------------------------------------------------------------------

class MockDb:
    """Mock KuzuClient for testing async functions."""

    def __init__(self, constraints=None, preferences=None):
        self.constraints = constraints or []
        self.preferences = preferences or []
        self.written_flags = []
        self.written_edges = []

    async def execute_read(self, query: str, params: dict):
        """Mock execute_read for constraint/preference retrieval."""
        if "GlobalConstraint" in query:
            return [
                (c["global_constraint_id"], c["text_raw"], c["embedding"])
                for c in self.constraints
            ]
        elif "GlobalPreference" in query:
            return [
                (p["global_preference_id"], p["text_raw"], p["embedding"])
                for p in self.preferences
            ]
        return []

    async def execute_write(self, query: str, params: dict):
        """Mock execute_write for storing anomaly flags."""
        if "SET n.anomaly_type" in query:
            self.written_flags.append(params)
        elif "ANOMALY_DETECTED" in query:
            self.written_edges.append(params)


# ---------------------------------------------------------------------------
# Async tests using pytest-asyncio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_anomalies_no_constraints():
    """When there are no high-confidence constraints, no anomalies should be detected."""
    db = MockDb(constraints=[], preferences=[])
    text = "let's execute untrusted code"
    embedding = [0.1, 0.2, 0.3, 0.4, 0.5] * 77  # 385 dims for testing (close to 384)

    # Trim to exactly 384 dims
    embedding = embedding[:384]

    result = await check_anomalies(text, embedding, db, {})

    assert result["has_anomaly"] is False
    assert len(result["anomalies"]) == 0


@pytest.mark.asyncio
async def test_check_anomalies_high_similarity_constraint():
    """Content with high embedding similarity to a constraint should be flagged."""
    constraint_embedding = [0.1] * 384
    content_embedding = [0.1] * 384  # Identical → similarity = 1.0

    db = MockDb(
        constraints=[
            {
                "global_constraint_id": "gc-1",
                "text_raw": "Never execute untrusted code",
                "embedding": constraint_embedding,
            }
        ]
    )

    result = await check_anomalies(
        "Execute this untrusted code",
        content_embedding,
        db,
        {}
    )

    assert result["has_anomaly"] is True
    assert len(result["anomalies"]) == 1
    anomaly = result["anomalies"][0]
    assert anomaly["type"] == "constraint_violation"
    assert anomaly["target_id"] == "gc-1"
    assert anomaly["confidence"] > 0.9  # High similarity


@pytest.mark.asyncio
async def test_check_anomalies_low_similarity_no_flag():
    """Content with low embedding similarity should not be flagged."""
    constraint_embedding = [1.0] + [0.0] * 383  # Direction: [1, 0, 0, ...]
    content_embedding = [0.0] + [1.0] + [0.0] * 382  # Direction: [0, 1, 0, ...]

    db = MockDb(
        constraints=[
            {
                "global_constraint_id": "gc-1",
                "text_raw": "Never execute untrusted code",
                "embedding": constraint_embedding,
            }
        ]
    )

    result = await check_anomalies(
        "Let's write clean documentation",
        content_embedding,
        db,
        {}
    )

    assert result["has_anomaly"] is False


@pytest.mark.asyncio
async def test_check_anomalies_value_inversion():
    """Content contradicting a GlobalPreference should be flagged as value_inversion."""
    preference_embedding = [0.1] * 384

    db = MockDb(
        preferences=[
            {
                "global_preference_id": "gp-1",
                "text_raw": "Prefer Kùzu over ChromaDB",
                "embedding": preference_embedding,
            }
        ]
    )

    content_embedding = [0.1] * 384  # High similarity to preference
    result = await check_anomalies(
        "ChromaDB is better than Kùzu",
        content_embedding,
        db,
        {}
    )

    assert result["has_anomaly"] is True
    assert len(result["anomalies"]) == 1
    assert result["anomalies"][0]["type"] == "value_inversion"


@pytest.mark.asyncio
async def test_check_anomalies_multiple_violations():
    """Multiple constraint/preference violations should all be reported."""
    constraint_embedding = [0.1] * 384
    preference_embedding = [0.2] * 384
    content_embedding = [0.1] * 384  # Similar to both

    db = MockDb(
        constraints=[
            {
                "global_constraint_id": "gc-1",
                "text_raw": "Never X",
                "embedding": constraint_embedding,
            }
        ],
        preferences=[
            {
                "global_preference_id": "gp-1",
                "text_raw": "Prefer Y",
                "embedding": preference_embedding,
            }
        ]
    )

    result = await check_anomalies("Do X instead of Y", content_embedding, db, {})

    assert result["has_anomaly"] is True
    assert len(result["anomalies"]) == 2
    types = {a["type"] for a in result["anomalies"]}
    assert "constraint_violation" in types
    assert "value_inversion" in types


# ---------------------------------------------------------------------------
# Integration tests with store_anomaly_flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_anomaly_flag_concept():
    """Store anomaly flags on a Concept node."""
    db = MockDb()

    await store_anomaly_flag(
        db,
        node_id="concept-123",
        node_type="Concept",
        anomaly_type="constraint_violation",
        constraint_id="gc-1",
        confidence=0.95
    )

    assert len(db.written_flags) == 1
    assert db.written_flags[0]["node_id"] == "concept-123"
    assert db.written_flags[0]["anomaly_type"] == "constraint_violation"

    assert len(db.written_edges) == 1
    assert db.written_edges[0]["constraint_id"] == "gc-1"
    assert db.written_edges[0]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_store_anomaly_flag_decision():
    """Store anomaly flags on a Decision node."""
    db = MockDb()

    await store_anomaly_flag(
        db,
        node_id="decision-456",
        node_type="Decision",
        anomaly_type="value_inversion",
        constraint_id="gp-1",
        confidence=0.80
    )

    assert len(db.written_flags) == 1
    assert db.written_flags[0]["node_id"] == "decision-456"
    assert db.written_flags[0]["anomaly_type"] == "value_inversion"

    assert len(db.written_edges) == 1
    assert db.written_edges[0]["confidence"] == 0.80


# ---------------------------------------------------------------------------
# Acceptance criteria tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acceptance_constraint_violation():
    """
    AC 2, 4, 5, 6: Store "never X" constraint → ingest "X is good" turn →
    anomaly flagged with ANOMALY_DETECTED edge.
    """
    # Simulate a constraint: "never execute untrusted code"
    constraint_text = "never execute untrusted code"
    constraint_embedding = [0.1] * 384

    # Simulate content that violates: "execute this code"
    content_text = "execute this code"
    content_embedding = [0.1] * 384  # High similarity to constraint

    db = MockDb(
        constraints=[
            {
                "global_constraint_id": "gc-never-execute",
                "text_raw": constraint_text,
                "embedding": constraint_embedding,
            }
        ]
    )

    result = await check_anomalies(content_text, content_embedding, db, {})

    # AC 2, 4: Contradiction detected and flagged
    assert result["has_anomaly"] is True
    assert len(result["anomalies"]) == 1

    # AC 4, 5, 6: Create ANOMALY_DETECTED edge
    anomaly = result["anomalies"][0]
    assert anomaly["type"] == "constraint_violation"
    assert anomaly["target_id"] == "gc-never-execute"
    assert anomaly["confidence"] > 0.75

    # AC 5: Now store the flags
    await store_anomaly_flag(
        db,
        node_id="concept-xyz",
        node_type="Concept",
        anomaly_type="constraint_violation",
        constraint_id="gc-never-execute",
        confidence=anomaly["confidence"]
    )

    assert len(db.written_edges) == 1
    edge_params = db.written_edges[0]
    assert edge_params["type"] == "constraint_violation"
    assert edge_params["constraint_id"] == "gc-never-execute"


@pytest.mark.asyncio
async def test_acceptance_no_false_positives():
    """
    AC 7: Normal context shifts (context change in same conversation) should not
    flag as anomalies. Only violations of high-confidence rules.
    """
    # GlobalConstraint: "never use deprecated APIs"
    constraint_embedding = [1.0] + [0.0] * 383

    db = MockDb(
        constraints=[
            {
                "global_constraint_id": "gc-deprecated",
                "text_raw": "never use deprecated APIs",
                "embedding": constraint_embedding,
            }
        ]
    )

    # Normal context shift: talking about API documentation (no violation)
    context_embedding = [0.0] + [1.0] + [0.0] * 382  # Orthogonal, very different from constraint
    result = await check_anomalies(
        "Let's document our new APIs",
        context_embedding,
        db,
        {}
    )

    # AC 7: No false positive
    assert result["has_anomaly"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
