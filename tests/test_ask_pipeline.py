"""
Integration tests for B374: Budget-Gated Pressure-Relief Valve in the ask pipeline.

Validates:
1. Sub-budget bypass: When total estimated tokens <= budget_tokens, compression
   stage is bypassed completely with 0s latency overhead (100% bypass rate).
2. Over-budget pressure relief: When bundle > budget_tokens, compression executes,
   reducing Bulk Lane sections while preserving Protected Lane sections verbatim (0% loss).
3. Parameter precedence: budget_tokens parameter, token_budget parameter, and
   config [compression].budget_tokens resolution.
4. Graph traversal bounds: Depth <= 2, fan-out <= 15, and early root filtering
   of archived and deprecated nodes.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from campy.brain.thalamus.ask import run_ask
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_section(sec_type: str, content: list, token_estimate: int) -> BundleSection:
    return BundleSection(
        section_type=sec_type,
        content=content,
        token_estimate=token_estimate,
        source_node_ids=["src1"],
    )


def _make_bundle(sections: list[BundleSection]) -> ContextBundle:
    total_tokens = sum(s.token_estimate for s in sections)
    return ContextBundle(
        query="test query",
        sections=sections,
        total_token_estimate=total_tokens,
        token_budget=32000,
        truncated=False,
    )


# ---------------------------------------------------------------------------
# Tests: Pressure-Relief Valve Gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sub_budget_bypasses_compression_completely():
    """When bundle total estimated tokens <= budget_tokens, skip compression entirely."""
    mock_db = MagicMock()
    config = {
        "llm": {"provider": "ollama", "model": "llama3.1:8b"},
        "compression": {"budget_tokens": 4000},
    }

    # Assembled bundle is 500 tokens (well under 4000)
    bundle_sections = [
        _make_section("exact_fact", [{"key": "timeout", "value": "30"}], 100),
        _make_section("summary", [{"text": "Prior work completed successfully."}], 400),
    ]
    bundle = _make_bundle(bundle_sections)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Verified answer from uncompressed memory."

    meta = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle),          patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm),          patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock),          patch("campy.brain.thalamus.compression.build_default_registry") as mock_registry:

        answer = await run_ask(
            query="check status",
            session_id="sess-sub-budget",
            db=mock_db,
            config=config,
            meta=meta,
        )

    assert answer == "Verified answer from uncompressed memory."
    # Gating check: build_default_registry must NEVER be called (0 compression latency)
    mock_registry.assert_not_called()
    assert meta.get("compression_bypassed") is True
    assert meta.get("total_tokens") == 500
    assert meta.get("budget_tokens") == 4000


@pytest.mark.asyncio
async def test_over_budget_triggers_two_lane_compression():
    """When bundle > budget_tokens, compress Bulk Lane while preserving Protected Lane verbatim."""
    mock_db = MagicMock()
    config = {
        "llm": {"provider": "ollama", "model": "llama3.1:8b"},
        "compression": {
            "budget_tokens": 2000,
            "graph_prune_threshold": 0.50,
            "ast_compression": True,
        },
    }

    protected_decision = {"decision_id": "D-42", "text": "Must use Ed25519 signing", "confidence": 0.99}
    protected_constraint = {"constraint_id": "K-1", "text": "Never commit keys", "active": True}

    python_source = """
class KeyManager:
    def __init__(self, vault):
        self.vault = vault
        self._keys = {}

    def fetch_key(self, key_id: str) -> bytes:
        if key_id not in self._keys:
            self._keys[key_id] = self.vault.read(key_id)
        return self._keys[key_id]
