from __future__ import annotations

import pytest

from mcp_engine.tools import current_truth, notify_turn


class FakeResult:
    def __init__(self, rows):
        self.rows = rows
        self.idx = 0

    def has_next(self):
        return self.idx < len(self.rows)

    def get_next(self):
        row = self.rows[self.idx]
        self.idx += 1
        return row


class RecallContractDB:
    """Small in-memory stand-in for the recall contract.

    It models the pieces current_truth/notify_turn need without requiring a
    real Kuzu lock: Message writes, vector candidates, exact Message lookup,
    LOADED writes, and token accounting.
    """

    def __init__(self):
        self.messages: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        self.loaded_edges: list[dict] = []
        self.writes: list[dict] = []
        self.token_estimate = 0
        self.token_limit = 128000

    def add_decision(
        self,
        *,
        decision_id: str,
        text_raw: str,
        pathway_strength: float,
        confidence: float,
        score: float = 0.7,
    ) -> None:
        self.decisions[decision_id] = {
            "node": {
                "decision_id": decision_id,
                "text_raw": text_raw,
                "pathway_strength": pathway_strength,
                "confidence": confidence,
                "confidence_low": False,
                "archived": False,
            },
            "score": score,
        }

    def vector_search(self, table_name, index_name, embedding, limit):
        if index_name == "message_emb_idx":
            rows = []
            for message in self.messages.values():
                rows.append({
                    "node": {
                        "message_id": message["message_id"],
                        "text_raw": message["text_raw"],
                        "role": message["role"],
                        "pathway_strength": message.get("pathway_strength", 0.0),
                        "confidence": message.get("confidence", 0.0),
                        "confidence_low": message.get("confidence_low", True),
                        "archived": False,
                    },
                    "score": message.get("score", 0.95),
                })
            return rows[:limit]
        if index_name == "decision_emb_idx":
            return list(self.decisions.values())[:limit]
        return []

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = " ".join(query.split())

        if "WORKING_ON" in q:
            return FakeResult([])

        if "UNWIND $ids AS nid" in q:
            return FakeResult([])

        if "RETURN s.token_estimate, s.token_limit, s.loaded_node_count" in q:
            return FakeResult([[self.token_estimate, self.token_limit, len(self.loaded_edges), 0, 0]])

        if "RETURN s.token_estimate" in q:
            return FakeResult([[self.token_estimate]])

        if "RETURN count(m)" in q:
            return FakeResult([[len(self.messages)]])

        if "RETURN count(*)" in q and "LOADED" in q:
            return FakeResult([[len(self.loaded_edges)]])

        if "[:LOADED]->" in q and "RETURN n." in q:
            return FakeResult([[edge["node_id"]] for edge in self.loaded_edges])

        if "-[l:LOADED]->" in q and "RETURN l.load_hits" in q:
            nid = params.get("nid")
            hits = [edge["load_hits"] for edge in self.loaded_edges if edge["node_id"] == nid]
            return FakeResult([[hits[0]]] if hits else [])

        if "MATCH (m:Message) WHERE lower(m.text_raw) CONTAINS lower($query)" in q:
            needle = (params.get("query") or "").lower()
            rows = []
            for message in self.messages.values():
                if needle in message["text_raw"].lower():
                    rows.append([
                        message["message_id"],
                        message["text_raw"],
                        message["role"],
                        message.get("confidence", 0.0),
                        message.get("confidence_low", True),
                        message.get("pathway_strength", 0.0),
                        message.get("created_at"),
                    ])
            return FakeResult(rows)

        if "WHERE m.message_id <> $mid" in q:
            return FakeResult([])

        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        params = params or {}
        q = " ".join(query.split())
        self.writes.append({"query": q, "params": params})

        if "CREATE (m:Message" in q:
            self.messages[params["message_id"]] = {
                "message_id": params["message_id"],
                "text_raw": params["text_raw"],
                "role": params["role"],
                "created_at": params["created_at"],
                "pathway_strength": 0.0,
                "confidence": 0.0,
                "confidence_low": True,
                "score": 0.95,
            }
            return

        if "CREATE (s)-[:LOADED" in q:
            self.loaded_edges.append({
                "node_id": params["nid"],
                "source": params.get("source"),
                "load_hits": 1,
            })
            return

        if "SET s.token_estimate = $est" in q:
            self.token_estimate = params["est"]


@pytest.fixture(autouse=True)
def _offline_embeddings(monkeypatch):
    monkeypatch.setattr("mcp_engine.tools.emb.embed", lambda text, model_name=None: [0.1] * 384)


@pytest.fixture
def _no_git_quest_work(monkeypatch):
    async def _quest(*args, **kwargs):
        return "quest-recall-contract"

    async def _session(*args, **kwargs):
        return None

    monkeypatch.setattr("mcp_engine.tools.get_or_create_main_quest", _quest)
    monkeypatch.setattr("mcp_engine.tools.get_or_create_session", _session)


@pytest.mark.asyncio
async def test_recall_contract_captures_and_finds_raw_message_without_loaded_edge(_no_git_quest_work):
    db = RecallContractDB()
    phrase = "recall_contract_probe_sidequests_no_context_bloat_001"

    stored = await notify_turn(
        {
            "role": "user",
            "content": f"Please remember this test phrase: {phrase}",
            "session_id": "recall-contract",
            "repo_root": "/repo",
            "git_branch": "main",
        },
        db,
        {"embeddings": {"model": "mock"}, "ingestion": {"max_ingest_chars": 4000}},
    )
    assert stored["status"] == "ingested"
    assert db.messages

    recalled = await current_truth(
        {
            "query": phrase,
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 5,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert any(r["node_type"] == "Message" and phrase in r["text_raw"] for r in recalled["results"])
    assert db.loaded_edges == []
    assert db.token_estimate > 0


@pytest.mark.asyncio
async def test_recall_contract_consolidated_memory_outranks_raw_message(_no_git_quest_work):
    db = RecallContractDB()
    phrase = "recall_contract_installer_capture_policy"
    db.messages["m-low"] = {
        "message_id": "m-low",
        "text_raw": f"Raw transcript mention: {phrase}",
        "role": "user",
        "created_at": "2026-05-10T00:00:00Z",
        "pathway_strength": 0.1,
        "confidence": 0.2,
        "confidence_low": True,
        "score": 0.99,
    }
    db.add_decision(
        decision_id="d-high",
        text_raw=f"Decision: keep {phrase} as durable capture fallback, not context cargo.",
        pathway_strength=0.9,
        confidence=0.9,
        score=0.65,
    )

    recalled = await current_truth(
        {
            "query": phrase,
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 5,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert recalled["results"][0]["node_type"] == "Decision"
    assert recalled["results"][0]["node_id"] == "d-high"
    assert any(edge["node_id"] == "d-high" for edge in db.loaded_edges)
    assert not any(edge["node_id"] == "m-low" for edge in db.loaded_edges)


@pytest.mark.asyncio
async def test_recall_contract_respects_limit(_no_git_quest_work):
    db = RecallContractDB()
    for idx in range(10):
        db.add_decision(
            decision_id=f"d-{idx}",
            text_raw=f"Recall limit candidate {idx}",
            pathway_strength=1.0 - (idx * 0.01),
            confidence=0.9,
            score=0.8,
        )

    recalled = await current_truth(
        {
            "query": "Recall limit candidate",
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 3,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert len(recalled["results"]) == 3
