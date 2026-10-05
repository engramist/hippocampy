"""B467: archive what benchmark sessions wrote into a personal store.

Non-isolated campy-benchmarks runs wrote ~2,000 fixture turns into a user's
~/.campy, and consolidation turned them into Concepts and CHOSEN_OVER edges
that `ask` read as the user's own decisions. `campy graph purge-sessions
--prefix ...` archives the Messages those sessions sent (and word-for-word
session-less copies of them), the Decisions/Constraints/Lessons only they
produced, and the Concepts only they name. The graph has no Concept ->
Message link, so "only they name" is whole-word mention in the remaining
Messages.

Archived Concepts must also stay out of the bundle's graph traversal, which
filtered flagged neighbours but not archived ones.

Real Oxigraph store.
"""

from __future__ import annotations

import asyncio

import pytest

from tests._spacy import SPACY_AVAILABLE

NOW = "2026-10-01T12:00:00+00:00"

SESSIONS = ["locomo_db_s1", "locomo_auth_s2", "arc_game_a", "real-7f3c", "arc-arc_eval_001-ab12"]

# (message_id, session or None, role, text)
MESSAGES = [
    ("b1", "locomo_db_s1", "user", "We migrated from PostgreSQL 14 to PostgreSQL 16 on Redis hosts."),
    ("b2", "locomo_db_s1", "assistant", "Noted: PostgreSQL 16 is the primary database."),
    ("b3", "locomo_auth_s2", "user", "Final decision: Zipkin has been replaced by OpenTelemetry."),
    ("b4", "arc_game_a", "user", "Game_A rule: blue pixels move right."),
    ("r1", "real-7f3c", "user", "Our Kuzu migration still needs PostgreSQL for the old reports."),
    ("r2", "real-7f3c", "assistant", "OpenTelemetry is configured in the collector."),
    ("r3", "arc-arc_eval_001-ab12", "user", "[STEP RESPONSE] step=18, action=ACTION4"),
    # session-less: a copy of b1 (spacing and case differ), and a real note
    ("c1", None, "user", "we migrated from  PostgreSQL 14 to PostgreSQL 16 on Redis hosts."),
    ("c2", None, "assistant", "Earlier note about Grafana dashboards."),
]

CONCEPTS = {
    "PostgreSQL 16": "archive",       # named by b1, b2 and the copy c1 only
    "PostgreSQL 14": "archive",
    "Redis": "archive",               # b1 and its copy c1: copies don't keep it
    "Zipkin": "archive",
    "blue pixels": "archive",         # arc_game_ fixture
    "PostgreSQL": "keep",             # also named by real r1 (whole word)
    "OpenTelemetry": "keep",          # also named by real r2
    "Kuzu": "untouched",              # real only
    "Grafana": "untouched",           # real session-less note only
    "Design Doc 7": "untouched",      # named by no message (from a document)
    "ACTION4": "untouched",           # arc-arc_eval_ is not a purged prefix
}

# (head, rel, tail)
EDGES = [
    ("PostgreSQL 14", "CHOSEN_OVER", "PostgreSQL 16"),   # both ends archived
    ("Kuzu", "REQUIRES", "PostgreSQL 16"),               # one end archived
    ("Kuzu", "ENABLES", "Grafana"),                      # neither
    ("Grafana", "PART_OF", "PostgreSQL 14"),             # one end (2-hop from Kuzu)
]

PREFIXES = ["locomo_", "msc_", "memgym_", "arc_game_"]


def _cid(text: str) -> str:
    return "c_" + text.lower().replace(" ", "_")