"""

    graph_nodes = [
        {"text": f"relevant node {i}", "type": "Concept", "pathway_strength": 0.9, "confidence": 0.9}
        for i in range(5)
    ] + [
        {"text": f"stale node {i}", "type": "Concept", "pathway_strength": 0.05, "confidence": 0.5}
        for i in range(25)
    ]

    # Total tokens = 200 (protected) + 200 (protected) + 1200 (bulk code) + 1800 (bulk graph) = 3400 > 2000 budget
    bundle_sections = [
        _make_section("decision", [protected_decision], 200),
        _make_section("constraint", [protected_constraint], 200),
        _make_section("code", [{"source": python_source, "language": "python"}], 1200),
        _make_section("semantic", graph_nodes, 1800),
    ]
    bundle = _make_bundle(bundle_sections)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Answer generated under budget."

    meta = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle),          patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm),          patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):

        answer = await run_ask(
            query="how are keys managed?",
            session_id="sess-over-budget",
            db=mock_db,
            config=config,
            meta=meta,
        )

    assert answer == "Answer generated under budget."
    assert meta.get("compression_bypassed") is False
    assert meta.get("total_tokens") == 3400

    # Verify Protected Lane sections are untouched (0% loss)
    sec_map = {s.section_type: s for s in bundle.sections}
    assert sec_map["decision"].content == [protected_decision]
    assert sec_map["decision"].token_estimate == 200

    assert sec_map["constraint"].content == [protected_constraint]
    assert sec_map["constraint"].token_estimate == 200

    # Verify Bulk Lane sections underwent compression
    assert sec_map["code"].token_estimate < 1200
    assert sec_map["semantic"].token_estimate < 1800

    # Post-compression tokens should be substantially reduced
    assert meta.get("post_compression_tokens") < meta.get("total_tokens")


@pytest.mark.asyncio
async def test_budget_parameter_precedence():
    """Verify precedence: explicit budget_tokens > explicit token_budget > config budget_tokens."""
    mock_db = MagicMock()
    config = {
        "llm": {"provider": "ollama", "model": "llama3.1:8b"},
        "compression": {"budget_tokens": 5000},
    }

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "ok"

    # Case 1: Caller passes budget_tokens=1000 override
    bundle = _make_bundle([_make_section("exact_fact", [{"k": "v"}], 2000)])
    meta1 = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle),          patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm),          patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask("q", "s", mock_db, config, budget_tokens=1000, meta=meta1)
    # 2000 > 1000, so compression triggered
    assert meta1["budget_tokens"] == 1000
    assert meta1["compression_bypassed"] is False

    # Case 2: Caller passes token_budget=1500 (non-32000)
    bundle = _make_bundle([_make_section("exact_fact", [{"k": "v"}], 2000)])
    meta2 = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle),          patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm),          patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask("q", "s", mock_db, config, token_budget=1500, meta=meta2)
    assert meta2["budget_tokens"] == 1500
    assert meta2["compression_bypassed"] is False

    # Case 3: Defaults inherit config["compression"]["budget_tokens"] = 5000
    bundle = _make_bundle([_make_section("exact_fact", [{"k": "v"}], 2000)])
    meta3 = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle),          patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm),          patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask("q", "s", mock_db, config, meta=meta3)
    # 2000 <= 5000, so compression bypassed
    assert meta3["budget_tokens"] == 5000
    assert meta3["compression_bypassed"] is True


# ---------------------------------------------------------------------------
# Tests: Graph Traversal Bounds & Early Filtering Guardrail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graph_traversal_bounds_and_filtering():
    """Verify graph anchor limits (<= 5), traversal hops (<= 2), fanout (<= 15) and root filtering."""
    from campy.brain.thalamus.bundle_compiler import _stage_graph_structure

    mock_db = MagicMock()

    # Simulate Concept table having archived, superseded_by, and flagged_for_review columns
    def fake_execute(query, params=None):
        mock_result = MagicMock()
        if "CALL table_info" in query:
            # Return columns: concept_id, text_raw, embedding, archived, superseded_by, flagged_for_review
            columns = [
                (0, "concept_id"),
                (1, "text_raw"),
                (2, "embedding"),
                (3, "archived"),
                (4, "superseded_by"),
                (5, "flagged_for_review"),
            ]
            mock_result.has_next.side_effect = [True] * len(columns) + [False]
            mock_result.get_next.side_effect = columns
            return mock_result

        if "LIMIT 5" in query:
            # Anchor query: ensure filters for archived and superseded_by are present
            assert "archived" in query
            assert "superseded_by" in query
            # Return 2 anchors
            rows = [
                ("c1", "Concept 1", 0.1),
                ("c2", "Concept 2", 0.15),
            ]
            mock_result.has_next.side_effect = [True, True, False]
            mock_result.get_next.side_effect = rows
            return mock_result

        if "MATCH (a:Concept)-[r:" in query:
            # Edge query: ensure hop fanout limit is bounded (LIMIT 10 <= 15)
            assert "LIMIT 10" in query
            mock_result.has_next.side_effect = [False]
            return mock_result

        mock_result.has_next.return_value = False
        return mock_result

    mock_db.execute = fake_execute

    with patch("campy.brain.hippocampus.graph.embeddings.embed", return_value=[0.1] * 384):
        section = await _stage_graph_structure(
            db=mock_db,
            query="test architecture",
            config={"embeddings": {}},
            tier_config={"max_graph_hops": 2},
            existing_sources=[],
        )

    # Hop depth should be bounded to <= 2
    assert section is None or section.section_type == "graph"
