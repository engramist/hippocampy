"""B472 Phase 3a: the Observation table, its edges and the grounded write API.

Phase 3a adds storage and a write API only: no producer, no worker, no
retrieval use. These tests pin:

- the schema checklist (table, edges, provenance, classification, vector spec,
  config) so a later change cannot drop one silently;
- the grounding rule: no verbatim quote, no row;
- idempotency: a repeated claim adds evidence, never a second row;
- the same behaviour on both backends (the Oxigraph runtime and the Kuzu test
  client), through the GraphGateway only.
"""

from __future__ import annotations

import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyoxigraph as ox
import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import (
    EDGE_REIFICATION,
    NODE_PRIMARY_KEYS,
    OxigraphClient,
    classify_edge,
    mint_uri,
)
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.observations import OBSERVATION_QUERIES
from campy.brain.hippocampus.graph.queries.vector_indexing import VECTOR_INDEX_SPECS
from campy.brain.hippocampus.schema import (
    CONTENT_HASH_TABLES,
    NODE_TABLES,
    PROVENANCE_TABLES,
    REL_TABLES,
    get_all_table_properties,
    init_schema,
)
from campy.brain.hippocampus.table_registry import get_table
from tests.kuzu_test_client import KUZU_AVAILABLE, KuzuClient

EMB = [0.05] * 384
SEED = Path(__file__).resolve().parent.parent / "campy" / "data" / "GistSeedExamples.md"
MSG_TEXT = "My sister Dana is a nurse.  She said “I went to the Denver support group on 7 May 2023”."
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
BACKENDS = ["oxigraph"] + (["kuzu"] if KUZU_AVAILABLE else [])


# --- fixtures -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def _kuzu_template(tmp_path_factory):
    """One initialised Kuzu store, copied per test (init_schema is slow)."""
    if not KUZU_AVAILABLE:
        return None
    path = tmp_path_factory.mktemp("kuzu_template") / "template.db"
    client = KuzuClient(db_path=str(path))
    init_schema(client, seed_examples_path=str(SEED),
                embedding_model="sentence-transformers/all-MiniLM-L6-v2")
    client.close()
    return path


@pytest.fixture(params=BACKENDS)
def db(request, tmp_path, _kuzu_template):
    if request.param == "oxigraph":
        yield OxigraphClient(tmp_path / "b472p3a.db")
        return
    path = tmp_path / "kuzu.db"
    if _kuzu_template.is_dir():
        shutil.copytree(_kuzu_template, path)
    else:
        shutil.copy(_kuzu_template, path)
        for extra in _kuzu_template.parent.glob(_kuzu_template.name + ".*"):
            shutil.copy(extra, tmp_path / extra.name.replace("template.db", "kuzu.db"))
    client = KuzuClient(db_path=str(path))
    yield client
    client.close()


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _message(gw, mid="m1", text=MSG_TEXT, role="user", speaker="Melanie", archived=False):
    await gw.run(
        "capture.create_message", message_id=mid, text_raw=text, embedding=None,
        embedding_model="m", embedding_dim=384, role=role, byte_end=len(text),
        created_at="2023-05-07T12:00:00+00:00",
    )
    if speaker:
        await gw.run("capture.set_message_source", message_id=mid, speaker=speaker,
                     occurred_at="2023-05-07T12:00:00+00:00")
    if archived:
        await gw.run("capture.archive_earlier_message_version", marker=text)
    return mid


async def _concept(gw, cid="c-dana", text="Dana"):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=EMB,
                 gist="Agent", stype="Person", now=T0)
    return cid


