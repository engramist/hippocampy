from fastapi.testclient import TestClient

from web.server import create_app


class RowResult:
    def __init__(self, rows):
        self.rows = list(rows)
        self.idx = 0

    def has_next(self):
        return self.idx < len(self.rows)

    def get_next(self):
        row = self.rows[self.idx]
        self.idx += 1
        return row


class TokenMetricsDB:
    def execute(self, query, params=None):
        if "RETURN s.session_id" in query:
            return RowResult([
                [
                    "sess-1", "2026-03-28T00:00:00Z", "2026-03-28T01:00:00Z",
                    1200, 128000, 12, 4, 240
                ]
            ])
        if "-[l:LOADED]->(n:Concept)" in query:
            return RowResult([['c1', '2026-03-28T00:05:00.000Z', 100, 2]])
        if "-[l:LOADED]->(n:Decision)" in query:
            return RowResult([['d1', '2026-03-28T00:10:00.000Z', 200, 1]])
        return RowResult([])

    async def execute_write(self, query, params=None):
        pass


def test_token_metrics_endpoint_exposes_sessions():
    client = TestClient(create_app(TokenMetricsDB()))
    response = client.get('/api/token-metrics')

    assert response.status_code == 200
    data = response.json()
    assert 'sessions' in data
    assert 'summary' in data
    assert data['summary']['total_tokens_saved'] == 240
    session = data['sessions'][0]
    assert session['session_id'] == 'sess-1'
    assert session['dedup_tokens_saved'] == 240
    assert len(session['timeline']) == 2
