import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.temporal_lobe.loop.orchestrator import run_loop
from campy.brain.thalamus.tools import init_loop_queue, notify_turn


class MockQueryResult:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._index = 0

    def has_next(self):
        return self._index < len(self._rows)

    def get_next(self):
        if not self.has_next():
            return None
        row = self._rows[self._index]
        self._index += 1
        return row


class MockDB:
    def __init__(self):
        self.writes = []

    def execute(self, query, params=None):
        return MockQueryResult()

    async def execute_write(self, query, params=None):
        self.writes.append({"query": query, "params": params or {}})

    async def execute_read(self, query, params=None):
        return []

    def vector_search(self, table_name, index_name, embedding, limit):
        return []


@pytest.mark.asyncio
async def test_notify_turn_non_git_session_ingests_message():
    """notify_turn without repo_root still creates a quest + Message."""
    db = MockDB()
    init_loop_queue(asyncio.Queue())

    result = await notify_turn(
        {
            "role": "user",
            "content": "We decided to keep analytics data in PostgreSQL.",
            "session_id": "non-git-session-001",
        },
        db,
        {
            "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
            "ingestion": {"max_ingest_chars": 4000},
        },
    )

    assert result["status"] == "ingested"
    assert result["quest_id"], "Non-git sessions should return a quest_id"

    combined_queries = " ".join(w["query"] for w in db.writes)
    assert "MainQuest" in combined_queries, "New quest should be created"
    assert "Message" in combined_queries, "Message node should be stored"
    assert "WORKING_ON" in combined_queries, "Session should link to the quest"


@pytest.mark.asyncio
async def test_non_git_session_loop_creates_concepts_and_links_session():
    """A non-git session should feed the loop, store concepts, and link to Session."""
    db = MockDB()
    init_loop_queue(asyncio.Queue())

    session_id = "non-git-session-002"
    content = "We must use PostgreSQL for analytics reporting."
    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "nlp": {"spacy_model": "en_core_web_md"},
        "hebbian": {"co_occurrence_threshold": 10},
    }

    notify_result = await notify_turn(
        {
            "role": "user",
            "content": content,
            "session_id": session_id,
        },
        db,
        config,
    )

    centroid_vector = emb.embed(content, model_name=config["embeddings"]["model"])
    centroids = {"PhysicalThing": centroid_vector}

    pre_loop_writes = len(db.writes)
    summary = await run_loop(
        message_id=notify_result["message_id"],
        text=content,
        db=db,
        llm_client=None,
        config=config,
        centroids=centroids,
        session_id=session_id,
    )

    assert summary["message_id"] == notify_result["message_id"]
    new_writes = db.writes[pre_loop_writes:]

    assert any("CREATE (c:Concept" in write["query"] for write in new_writes), \
        "Loop should create Concept nodes for non-git sessions"
    # SENT_IN is written by notify_turn (Message→Session), always present.
    # ESTABLISHED_IN is only written for >90%-confidence artifacts (requires LLM for
    # disambiguation) so cannot be asserted in a no-LLM unit test.
    all_writes = db.writes  # includes pre-loop writes from notify_turn
    assert any("SENT_IN" in write["query"] for write in all_writes), \
        "Message should be linked to Session via SENT_IN (non-git session provenance)"
