
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from mcp_engine.loop.orchestrator import run_loop

@pytest.mark.asyncio
async def test_run_loop_with_precomputed_data():
    # Mock dependencies
    db = MagicMock()
    # Mock db.execute for the Message node check
    mock_result = MagicMock()
    mock_result.has_next.return_value = True
    db.execute.return_value = mock_result
    
    # Use AsyncMock for methods that are awaited
    db.execute_read = AsyncMock(return_value=[])
    db.execute_write = AsyncMock()
    
    llm_client = MagicMock()
    config = {
        "embeddings": {"model": "all-MiniLM-L6-v2"},
        "nlp": {"spacy_model": "en_core_web_md"},
        "hebbian": {"co_occurrence_threshold": 10}
    }
    centroids = {}
    
    precomputed = {
        "entities": [
            {"text": "ARC-AGI-3", "gist_class": "Category", "schema_org_type": "DefinedTerm", "label": "ORG"},
            {"text": "ACTION1", "gist_class": "PlannedEvent", "schema_org_type": "Action", "label": "ORG"}
        ],
        "relations": [
            {"head": "ACTION1", "relation_type": "PART_OF", "tail": "ARC-AGI-3", "confidence": 0.9}
        ]
    }
    
    # Mock embedding to return dummy vectors
    with patch("mcp_engine.graph.embeddings.embed", return_value=[0.1] * 384):
        # Mock extract_entities to prove it's NOT called
        with patch("mcp_engine.loop.orchestrator.extract_entities") as mock_extract:
            # Mock classify_artifact to ensure it proceeds
            with patch("mcp_engine.loop.orchestrator.classify_artifact", return_value={"artifact_type": "decision", "confidence": 0.95, "confidence_low": False, "should_proceed": True}):
                # Mock storage functions to return string IDs for comparison
                mock_store_concept = AsyncMock(side_effect=["cid1", "cid2"])
                with patch("mcp_engine.loop.orchestrator._store_concept", mock_store_concept):
                    with patch("mcp_engine.loop.orchestrator._ensure_concept_exists", side_effect=["id1", "id2", "id3", "id4"]):
                        with patch("mcp_engine.loop.orchestrator._store_relation", return_value=None):
                            with patch("mcp_engine.loop.orchestrator._reify_concept", side_effect=["cid1", "cid2", "cid3", "cid4"]):
                                with patch("mcp_engine.loop.orchestrator.retrieve_candidates", return_value=[]):
                                    summary = await run_loop(
                                        message_id="msg-123",
                                        text="ARC-AGI-3 has ACTION1.",
                                        db=db,
                                        llm_client=llm_client,
                                        config=config,
                                        centroids=centroids,
                                        precomputed=precomputed
                                    )
                                    
                                    # Verify extract_entities was NOT called
                                    mock_extract.assert_not_called()
                                    
                                    # Verify summary reflects precomputed counts
                                    assert summary["entities_found"] == 2
                                    assert summary["relations_found"] == 1
                                    
                                    # Verify _store_concept was called to store entities
                                    assert mock_store_concept.called

@pytest.mark.asyncio
async def test_run_loop_without_precomputed_data():
    # Mock dependencies
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.has_next.return_value = True
    db.execute.return_value = mock_result
    
    db.execute_read = AsyncMock(return_value=[])
    db.execute_write = AsyncMock()
    
    llm_client = MagicMock()
    config = {
        "embeddings": {"model": "all-MiniLM-L6-v2"},
        "nlp": {"spacy_model": "en_core_web_md"},
        "hebbian": {"co_occurrence_threshold": 10}
    }
    centroids = {}
    
    # Mock steps that use LLM or spaCy
    with patch("mcp_engine.graph.embeddings.embed", return_value=[0.1] * 384):
        with patch("mcp_engine.loop.orchestrator.extract_entities", return_value=(MagicMock(), [{"text": "e1", "label": "ORG"}])):
            with patch("mcp_engine.loop.orchestrator.classify_concept", return_value={"gist_class": "Category", "confidence": 0.8, "system": "1", "vector": [0.1]*384}):
                with patch("mcp_engine.loop.orchestrator.route_to_schema_org", return_value={"schema_org_type": "Thing"}):
                    with patch("mcp_engine.loop.orchestrator.extract_relations", return_value=[]):
                        with patch("mcp_engine.loop.orchestrator.classify_artifact", return_value={"artifact_type": "decision", "confidence": 0.95, "confidence_low": False, "should_proceed": True}):
                            mock_store_concept = AsyncMock(side_effect=["cid1"])
                            with patch("mcp_engine.loop.orchestrator._store_concept", mock_store_concept):
                                with patch("mcp_engine.loop.orchestrator._ensure_concept_exists", side_effect=["id1", "id2"]):
                                    with patch("mcp_engine.loop.orchestrator._reify_concept", side_effect=["cid1", "cid2"]):
                                        with patch("mcp_engine.loop.orchestrator.retrieve_candidates", return_value=[]):
                                            summary = await run_loop(
                                                message_id="msg-456",
                                                text="Some text",
                                                db=db,
                                                llm_client=llm_client,
                                                config=config,
                                                centroids=centroids,
                                                precomputed=None
                                            )
                                            
                                            assert summary["entities_found"] == 1
                                            assert mock_store_concept.called
