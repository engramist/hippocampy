from __future__ import annotations
import pytest
from datetime import datetime, timezone, timedelta

from mcp_engine.tools import notify_turn, reconstruct_timeline


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch):
    """Keep tests fully offline; do not load remote sentence-transformer models."""
    monkeypatch.setattr("mcp_engine.tools.emb.embed", lambda text, model_name=None: [0.1] * 384)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows
        self._i = 0

    def has_next(self):
        return self._i < len(self._rows)

    def get_next(self):
        r = self._rows[self._i]
        self._i += 1
        return r


class FakeDBNotify:
    def __init__(self):
        self.messages = {}  # message_id -> created_at_iso
        self.writes = []

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = query.strip()
        # Return the most recent other message in this session
        if "RETURN m.message_id, m.created_at" in q and "WHERE m.message_id <> $mid" in q:
            sid = params.get("sid")
            mid = params.get("mid")
            # find messages in the session (we don't store session mapping; assume all messages share session)
            candidates = [(mid_id, iso) for mid_id, iso in self.messages.items() if mid_id != mid]
            if not candidates:
                return FakeResult([])
            # pick latest by iso string
            candidates.sort(key=lambda x: x[1], reverse=True)
            return FakeResult([[candidates[0][0], candidates[0][1]]])
        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        params = params or {}
        q = query.strip()
        self.writes.append({"query": q, "params": params})
        # Capture created Message
        if q.startswith("CREATE (m:Message") or "CREATE (m:Message" in q:
            mid = params.get("message_id")
            created = params.get("created_at")
            if mid and created:
                self.messages[mid] = created


@pytest.mark.asyncio
async def test_notify_turn_creates_followed_by(monkeypatch):
    db = FakeDBNotify()

    # monkeypatch quest/session functions to avoid DB interaction
    async def _fake_get_or_create_main_quest(db, repo_root, git_branch, embedding_model, now):
        return "quest-1"

    monkeypatch.setattr("mcp_engine.tools.get_or_create_main_quest", _fake_get_or_create_main_quest)

    async def _fake_get_or_create_session(db_, sid, qid, now):
        return None

    monkeypatch.setattr("mcp_engine.tools.get_or_create_session", _fake_get_or_create_session)

    config = {"embeddings": {"model": "mock"}, "ingestion": {"max_ingest_chars": 4000}}

    # First message — no FOLLOWED_BY expected
    params1 = {"role": "user", "content": "first message", "session_id": "s1", "repo_root": "/r", "git_branch": "main"}
    res1 = await notify_turn(params1, db, config)
    assert res1["status"] == "queued"

    # Second message — should create FOLLOWED_BY edge linking to first
    params2 = {"role": "user", "content": "second message", "session_id": "s1", "repo_root": "/r", "git_branch": "main"}
    res2 = await notify_turn(params2, db, config)
    assert res2["status"] == "queued"

    # Inspect writes to ensure FOLLOWED_BY created
    found = any("FOLLOWED_BY" in w["query"] or "FOLLOWED_BY" in str(w.get("params", {})) for w in db.writes)
    assert found, "FOLLOWED_BY edge was not written"


class FakeDBTimeline:
    def __init__(self):
        # simple chain m1 -> m2 -> m3
        now = datetime.now(timezone.utc)
        self.messages = {
            "m1": {"text": "start foo", "created_at": (now - timedelta(seconds=30)).isoformat()},
            "m2": {"text": "middle", "created_at": (now - timedelta(seconds=20)).isoformat()},
            "m3": {"text": "end", "created_at": (now - timedelta(seconds=10)).isoformat()},
        }
        self.followed = {"m1": "m2", "m2": "m3"}
        self.decisions = {"m1": [{"decision_id": "d1", "text": "decide A"}], "m3": [{"decision_id": "d2", "text": "decide B"}]}

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = query.strip().lower()
        # match topic in messages
        if "lower(m.text_raw) contains lower($topic)" in q or "contains lower($topic)" in q:
            topic = params.get("topic", "")
            rows = []
            for mid, m in sorted(self.messages.items(), key=lambda x: x[1]["created_at"]):
                if topic in (m["text"] or "").lower():
                    rows.append([mid, m["text"], m["created_at"]])
            return FakeResult(rows)

        # decisions established containing topic
        if "match (m:message)-[:established]->(d:decision)" in q and "contains lower($topic)" in q:
            topic = params.get("topic", "")
            rows = []
            for mid, decs in self.decisions.items():
                for d in decs:
                    if topic in (d["text"] or "").lower():
                        rows.append([mid, self.messages[mid]["text"], self.messages[mid]["created_at"]])
            return FakeResult(rows)

        # fetch message by id
        if "match (m:message {message_id: $mid}) return m.message_id" in q:
            mid = params.get("mid")
            if mid in self.messages:
                m = self.messages[mid]
                return FakeResult([[mid, m["text"], m["created_at"]]])
            return FakeResult([])

        # traverse FOLLOWED_BY
        if "-[:followed_by]->(n:message)" in q:
            mid = params.get("mid")
            nxt = self.followed.get(mid)
            if nxt:
                m = self.messages[nxt]
                return FakeResult([[nxt, m["text"], m["created_at"]]])
            return FakeResult([])

        # fetch decisions for a message
        if "-[:established]->(d:decision) return d.decision_id, d.text_raw" in q:
            mid = params.get("mid")
            rows = []
            for d in self.decisions.get(mid, []):
                rows.append([d["decision_id"], d["text"]])
            return FakeResult(rows)

        return FakeResult([])


@pytest.mark.asyncio
async def test_reconstruct_timeline_returns_ordered_messages():
    db = FakeDBTimeline()
    params = {"topic": "foo", "max_hops": 10}
    result = await reconstruct_timeline(params, db, {})
    assert "timeline" in result
    timeline = result["timeline"]
    # expect first message m1, then m2, then m3
    ids = [entry["message"]["message_id"] for entry in timeline]
    assert ids == ["m1", "m2", "m3"]
    # decisions included for m1 and m3
    decs = [entry["decisions"] for entry in timeline]
    assert any(d for d in decs if d and d[0]["decision_id"] == "d1")
