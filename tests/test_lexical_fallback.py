from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.thalamus.tools import current_truth


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0

    def has_next(self):
        return self._idx < len(self._rows)

    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class LexicalCaptureDB:
    def __init__(self, *, lexical_rows=None, vector_rows=None):
        self.lexical_rows = list(lexical_rows or [])
        self.vector_rows = vector_rows or {}
        self.queries: list[tuple[str, dict]] = []

    def vector_search(self, table_name, index_name, embedding, limit):
        return list(self.vector_rows.get(index_name, []))[:limit]

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        normalized = " ".join(query.split())
        self.queries.append((normalized, params))

        if "MATCH (m:Message)" in normalized and "CONTAINS" in normalized:
            return FakeResult(self.lexical_rows)

        if "UNWIND $ids AS nid" in normalized:
            return FakeResult([])

        if "WORKING_ON" in normalized:
            return FakeResult([])

        if "RETURN s.token_estimate, s.token_limit, s.loaded_node_count" in normalized:
            return FakeResult([])

        if "RETURN s.token_estimate" in normalized:
            return FakeResult([])

        if "RETURN count(m)" in normalized:
            return FakeResult([[0]])

        if "RETURN n." in normalized and "LOADED" in normalized:
            return FakeResult([])

        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        return None


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch):
    monkeypatch.setattr(
        "campy.brain.thalamus.tools.emb.embed",
        lambda text, model_name=None: [0.1] * 384,
    )


def _query_text(db: LexicalCaptureDB) -> str:
    return next(q for q, _ in db.queries if "MATCH (m:Message)" in q)


@pytest.mark.asyncio
async def test_lexical_query_has_window_and_limit():
    db = LexicalCaptureDB()

    await current_truth(
        {"query": "recent capture", "session_id": "unknown"},
        db,
        {"embeddings": {"model": "mock"}, "retrieval": {"lexical_window_days": 14, "lexical_limit": 10}},
    )

    q = _query_text(db)
    assert "timestamp($cutoff)" in q
    assert "LIMIT 10" in q


@pytest.mark.asyncio
async def test_recent_message_surfaces_with_lexical_exact():
    db = LexicalCaptureDB(
        lexical_rows=[
            [
                "m-recent",
                "We just discussed the bounded lexical fallback yesterday.",
                "user",
                0.0,
                True,
                0.0,
                datetime(2026, 6, 10, 12, tzinfo=timezone.utc).isoformat(),
            ]
        ]
    )

    result = await current_truth(
        {"query": "bounded lexical fallback", "session_id": "unknown"},
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert result["results"][0]["node_id"] == "m-recent"
    assert result["results"][0]["node_type"] == "Message"
    assert result["results"][0]["lexical_exact"] is True


@pytest.mark.asyncio
async def test_config_overrides_window():
    fixed_now = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    db = LexicalCaptureDB()
    import campy.brain.thalamus.tools as tools_mod

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tools_mod, "datetime", FrozenDatetime)
    try:
        await current_truth(
            {"query": "window override", "session_id": "unknown"},
            db,
            {"embeddings": {"model": "mock"}, "retrieval": {"lexical_window_days": 2}},
        )
    finally:
        monkeypatch.undo()

    _, params = next(item for item in db.queries if "MATCH (m:Message)" in item[0])
    assert params["cutoff"].startswith((fixed_now - timedelta(days=2)).isoformat()[:10])


@pytest.mark.asyncio
async def test_old_message_can_still_surface_via_vector_search():
    db = LexicalCaptureDB(
        vector_rows={
            "message_emb_idx": [
                {
                    "node": {
                        "message_id": "m-old",
                        "text_raw": "An older note about bounded lexical fallback.",
                        "role": "user",
                        "pathway_strength": 0.2,
                        "confidence": 0.5,
                        "confidence_low": True,
                        "archived": False,
                    },
                    "score": 0.96,
                }
            ]
        }
    )

    result = await current_truth(
        {"query": "bounded lexical fallback", "session_id": "unknown"},
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert result["results"][0]["node_id"] == "m-old"
    assert result["results"][0]["lexical_exact"] is False


def test_fts_probe_graceful_failure():
    client = object.__new__(KuzuClient)
    client._fts_checked = None

    def _boom(*args, **kwargs):
        raise RuntimeError("fts unavailable")

    client.execute = _boom  # type: ignore[attr-defined]

    assert client.has_fts() is False
    assert client.has_fts() is False
