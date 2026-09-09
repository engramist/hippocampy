"""
tests/test_b412_read_path_fixes.py — Proof tests for B412's read-path
schema-conformance fixes.

B412's own requirement: "Each fix must be proven by a test asserting
NON-EMPTY, CORRECT results" — not that the query runs without error. A
query returning `[]` passes the conformance checker's structural scan today
(it only inspects `NamedQuery.cypher`), while `NamedQuery.sparql` is what
actually executes on the Oxigraph runtime path (B397 cutover) — so every
test here drives the real `GraphGateway` + `OxigraphClient` + `REGISTRY`
path, not just the static Cypher text.

Fixes proven here:
1. `retrieval.get_originating_message_*` (7 queries): `Message` has
   `text_raw`, not `content`.
2. `thalamus.file_bridge_concepts` / `file_bridge_concept_relationships` /
   `file_bridge_decisions` (4 violations): SKOS pref/alt labels live on
   separate `Label` nodes reached via `HAS_PREF_LABEL`/`HAS_ALT_LABEL`, not
   `Concept`/`Decision` columns.
3. `capture.get_last_proactive_push_count` (1): schema was missing a real,
   live column (`Session.last_proactive_push_msg_count`) — added to
   `SCHEMA_MIGRATIONS` rather than renaming the (already-correct) query.
4. `arc.get_action_fact_detail` (4): deleted as unreachable — a regression
   guard proves no caller references it.

`quests.get_session_onboarding_status` (`MainQuest.git_branch`) is
deliberately NOT covered here — B412 escalates that one rather than
guessing; see the comment on the NamedQuery itself
(campy/brain/hippocampus/graph/queries/quests.py).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import CAMPY_NS, OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b412.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Message.content -> Message.text_raw
# ---------------------------------------------------------------------------

_ORIGINATING_MESSAGE_CASES = [
    ("Concept", "concept_id", "concept"),
    ("Decision", "decision_id", "decision"),
    ("Constraint", "constraint_id", "constraint"),
    ("Requirement", "requirement_id", "requirement"),
    ("ActionItem", "action_item_id", "actionitem"),
    ("DocumentExtract", "extract_id", "documentextract"),
    ("Message", "message_id", "message"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("label,pk,key", _ORIGINATING_MESSAGE_CASES, ids=[c[2] for c in _ORIGINATING_MESSAGE_CASES])
async def test_get_originating_message_returns_real_text(ox_client, gw, label, pk, key):
    """retrieval.get_originating_message_{key} must return the real
    Message.text_raw content, not silently NULL out on a nonexistent
    Message.content column."""
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"
    expected_text = f"the originating message text for {key}"
    originating_msg_uri = ox_client.write_node("Message", {"message_id": msg_id, "text_raw": expected_text})

    if label == "Message":
        # Query shape is (n:Message)-[:ESTABLISHED_IN]->(m:Message) — n and
        # m must be two distinct Message nodes.
        node_pk_value = f"msg_{uuid.uuid4().hex[:8]}"
        node_uri = ox_client.write_node(
            "Message", {"message_id": node_pk_value, "text_raw": "the current message, not the originating one"}
        )
    else:
        node_id = f"{key}_{uuid.uuid4().hex[:8]}"
        node_pk_value = node_id
        node_uri = ox_client.write_node(label, {pk: node_id})

    ox_client.write_edge("ESTABLISHED_IN", node_uri, originating_msg_uri)

    rows = await gw.run(f"retrieval.get_originating_message_{key}", id=node_pk_value)

    assert rows, f"retrieval.get_originating_message_{key} returned no rows"
    row = rows[0]
    value = row.get("m.content") if hasattr(row, "get") else row[0]
    assert value == expected_text, (
        f"retrieval.get_originating_message_{key} returned {value!r}, expected {expected_text!r}"
    )

    # --- Teeth check: the pre-fix SPARQL (campy:content instead of
    # campy:text_raw) returns nothing against this exact fixture data,
    # proving the fix — not just "the query runs" — is what changed.
    old_buggy_sparql = f"""
        PREFIX campy: <{CAMPY_NS}>
        SELECT ?content WHERE {{
            ?n a campy:{label} ; campy:{pk} ?id .
            ?n campy:ESTABLISHED_IN ?m .
            ?m a campy:Message .
            OPTIONAL {{ ?m campy:content ?content }}
            FILTER(?id = "{node_pk_value}")
        }}
        LIMIT 1
    """
    old_rows = ox_client._execute_and_collect(old_buggy_sparql)
    assert old_rows, "old query shape should still return a row (OPTIONAL keeps it)"
    assert old_rows[0].get("content") is None, (
        "pre-fix campy:content binding unexpectedly resolved — fixture or "
        "assumption about the bug is wrong"
    )


# ---------------------------------------------------------------------------
# 2. Concept/Decision prefLabel/altLabel -> Label traversal via
#    HAS_PREF_LABEL / HAS_ALT_LABEL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_bridge_concepts_resolves_pref_and_alt_labels(ox_client, gw):
    cid = f"concept_{uuid.uuid4().hex[:8]}"
    c_uri = ox_client.write_node(
        "Concept",
        {
            "concept_id": cid,
            "text_raw": "A thing with a preferred name and two aliases.",
            "gist_class": "Category",
            "confidence": 0.9,
            "pathway_strength": 0.75,
        },
    )

    pref_uri = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Canonical Name"})
    ox_client.write_edge("HAS_PREF_LABEL", c_uri, pref_uri)

    alt1_uri = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Alias One"})
    alt2_uri = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Alias Two"})
    ox_client.write_edge("HAS_ALT_LABEL", c_uri, alt1_uri)
    ox_client.write_edge("HAS_ALT_LABEL", c_uri, alt2_uri)

    rows = await gw.run("thalamus.file_bridge_concepts")
    matches = [r for r in rows if r.get("id") == cid]
    assert matches, "thalamus.file_bridge_concepts did not return the seeded Concept"
    row = matches[0]

    assert row.get("name") == "Canonical Name", f"expected pref label text, got {row.get('name')!r}"
    alt_labels = row.get("alt_labels") or ""
    assert "Alias One" in alt_labels and "Alias Two" in alt_labels, (
        f"expected both alt labels in {alt_labels!r}"
    )

    # --- Teeth check: the pre-fix SPARQL (campy:prefLabel/campy:altLabel
    # directly on Concept) never binds against this fixture, because no
    # writer ever asserts those predicates on a Concept.
    old_buggy_sparql = f"""
        PREFIX campy: <{CAMPY_NS}>
        SELECT ?name ?alt_labels WHERE {{
            ?c a campy:Concept ; campy:concept_id "{cid}" .
            OPTIONAL {{ ?c campy:prefLabel ?name }}
            OPTIONAL {{ ?c campy:altLabel ?alt_labels }}
        }}
    """
    old_rows = ox_client._execute_and_collect(old_buggy_sparql)
    assert old_rows and old_rows[0].get("name") is None and old_rows[0].get("alt_labels") is None


@pytest.mark.asyncio
async def test_file_bridge_concept_relationships_resolves_pref_labels(ox_client, gw):
    a_id, b_id = f"c_{uuid.uuid4().hex[:8]}", f"c_{uuid.uuid4().hex[:8]}"
    a_uri = ox_client.write_node("Concept", {"concept_id": a_id, "text_raw": "A", "pathway_strength": 0.9})
    b_uri = ox_client.write_node("Concept", {"concept_id": b_id, "text_raw": "B", "pathway_strength": 0.5})

    a_pref = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Concept A"})
    b_pref = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Concept B"})
    ox_client.write_edge("HAS_PREF_LABEL", a_uri, a_pref)
    ox_client.write_edge("HAS_PREF_LABEL", b_uri, b_pref)

    ox_client.write_edge("REQUIRES", a_uri, b_uri)

    rows = await gw.run("thalamus.file_bridge_concept_relationships")
    matches = [r for r in rows if r.get("from_name") == "Concept A" and r.get("to_name") == "Concept B"]
    assert matches, f"expected a Concept A --[REQUIRES]--> Concept B row, got {rows!r}"
    assert matches[0].get("rel_type") == "REQUIRES"


@pytest.mark.asyncio
async def test_file_bridge_decisions_resolves_pref_label(ox_client, gw):
    did = f"dec_{uuid.uuid4().hex[:8]}"
    d_uri = ox_client.write_node(
        "Decision",
        {"decision_id": did, "text_raw": "Chose SPARQL over Cypher.", "confidence": 0.95, "created_at": _now()},
    )
    pref_uri = ox_client.write_node("Label", {"label_id": f"lbl_{uuid.uuid4().hex[:8]}", "text": "Use SPARQL"})
    ox_client.write_edge("HAS_PREF_LABEL", d_uri, pref_uri)

    rows = await gw.run("thalamus.file_bridge_decisions")
    matches = [r for r in rows if r.get("id") == did]
    assert matches, "thalamus.file_bridge_decisions did not return the seeded Decision"
    assert matches[0].get("title") == "Use SPARQL"


# ---------------------------------------------------------------------------
# 3. capture.get_last_proactive_push_count — schema was missing a real,
#    already-written column.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_proactive_push_count_roundtrip(ox_client, gw):
    sid = f"sess_{uuid.uuid4().hex[:8]}"
    ox_client.write_node("Session", {"session_id": sid})

    # Nothing set yet -> OPTIONAL leaves it unbound, not an error.
    rows = await gw.run("capture.get_last_proactive_push_count", sid=sid)
    assert rows
    assert (rows[0].get("s.last_proactive_push_msg_count")) is None

    await gw.run("capture.set_last_proactive_push_count", sid=sid, count=42)

    rows = await gw.run("capture.get_last_proactive_push_count", sid=sid)
    assert rows, "capture.get_last_proactive_push_count returned no rows after a write"
    value = rows[0].get("s.last_proactive_push_msg_count")
    assert value is not None, "expected a real count back, got None"
    assert int(value) == 42


def test_session_last_proactive_push_msg_count_is_declared_in_schema():
    from campy.brain.hippocampus.schema import get_all_table_properties

    props = get_all_table_properties()
    assert "last_proactive_push_msg_count" in props["Session"], (
        "Session.last_proactive_push_msg_count must be declared (B412: it is real, "
        "live data written by B195's Active Context Push, the schema declaration "
        "was simply missing)"
    )


# ---------------------------------------------------------------------------
# 4. arc.get_action_fact_detail — deleted as unreachable.
# ---------------------------------------------------------------------------


def test_action_fact_detail_removed_from_registry():
    names = {q.name for q in REGISTRY}
    assert "arc.get_action_fact_detail" not in names, (
        "arc.get_action_fact_detail was deleted as unreachable (B412) — "
        "if it's back, either it grew a real caller (update this test and "
        "fix its schema-conformance violations properly) or the deletion "
        "was reverted by mistake"
    )


def test_action_fact_detail_has_no_callers_anywhere_in_repo():
    """Regression guard for the reachability claim the deletion relies on:
    grep the whole tree (source, tests, scripts, docs) for the string. The
    only expected hits are this test file and the backlog card recording
    the deletion."""
    pattern = re.compile(r"get_action_fact_detail")
    hits: list[str] = []
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path == Path(__file__):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            hits.append(str(path.relative_to(REPO_ROOT)))

    allowed = {
        "backlog/B412.md",
        "scripts/schema_conformance_baseline.json",
        # The deletion's own explanatory comment, left in place of the
        # removed NamedQuery in arc.py.
        "campy/brain/hippocampus/graph/queries/arc.py",
    }
    unexpected = [h for h in hits if h not in allowed]
    assert not unexpected, (
        f"arc.get_action_fact_detail is referenced outside the expected historical "
        f"record: {unexpected} — it may have grown a real caller since B412 deleted it"
    )