def _build_store(path):
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.graph.vector_store import mint_uri

    client = OxigraphClient(str(path))
    for sid in SESSIONS:
        client.write_node("Session", {"session_id": sid, "started_at": NOW})
    for mid, sid, role, text in MESSAGES:
        client.write_node("Message", {"message_id": mid, "text_raw": text, "role": role,
                                      "created_at": NOW, "archived": False})
        if sid:
            client.write_edge("SENT_IN", mint_uri("Message", mid), mint_uri("Session", sid))
    for text in CONCEPTS:
        client.write_node("Concept", {"concept_id": _cid(text), "text_raw": text, "archived": False,
                                      "pathway_strength": 0.7, "confidence": 0.8, "created_at": NOW})
    for head, rel, tail in EDGES:
        assert client.upsert_semantic_relation(
            rel, mint_uri("Concept", _cid(head)), mint_uri("Concept", _cid(tail)), 0.75, "LLM", NOW)
    # products: d1 only from a benchmark message, d2 from a benchmark AND a
    # real one, k1 a benchmark Constraint, l1 a benchmark Lesson, l2 a real one
    for table, key, nid in (("Decision", "decision_id", "d1"), ("Decision", "decision_id", "d2"),
                            ("Constraint", "constraint_id", "k1"),
                            ("Lesson", "lesson_id", "l1"), ("Lesson", "lesson_id", "l2")):
        client.write_node(table, {key: nid, "text_raw": f"{table} {nid}", "created_at": NOW, "archived": False})
    for mid, rel, table, nid in (("b1", "ESTABLISHED", "Decision", "d1"), ("b1", "ESTABLISHED", "Decision", "d2"),
                                 ("r1", "ESTABLISHED", "Decision", "d2"), ("b3", "ESTABLISHED", "Constraint", "k1"),
                                 ("b3", "CONTAINS_LESSON", "Lesson", "l1"), ("r1", "CONTAINS_LESSON", "Lesson", "l2")):
        client.write_edge(rel, mint_uri("Message", mid), mint_uri(table, nid))
    return client


def _archived(client, table: str, key: str) -> set[str]:
    rows = client.store.query(f"""
        PREFIX campy: <https://campy.dev/ns#>
        SELECT ?id WHERE {{ ?n a campy:{table} ; campy:{key} ?id ; campy:archived true }}""")
    return {r["id"].value for r in rows}


@pytest.fixture
def client(tmp_path):
    return _build_store(tmp_path / "brain.db")


def _purge(client, apply):
    from campy.cli.graph_repair import purge_sessions

    return asyncio.run(purge_sessions(client, PREFIXES, apply=apply))


def test_dry_run_reports_exactly_what_the_benchmark_sessions_wrote(client):
    plan = _purge(client, apply=False)

    assert {p: sorted(s) for p, s in plan.sessions.items()} == {
        "locomo_": ["locomo_auth_s2", "locomo_db_s1"], "msc_": [], "memgym_": [], "arc_game_": ["arc_game_a"]}
    assert set(plan.messages) == {"b1", "b2", "b3", "b4", "c1"}
    assert plan.session_less == ["c1"]
    assert plan.products == {"Decision": ["d1"], "Constraint": ["k1"], "Lesson": ["l1"]}
    assert set(plan.concepts.values()) == {t for t, v in CONCEPTS.items() if v == "archive"}
    assert plan.kept_concepts == 2  # PostgreSQL, OpenTelemetry
    assert plan.edges == {"both": 1, "one": 2}
    # nothing written
    assert not _archived(client, "Message", "message_id")
    assert not _archived(client, "Concept", "concept_id")


def test_apply_archives_only_benchmark_data_and_is_idempotent(client):
    _purge(client, apply=True)

    assert _archived(client, "Message", "message_id") == {"b1", "b2", "b3", "b4", "c1"}
    assert _archived(client, "Decision", "decision_id") == {"d1"}  # d2 also came from a real message
    assert _archived(client, "Constraint", "constraint_id") == {"k1"}
    assert _archived(client, "Lesson", "lesson_id") == {"l1"}
    assert _archived(client, "Concept", "concept_id") == {
        _cid(t) for t, v in CONCEPTS.items() if v == "archive"}

    again = _purge(client, apply=False)
    assert not again.messages and not again.concepts
    assert again.products == {"Decision": [], "Constraint": [], "Lesson": []}


def test_graph_traversal_skips_archived_concepts(client):
    """The bundle's 1- and 2-hop expansion filtered flagged neighbours but not
    archived ones: an archived fixture Concept still reached the bundle
    through a real one ("Kuzu REQUIRES PostgreSQL 16")."""
    from campy.brain.hippocampus.graph.gateway import get_gateway

    _purge(client, apply=True)
    gw = get_gateway(client)
    for suffix in ("", "_flagged"):
        one = asyncio.run(gw.run(f"thalamus.bundle_graph_one_hop{suffix}", aid=_cid("Kuzu")))
        names = {(list(r.values()) if isinstance(r, dict) else r)[2] for r in one}
        assert names == {"Grafana"}, (suffix, names)
        two = asyncio.run(gw.run(f"thalamus.bundle_graph_two_hop{suffix}", aid=_cid("Kuzu")))
        names = {(list(r.values()) if isinstance(r, dict) else r)[4] for r in two}
        # Kuzu -> Grafana -> PostgreSQL 14 and Kuzu -> PostgreSQL 16 -> ... both end or pass at an archived Concept
        assert names == set(), (suffix, names)


