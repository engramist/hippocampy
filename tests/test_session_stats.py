
import pytest
import uuid
import asyncio
from mcp_engine.tools import context_status

class RecordingDB:
    class _MockResult:
        def __init__(self, rows=None):
            self.rows = rows or []
            self.pos = 0
        def has_next(self):
            return self.pos < len(self.rows)
        def get_next(self):
            res = self.rows[self.pos]
            self.pos += 1
            return res

    def __init__(self):
        self.results = {}

    def set_result(self, query_substring, rows):
        self.results[query_substring] = rows

    def execute(self, query, params=None):
        for sub, rows in self.results.items():
            if sub in query:
                return self._MockResult(rows)
        return self._MockResult()

@pytest.mark.asyncio
async def test_message_count_in_context_status():
    """
    B64: Verify message_count is correctly reported in context_status tool.
    Trace: Session node -> count SENT_IN edges -> return count
    """
    db = RecordingDB()
    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "ingestion": {"max_ingest_chars": 4000}
    }
    session_id = "test-session-123"

    # Mock Session result for get_session_token_state
    db.set_result("MATCH (s:Session {session_id: $sid}) RETURN", [[100, 1000, 5, 0, 0]])
    # Mock SENT_IN count result
    db.set_result("MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})", [[3]])

    res = await context_status({"session_id": session_id}, db, config)
    
    assert "message_count" in res
    assert res["message_count"] == 3
    assert res["token_estimate"] == 100
    assert res["loaded_nodes"] == 5

@pytest.mark.asyncio
async def test_archived_messages_excluded_from_stats():
    """
    B64: Verify that archived=true messages are excluded from stats.
    """
    db = RecordingDB()
    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "ingestion": {"max_ingest_chars": 4000}
    }
    session_id = "test-session-456"

    # Mock Session result
    db.set_result("MATCH (s:Session {session_id: $sid}) RETURN", [[100, 1000, 5, 0, 0]])
    
    # Mock result for the new query including NULL/false
    # The code will call: MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) WHERE m.archived IS NULL OR m.archived = false RETURN count(m)
    db.set_result("WHERE m.archived IS NULL OR m.archived = false", [[2]])

    res = await context_status({"session_id": session_id}, db, config)
    
    assert res["message_count"] == 2
