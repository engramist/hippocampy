"""B580: a text parameter that starts with "http(s)://" (or even with one of the store's own bases) must bind as a
literal, not an IRI; an error the daemon replies with is reported as an error, not as "offline"; a poisoned offline
queue entry is dropped after one daemon-replied error, and kept while the daemon is unreachable."""
from __future__ import annotations

import json

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import IRI, OxigraphClient, _format_sparql_term
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy import brain_transport as bt

URL_TEXT = "https://www.youtube.com/watch?v=abc&ab\\_channel=someone\n\nin this song he remixes it, which version?"
OWN_BASE_TEXT = "https://campy.dev/id/Message/abc see this\n"
DIM = 384
P = "PREFIX campy:<https://campy.dev/ns#>\n"


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "b580.db"), REGISTRY)


async def _write(gw, mid, text):
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=[0.5] * DIM,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text.encode()),
                 created_at="2023-05-07T00:43:00")


def _text_of(db, mid):
    rows = db._execute_and_collect(P + "SELECT ?t (isLiteral(?t) AS ?lit) WHERE { ?m a campy:Message ; "
                                   "campy:message_id ?id ; campy:text_raw ?t } ", {"id": mid})
    assert len(rows) == 1, rows
    return rows[0]["t"], rows[0]["lit"]


# (1) a URL-leading turn with a backslash, a space and a newline is captured and reads back as a literal
@pytest.mark.asyncio
async def test_url_leading_message_round_trips_as_literal(gw):
    await _write(gw, "m-url", URL_TEXT)
    text, lit = _text_of(gw._client, "m-url")
    assert text == URL_TEXT and lit is True


# (5) a message that starts with one of the store's own node URIs is still free text
@pytest.mark.asyncio
async def test_own_base_leading_message_round_trips_as_literal(gw):
    await _write(gw, "m-own", OWN_BASE_TEXT)
    text, lit = _text_of(gw._client, "m-own")
    assert text == OWN_BASE_TEXT and lit is True


# (2) an explicitly marked external IRI still binds as an IRI; a plain http string binds as a literal;
#     a valid own-base node id still binds as an IRI
def test_iri_marker_and_plain_strings():
    assert _format_sparql_term(IRI("https://schema.org/Person")) == "<https://schema.org/Person>"
    assert _format_sparql_term("https://schema.org/Person") == '"https://schema.org/Person"'
    assert _format_sparql_term("https://campy.dev/id/Message/abc") == "<https://campy.dev/id/Message/abc>"
    assert not _format_sparql_term(OWN_BASE_TEXT).startswith("<")


# (4) a Message stored earlier with its text as an IRI is still readable
@pytest.mark.asyncio
async def test_message_with_iri_text_is_still_readable(gw):
    db = gw._client
    db.execute(P + "INSERT DATA { <https://campy.dev/id/Message/old> a campy:Message ; campy:message_id \"old\" ; "
               "campy:text_raw <https://example.org/page> . }")
    node = db.get_node("Message", "https://campy.dev/id/Message/old")
    assert node is not None and node["text_raw"] == "https://example.org/page"
    text, lit = _text_of(db, "old")
    assert text == "https://example.org/page" and lit is False


# (3) a daemon-replied error is an error, not "queued_offline", and nothing is queued; unreachable is still offline
@pytest.mark.asyncio
async def test_adapter_reports_daemon_error_not_offline(monkeypatch, tmp_path):
    from campy.adapters import mcp_server as ms

    monkeypatch.setattr(ms, "OFFLINE_QUEUE", tmp_path / "offline_queue.jsonl")
    monkeypatch.setattr(bt, "_record_soft_failure", lambda m, e: 1)
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "notify_turn", "arguments": {"role": "user", "content": URL_TEXT, "session_id": "s"}}}

    async def reply_error(method, params, timeout):
        raise bt.DaemonReplyError("error at 25:71: expected IRIs are only allowed to contain escape sequences")
    monkeypatch.setattr(bt, "call_brain", reply_error)
    out = await ms.handle_mcp_request(req)
    assert "error" in out and "queued_offline" not in json.dumps(out)
    assert not (tmp_path / "offline_queue.jsonl").exists()

    async def unreachable(method, params, timeout):
        raise RuntimeError("DAEMON_OFFLINE: socket transports failed")
    monkeypatch.setattr(bt, "call_brain", unreachable)
    out = await ms.handle_mcp_request(req)
    assert "queued_offline" in json.dumps(out)
    assert (tmp_path / "offline_queue.jsonl").exists()


# (6) a poisoned queue entry is dropped after one daemon-replied error; an unreachable daemon leaves it queued
@pytest.mark.asyncio
async def test_poisoned_queue_entry_dropped_unreachable_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "_record_soft_failure", lambda m, e: 1)
    q = tmp_path / "offline_queue.jsonl"
    entries = [{"method": "notify_turn", "params": {"content": c}} for c in ("poisoned", "fine")]
    q.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    seen = []

    async def daemon(method, params):
        seen.append(params["content"])
        if params["content"] == "poisoned":
            raise bt.DaemonReplyError("query error")
        return {"status": "ok"}
    counts = await bt.replay_offline_queue(q, daemon)
    assert counts == {"replayed": 1, "dropped": 1, "kept": 0} and seen == ["poisoned", "fine"]
    assert not q.exists()

    q.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    async def offline(method, params):
        raise RuntimeError("DAEMON_OFFLINE: soft-failure calling notify_turn")
    counts = await bt.replay_offline_queue(q, offline)
    assert counts["kept"] == 2 and counts["dropped"] == 0
    assert [json.loads(x)["params"]["content"] for x in q.read_text().splitlines()] == ["poisoned", "fine"]