def test_cli_needs_a_prefix_and_refuses_an_empty_one(tmp_path):
    from typer.testing import CliRunner

    from campy.cli.graph_repair import graph_app

    _build_store(tmp_path / "brain.db").close()
    runner = CliRunner()
    res = runner.invoke(graph_app, ["purge-sessions", "--db-path", str(tmp_path / "brain.db")])
    assert res.exit_code == 1 and "--prefix or --session" in res.output
    res = runner.invoke(graph_app, ["purge-sessions", "--prefix", "", "--db-path", str(tmp_path / "brain.db")])
    assert res.exit_code == 1 and "every session" in res.output
    res = runner.invoke(graph_app, ["purge-sessions", "--prefix", "locomo_", "--db-path", str(tmp_path / "brain.db")])
    assert res.exit_code == 0 and "Dry run" in res.output, res.output


@pytest.mark.skipif(not SPACY_AVAILABLE, reason="needs spaCy with en_core_web_md")
def test_supersession_repair_ignores_archived_data(client):
    """After the purge, B465's repair neither lists edges between archived
    Concepts nor reads archived Messages as the user's statements: the
    fixture's "PostgreSQL 14 CHOSEN_OVER PostgreSQL 16" is inverted before
    and gone after."""
    import spacy

    from campy.cli.graph_repair import find_supersession_verdicts

    nlp = spacy.load("en_core_web_md")
    before = asyncio.run(find_supersession_verdicts(client, nlp=nlp))
    assert [v.label for v in before if v.verdict == "inverted"] == ["PostgreSQL 14 -CHOSEN_OVER-> PostgreSQL 16"]
    _purge(client, apply=True)
    assert asyncio.run(find_supersession_verdicts(client, nlp=nlp)) == []


def _index_everything(client):
    """Give every Message and Concept a vector and a full-text row, as the
    daemon does."""
    from campy.brain.hippocampus.graph.vector_store import mint_uri

    vs = client.vector_store
    dim = vs.dim
    for i, (mid, _sid, _role, text) in enumerate(MESSAGES):
        uri = mint_uri("Message", mid)
        vs.upsert_vector(uri, [float(i + 1)] + [0.0] * (dim - 1))
        vs.index_text(uri, text)
    for i, text in enumerate(CONCEPTS):
        uri = mint_uri("Concept", _cid(text))
        vs.upsert_vector(uri, [0.0, float(i + 1)] + [0.0] * (dim - 2))
        vs.index_text(uri, text)


def test_apply_drops_the_archived_nodes_vector_and_text_rows(client):
    """Archived rows left in vectors.db would still take places in a search's
    top k (results are filtered by `archived` only after hydration) and count
    in the conversation stage's word frequencies."""
    from campy.brain.hippocampus.graph.vector_store import mint_uri

    _index_everything(client)
    vs = client.vector_store
    _purge(client, apply=True)

    for mid in ("b1", "b2", "b3", "b4", "c1"):
        assert vs.get_vector(mint_uri("Message", mid)) is None, mid
    for mid in ("r1", "r2", "r3", "c2"):
        assert vs.get_vector(mint_uri("Message", mid)) is not None, mid
    for text, fate in CONCEPTS.items():
        present = vs.get_vector(mint_uri("Concept", _cid(text))) is not None
        assert present == (fate != "archive"), text
    lexical = {u for u, _ in vs.search_text("PostgreSQL", k=50)}
    assert mint_uri("Message", "r1") in lexical
    assert not lexical & {mint_uri("Message", m) for m in ("b1", "b2", "c1")}


def test_session_option_matches_exactly(client):
    """--session x archives session "x" only; a prefix "x" would also take
    "x-other". One-off ids (a session literally named "x") need it."""
    from campy.brain.hippocampus.graph.vector_store import mint_uri

    for sid, mid, text in (("x", "x1", "hello from Zorblax"), ("x-other", "x2", "hello from Quuxly")):
        client.write_node("Session", {"session_id": sid, "started_at": NOW})
        client.write_node("Message", {"message_id": mid, "text_raw": text, "role": "user",
                                      "created_at": NOW, "archived": False})
        client.write_edge("SENT_IN", mint_uri("Message", mid), mint_uri("Session", sid))
    from campy.cli.graph_repair import purge_sessions

    plan = asyncio.run(purge_sessions(client, [], apply=False, sessions=["x"]))
    assert set(plan.messages) == {"x1"}
    assert plan.sessions == {"x": ["x"]}
    by_prefix = asyncio.run(purge_sessions(client, ["x"], apply=False))
    assert set(by_prefix.messages) == {"x1", "x2"}