def _utc(dt):
    """Kuzu returns naive UTC timestamps, Oxigraph aware ones."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _draft(**kw) -> obs.ObservationDraft:
    base = dict(
        evidence_ref="m1", evidence_text="My sister Dana is a nurse",
        subject_text="Dana", predicate="has_attribute", object_text="job: nurse",
        extraction_method="pattern", confidence=0.8, rule_version="pattern-1",
    )
    base.update(kw)
    return obs.ObservationDraft(**base)


# --- the schema checklist ------------------------------------------------------------

def test_observation_is_a_provenance_table_with_every_provenance_column():
    assert "Observation" in PROVENANCE_TABLES and "Observation" in CONTENT_HASH_TABLES
    cols = get_all_table_properties()["Observation"]
    for c in ("observation_id", "subject_text", "subject_id", "predicate", "object_text",
              "object_id", "event_text", "time_text", "time_start", "time_end",
              "time_precision", "speaker", "polarity", "confidence", "confidence_low",
              "extraction_method", "rule_version", "evidence_start", "evidence_end",
              "evidence_text", "text_raw", "embedding", "archived", "created_at",
              "source", "source_version", "observed_at", "evidence_ref", "superseded_by",
              "superseded_at", "supersession_reason", "authority", "content_hash"):
        assert c in cols, c
    assert NODE_PRIMARY_KEYS["Observation"] == "observation_id"
    assert "PRIMARY KEY (observation_id)" in NODE_TABLES["Observation"]


def test_edges_are_declared_and_classified_plain():
    ddl = {d.split("IF NOT EXISTS ")[1].split(" ")[0]: d for d in REL_TABLES if "IF NOT EXISTS" in d}
    assert "FROM Observation TO Concept" in ddl["OBSERVATION_ABOUT"]
    assert "FROM Observation TO Message" in ddl["EVIDENCED_BY"]
    # property-free DDL is what makes "plain" correct (a previous card got this wrong)
    props = get_all_table_properties()
    assert props["OBSERVATION_ABOUT"] == set() and props["EVIDENCED_BY"] == set()
    assert classify_edge("OBSERVATION_ABOUT") == "plain"
    assert classify_edge("EVIDENCED_BY") == "plain"
    assert Counter(EDGE_REIFICATION.values())["plain"] == 54
    assert "FROM Observation TO Observation" in ddl["DEPRECATED_BY"]


def test_registry_vector_spec_and_queries_line_up():
    info = get_table("Observation")
    assert info.has_embedding and info.vector_index == "observation_emb_idx"
    spec = VECTOR_INDEX_SPECS["observations.create_observation"]
    assert (spec.table, spec.pk_col, spec.text_param) == ("Observation", "observation_id", "text_raw")
    assert REGISTRY.get("observations.create_observation").vector_index == spec
    # a new module of new queries: nothing was added to an existing query
    assert {q.name for q in OBSERVATION_QUERIES} == {
        n for n in (q.name for q in OBSERVATION_QUERIES) if n.startswith("observations.")}


@pytest.mark.parametrize("query", OBSERVATION_QUERIES, ids=lambda q: q.name)
def test_every_observation_query_has_sparql_that_parses(query):
    assert query.sparql, f"{query.name} needs a sparql= form"
    store = ox.Store()
    from campy.brain.hippocampus.graph.oxigraph_client import _bind_params_to_sparql
    bound = _bind_params_to_sparql(query.sparql, {p: "x" for p in query.params})
    (store.update if query.mutating else store.query)(bound)


def test_observations_ship_disabled():
    assert _DEFAULT_CONFIG["observations"]["enabled"] is False
    assert obs.observations_enabled({}) is False
    assert obs.observations_enabled({"observations": {"enabled": True}}) is True
    import tomllib
    cfg = tomllib.loads((Path(__file__).resolve().parent.parent / "campy" / "data" / "config" / "campy.toml").read_text())
    assert cfg["observations"]["enabled"] is False


# --- grounding ----------------------------------------------------------------------

@pytest.mark.parametrize("quote, expected", [
    ("My sister Dana is a nurse", (0, 25)),
    ("Dana  is  a nurse", (10, 25)),                       # whitespace runs are collapsed
    ("nurse. She said", (20, 36)),                         # spans the double space
    ("my sister dana is a nurse", None),                   # case differs
    ("Dana is a doctor", None),
    ("", None),
    ("   ", None),
])
def test_locate_quote(quote, expected):
    got = obs.locate_quote(MSG_TEXT, quote)
    assert got == expected
    if got:
        assert " ".join(MSG_TEXT[got[0]:got[1]].split()) == " ".join(quote.split())


def test_locate_quote_unifies_curly_and_straight_quotes():
    got = obs.locate_quote(MSG_TEXT, 'She said "I went to the Denver support group on 7 May 2023"')
    assert MSG_TEXT[got[0]:got[1]] == 'She said “I went to the Denver support group on 7 May 2023”'


def test_locate_quote_survives_whitespace_runs_and_returns_original_offsets():
    text = "I  live\n in   Denver now"
    s, e = obs.locate_quote(text, "I live in Denver")
    assert text[s:e] == "I  live\n in   Denver"


@pytest.mark.asyncio
async def test_a_grounded_draft_is_written_with_recomputed_offsets_and_provenance(gw, db):
    await _message(gw)
    cid = await _concept(gw)
    res = await obs.record_observation(db, _draft(
        evidence_text="my sister dana is a nurse".replace("my", "My").replace("dana", "Dana"),
        subject_id=cid, time_text="7 May 2023", time_start=T0, time_end=T0, time_precision="day",
    ))
    assert res.status == "created" and res.ok
    row = await obs.get_observation(db, res.observation_id)
    assert row["evidence_text"] == MSG_TEXT[row["evidence_start"]:row["evidence_end"]] == "My sister Dana is a nurse"
    assert (row["evidence_start"], row["evidence_end"]) == (0, 25)
    assert (row["subject_text"], row["subject_id"], row["predicate"], row["object_text"]) == (
        "Dana", cid, "has_attribute", "job: nurse")
    assert row["polarity"] == "asserted" and row["time_text"] == "7 May 2023"
    assert row["time_precision"] == "day" and _utc(row["time_start"]) == T0
    assert row["confidence"] == pytest.approx(0.8) and row["confidence_low"] is True
    assert row["speaker"] == "Melanie"                      # defaulted from the Message
    assert row["text_raw"] == "Dana - has_attribute - job: nurse (7 May 2023)"
    # provenance (B312/B313/B320)
    assert row["source"] == "loop:observation:pattern" and row["source_version"] == "pattern-1"
    assert row["evidence_ref"] == "m1" and row["authority"] == "earned"
    assert _utc(row["observed_at"]) == T0                          # the turn's occurred_at
    assert row["content_hash"] and len(row["content_hash"]) == 64
    assert row["created_at"] and row["archived"] is False
    # edges
    assert await obs.evidence_message_ids(db, res.observation_id) == ["m1"]
    assert [r["observation_id"] for r in await obs.observations_for_message(db, "m1")] == [res.observation_id]
    assert [r["observation_id"] for r in await obs.observations_for_concept(db, cid)] == [res.observation_id]


@pytest.mark.asyncio
async def test_confidence_above_the_ceiling_is_not_low(gw, db):
    await _message(gw)
    res = await obs.record_observation(db, _draft(confidence=0.95))
    assert (await obs.get_observation(db, res.observation_id))["confidence_low"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change, reason", [
    (dict(evidence_text="My sister Dana is a doctor"), "quote_not_found"),
    (dict(predicate="invented"), "bad_predicate"),
    (dict(polarity="maybe"), "bad_polarity"),
    (dict(confidence=0.59), "low_confidence"),
    (dict(extraction_method="deterministic"), "bad_extraction_method"),
    (dict(time_precision="decade"), "bad_time_precision"),
    (dict(object_text="  "), "empty_object"),
    (dict(object_text="x" * 201), "object_too_long"),
    (dict(evidence_text="y" * 401), "evidence_too_long"),
    (dict(time_start=T0, time_end=datetime(2020, 1, 1, tzinfo=timezone.utc)), "bad_time_range"),
    (dict(embedding=[0.1, 0.2]), "bad_embedding"),
    (dict(subject_text="Zed"), "subject_not_grounded"),
    (dict(subject_id="no-such-concept"), "subject_concept_missing"),
    (dict(object_id="no-such-concept"), "object_concept_missing"),
    (dict(evidence_ref="nope"), "evidence_message_missing"),
])
async def test_rejections_write_nothing(gw, db, change, reason):
    await _message(gw)
    await _concept(gw, "c-other", "Someone Else")   # a Concept exists, just not the one named
    res = await obs.record_observation(db, _draft(**change))
    assert res.status == "rejected" and not res.ok and res.reason == reason
    assert reason in obs.REJECT_REASONS
    assert await obs.observations_for_message(db, "m1") == []


@pytest.mark.asyncio
async def test_first_person_subject_is_grounded_on_a_user_turn_only(gw, db):
    await _message(gw, text="I adopted a puppy last week.")
    ok = await obs.record_observation(db, _draft(
        evidence_text="adopted a puppy last week", subject_text="I", predicate="did",
        object_text="adopted a puppy", time_text="last week"))
    assert ok.status == "created"
    # "the user" needs a first-person cue in the quote
    ok2 = await obs.record_observation(db, _draft(
        evidence_text="I adopted a puppy", subject_text="the user", predicate="owns", object_text="a puppy"))
    assert ok2.status == "created"
    bad = await obs.record_observation(db, _draft(
        evidence_text="a puppy last week", subject_text="the user", predicate="owns", object_text="a puppy"))
    assert bad.reason == "subject_not_grounded"


@pytest.mark.asyncio
async def test_assistant_turns_are_not_evidence(gw, db):
    await _message(gw, mid="a1", text="Dana is a nurse, you said.", role="assistant", speaker=None)
    res = await obs.record_observation(db, _draft(evidence_ref="a1", evidence_text="Dana is a nurse"))
    assert res.reason == "evidence_not_user_turn"
    # a caller can widen the set explicitly
    res = await obs.record_observation(db, _draft(evidence_ref="a1", evidence_text="Dana is a nurse"),
                                       allowed_roles=frozenset({"user", "assistant"}))
    assert res.status == "created"


@pytest.mark.asyncio
async def test_an_archived_message_is_not_evidence(gw, db):
    await _message(gw, archived=True)
    res = await obs.record_observation(db, _draft())
    assert res.reason == "evidence_message_archived"


# --- idempotency ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_same_claim_twice_from_one_message_is_one_row(gw, db):
    await _message(gw)
    cid = await _concept(gw)
    first = await obs.record_observation(db, _draft(subject_id=cid))
    again = await obs.record_observation(db, _draft(subject_id=cid))
    assert (first.status, again.status) == ("created", "duplicate")
    assert again.observation_id == first.observation_id
    assert len(await obs.observations_for_message(db, "m1")) == 1
    assert await obs.evidence_message_ids(db, first.observation_id) == ["m1"]
    assert len(await obs.observations_for_concept(db, cid)) == 1


@pytest.mark.asyncio
async def test_a_second_message_adds_evidence_not_a_second_row(gw, db):
    await _message(gw, mid="m1")
    await _message(gw, mid="m2", text="Remember, Dana is a nurse. Really.")
    first = await obs.record_observation(db, _draft(subject_text="  dana ", object_text="Job: Nurse"))
    second = await obs.record_observation(db, _draft(
        evidence_ref="m2", evidence_text="Dana is a nurse", object_text="job: nurse"))
    assert second.status == "duplicate" and second.observation_id == first.observation_id
    assert sorted(await obs.evidence_message_ids(db, first.observation_id)) == ["m1", "m2"]
    assert [r["observation_id"] for r in await obs.observations_for_message(db, "m2")] == [first.observation_id]
    # the row keeps its first evidence span
    assert (await obs.get_observation(db, first.observation_id))["evidence_ref"] == "m1"


@pytest.mark.asyncio
async def test_a_negated_claim_is_a_different_claim(gw, db):
    await _message(gw, text="I love hiking. I don't love hiking in July.")
    a = await obs.record_observation(db, _draft(
        evidence_text="I love hiking", subject_text="I", predicate="prefers", object_text="hiking"))
    b = await obs.record_observation(db, _draft(
        evidence_text="I don't love hiking", subject_text="I", predicate="prefers",
        object_text="hiking", polarity="negated"))
    assert (a.status, b.status) == ("created", "created") and a.observation_id != b.observation_id
    assert len(await obs.observations_for_message(db, "m1")) == 2


@pytest.mark.asyncio
async def test_a_different_object_or_time_is_a_different_claim(gw, db):
    await _message(gw)
    a = await obs.record_observation(db, _draft())
    b = await obs.record_observation(db, _draft(object_text="job: teacher"))
    c = await obs.record_observation(db, _draft(time_text="7 May 2023"))
    assert len({a.observation_id, b.observation_id, c.observation_id}) == 3


@pytest.mark.asyncio
async def test_write_stats_count_outcomes_and_reasons(gw, db):
    await _message(gw)
    stats = obs.WriteStats()
    for d in (_draft(), _draft(), _draft(evidence_text="nowhere"), _draft(confidence=0.1)):
        stats.record(await obs.record_observation(db, d))
    assert (stats.created, stats.duplicate) == (1, 1)
    assert stats.rejected == {"quote_not_found": 1, "low_confidence": 1}


@pytest.mark.asyncio
async def test_a_retry_after_a_crash_between_node_and_edge_heals(gw, db):
    """Simulate the node written but its EVIDENCED_BY edge lost: the retry finds the
    node by content hash and adds the missing edge."""
    await _message(gw)
    draft = _draft()
    key = obs.observation_content_hash(draft)
    await gw.run(
        "observations.create_observation", observation_id="o-orphan", subject_text="Dana",
        subject_id=None, predicate="has_attribute", object_text="job: nurse", object_id=None,
        event_text=None, time_text=None, time_start=None, time_end=None, time_precision=None,
        speaker=None, polarity="asserted", confidence=0.8, confidence_low=True,
        extraction_method="pattern", rule_version="pattern-1", evidence_start=0, evidence_end=25,
        evidence_text="My sister Dana is a nurse", text_raw="t", embedding=None,
        embedding_model=None, embedding_dim=None, source="s", observed_at=None,
        evidence_ref="m1", content_hash=key, now=T0)
    assert await obs.observations_for_message(db, "m1") == []
    res = await obs.record_observation(db, draft)
    assert (res.status, res.observation_id) == ("duplicate", "o-orphan")
    assert [r["observation_id"] for r in await obs.observations_for_message(db, "m1")] == ["o-orphan"]


# --- embedding ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_supplied_embedding_is_stored_and_indexed(gw, db):
    await _message(gw)
    res = await obs.record_observation(db, _draft(embedding=EMB))
    assert res.status == "created"
    row = await obs.get_observation(db, res.observation_id)
    assert row["text_raw"].startswith("Dana - has_attribute")
    if isinstance(db, OxigraphClient):
        uri = mint_uri("Observation", res.observation_id)
        assert db.vector_store.get_vector(uri) is not None
        assert db.vector_store.search_text("nurse", 5)


@pytest.mark.asyncio
async def test_no_embedding_means_nothing_indexed(gw, db):
    await _message(gw)
    res = await obs.record_observation(db, _draft())
    if isinstance(db, OxigraphClient):
        assert db.vector_store.get_vector(mint_uri("Observation", res.observation_id)) is None


# --- migration ----------------------------------------------------------------------------

@pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")
def test_an_old_kuzu_store_gains_the_table_and_edges_with_no_data():
    """A store created before Phase 3a (no Observation table; DEPRECATED_BY without the
    Observation pair) is brought up to date by init_schema, empty."""
    with tempfile.TemporaryDirectory() as d:
        client = KuzuClient(db_path=str(Path(d) / "old.db"))
        init_schema(client, seed_examples_path=str(SEED), embedding_model="sentence-transformers/all-MiniLM-L6-v2")
        # make it look pre-3a
        for t in ("EVIDENCED_BY", "OBSERVATION_ABOUT", "DEPRECATED_BY"):
            client.execute(f"DROP TABLE {t}")
        client.execute("CALL DROP_VECTOR_INDEX('Observation', 'observation_emb_idx')")
        client.execute("DROP TABLE Observation")
        old_pairs = ", ".join(f"FROM {t} TO {t}" for t in PROVENANCE_TABLES if t != "Observation")
        client.execute(f"CREATE REL TABLE DEPRECATED_BY ({old_pairs})")
        with pytest.raises(Exception):
            client.execute("MATCH (o:Observation) RETURN count(o)")

        init_schema(client, seed_examples_path=str(SEED), embedding_model="sentence-transformers/all-MiniLM-L6-v2")

        res = client.execute("MATCH (o:Observation) RETURN count(o)")
        assert res.get_next()[0] == 0
        client.execute("MATCH (o:Observation)-[:EVIDENCED_BY]->(m:Message) RETURN count(o)")
        client.execute("MATCH (o:Observation)-[:OBSERVATION_ABOUT]->(c:Concept) RETURN count(o)")
        # the widened DEPRECATED_BY accepts the pair
        client.execute("MATCH (a:Observation)-[:DEPRECATED_BY]->(b:Observation) RETURN count(a)")
        # re-running is a no-op
        init_schema(client, seed_examples_path=str(SEED), embedding_model="sentence-transformers/all-MiniLM-L6-v2")
        client.close()


@pytest.mark.asyncio
async def test_an_existing_oxigraph_store_needs_no_migration(tmp_path):
    """Oxigraph is schema-less: a store written before Phase 3a reads back no
    Observations and accepts them."""
    path = tmp_path / "old_ox.db"
    first = OxigraphClient(path)
    await _message(GraphGateway(first, REGISTRY))
    del first
    reopened = OxigraphClient(path)
    assert await obs.observations_for_message(reopened, "m1") == []
    assert (await obs.record_observation(reopened, _draft())).status == "created"
