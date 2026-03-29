
import pytest
from web.server import create_app
from fastapi.testclient import TestClient

class MockDB:
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

def test_thinking_stats_includes_messages():
    """B64: Verify Message count is included in the /api/thinking stats summary."""
    db = MockDB()
    # Mock result for Message count
    db.set_result("MATCH (n:Message) WHERE n.archived = false", [[42]])
    
    app = create_app(db)
    client = TestClient(app)
    
    response = client.get("/api/thinking")
    assert response.status_code == 200
    data = response.json()
    assert "stats" in data
    assert "messages" in data["stats"]
    assert data["stats"]["messages"] == 42
