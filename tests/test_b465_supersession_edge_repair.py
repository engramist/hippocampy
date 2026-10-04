"""B465: repair supersession edges written backwards before B460.

Before B460, consolidation's Step 3b LLM wrote "A CHOSEN_OVER B" with the
RETIRED value as A -- in a real-model LoCoMo store 8 of 11 such edges were
inverted ("PostgreSQL 14 CHOSEN_OVER PostgreSQL 16" from "We have completely
migrated from PostgreSQL 14 to PostgreSQL 16"). B460 fixed extraction going
forward; existing stores keep the inverted edges. `campy graph
repair-supersession-edges` re-reads the user's own statements with B460's
Step 1b and fixes only the edges a user message contradicts.

Real Oxigraph store, real spaCy (en_core_web_md).
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from tests._spacy import SPACY_AVAILABLE

needs_spacy = pytest.mark.skipif(not SPACY_AVAILABLE, reason="needs spaCy with en_core_web_md")

NOW = "2026-10-01T12:00:00+00:00"

CONCEPTS = [
    "PostgreSQL 14", "PostgreSQL 16", "PostgreSQL", "Primary database",
    "Zipkin", "OpenTelemetry OTel", "ActiveMQ", "Apache Kafka", "HS256", "RS256",
    "TLS 1.2", "TLS 1.3", "Zstandard", "gzip", "Redis", "Memcached", "Vue 2", "Vue 3",
]

# (role, text) -- the user's own statements, plus one assistant turn.
MESSAGES = [
    ("user", "CRITICAL UPDATE: We have completely migrated from PostgreSQL 14 to PostgreSQL 16."),
    ("user", "Final decision: Zipkin has been replaced by OpenTelemetry (OTel) for tracing."),
    ("user", "Final decision: ActiveMQ has been replaced by Apache Kafka."),
    ("user", "Final decision: HS256 has been replaced by RS256."),
    ("user", "We switched from TLS 1.2 to TLS 1.3 last week."),
    ("user", "PostgreSQL is our primary database."),
    ("assistant", "Redis has been replaced by Memcached."),  # not the user's statement
    ("user", "We migrated from Vue 2 to Vue 3."),
    ("user", "We migrated from Vue 3 to Vue 2 after the regression."),
]

# (head, rel, tail) as a pre-B460 store holds them
EDGES = [
    ("PostgreSQL 14", "CHOSEN_OVER", "PostgreSQL 16"),       # inverted: "from 14 to 16"
    ("Zipkin", "CHOSEN_OVER", "OpenTelemetry OTel"),         # inverted: passive; concept contains span
    ("ActiveMQ", "REPLACES", "Apache Kafka"),                # inverted, REPLACES
    ("TLS 1.2", "CHOSEN_OVER", "TLS 1.3"),                   # inverted, beside the right edge below
    ("TLS 1.3", "REPLACES", "TLS 1.2"),                      # right
    ("RS256", "CHOSEN_OVER", "HS256"),                       # right
    ("PostgreSQL", "CHOSEN_OVER", "Primary database"),       # nonsense: no supersession stated
    ("PostgreSQL", "CHOSEN_OVER", "PostgreSQL 16"),          # "PostgreSQL" names both sides
    ("Zstandard", "CHOSEN_OVER", "gzip"),                    # no message at all
    ("Redis", "CHOSEN_OVER", "Memcached"),                   # only an assistant said otherwise
    ("Vue 2", "CHOSEN_OVER", "Vue 3"),                       # user said both: conflicting
]

INVERTED = {
    "PostgreSQL 14 -CHOSEN_OVER-> PostgreSQL 16",
    "Zipkin -CHOSEN_OVER-> OpenTelemetry OTel",
    "ActiveMQ -REPLACES-> Apache Kafka",
    "TLS 1.2 -CHOSEN_OVER-> TLS 1.3",
}


def _cid(text: str) -> str:
    return "c_" + text.lower().replace(" ", "_").replace(".", "_")


def _build_store(path):
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.graph.vector_store import mint_uri

    client = OxigraphClient(str(path))
    for text in CONCEPTS:
        client.write_node("Concept", {
            "concept_id": _cid(text), "text_raw": text, "pathway_strength": 0.7,
            "confidence": 0.8, "created_at": NOW,
        })
    for i, (role, text) in enumerate(MESSAGES):
        client.write_node("Message", {
            "message_id": f"m{i:02d}", "text_raw": text, "role": role,
            "created_at": f"2026-10-01T12:{i:02d}:00+00:00",
        })
    for head, rel, tail in EDGES:
        assert client.upsert_semantic_relation(
            rel, mint_uri("Concept", _cid(head)), mint_uri("Concept", _cid(tail)), 0.75, "LLM", NOW)
    return client


def _edges(client) -> set[tuple[str, str, str, str]]:
    """(head, rel, tail, inferred_by) for every Concept-Concept supersession edge."""
    rows = client.store.query("""
        PREFIX campy: <https://campy.dev/ns#>
        SELECT ?h ?p ?t ?by WHERE {
            VALUES ?p { campy:CHOSEN_OVER campy:REPLACES }
            ?a ?p ?b . ?a campy:text_raw ?h . ?b campy:text_raw ?t .
            OPTIONAL { ?r <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> <<( ?a ?p ?b )>> ;
                          campy:inferred_by ?by }
        }""")
    return {(r["h"].value, r["p"].value.rsplit("#", 1)[-1], r["t"].value,
             r["by"].value if r["by"] is not None else None) for r in rows}


@pytest.fixture
def client(tmp_path):
    return _build_store(tmp_path / "brain.db")


@pytest.fixture(scope="module")
def nlp():
    import spacy

    return spacy.load("en_core_web_md")


def _run(client, nlp, apply):
    from campy.cli.graph_repair import repair_supersession_edges

    return asyncio.run(repair_supersession_edges(client, apply=apply, nlp=nlp))


@needs_spacy
def test_dry_run_reports_exactly_the_inverted_edges_and_writes_nothing(client, nlp):
    before = _edges(client)
    verdicts = _run(client, nlp, apply=False)

    by_label = {v.label: v for v in verdicts}
    assert set(by_label) == {f"{h} -{r}-> {t}" for h, r, t in EDGES}
    assert {k for k, v in by_label.items() if v.verdict == "inverted"} == INVERTED
    assert by_label["TLS 1.3 -REPLACES-> TLS 1.2"].verdict == "right"
    assert by_label["RS256 -CHOSEN_OVER-> HS256"].verdict == "right"
    assert by_label["Vue 2 -CHOSEN_OVER-> Vue 3"].verdict == "conflicting"
    for label in ("PostgreSQL -CHOSEN_OVER-> Primary database", "PostgreSQL -CHOSEN_OVER-> PostgreSQL 16",
                  "Zstandard -CHOSEN_OVER-> gzip", "Redis -CHOSEN_OVER-> Memcached"):
        assert by_label[label].verdict == "unverifiable", label

    # each inverted edge is justified by the user message that contradicts it
    pg = by_label["PostgreSQL 14 -CHOSEN_OVER-> PostgreSQL 16"]
    assert [st.message_id for st in pg.evidence] == ["m00"]
    assert (pg.evidence[0].new, pg.evidence[0].old) == ("PostgreSQL 16", "PostgreSQL 14")

    assert _edges(client) == before


@needs_spacy
def test_apply_fixes_inverted_edges_and_leaves_the_rest(client, nlp):
    before = _edges(client)
    _run(client, nlp, apply=True)
    after = _edges(client)

    removed = {(h, r, t) for h, r, t, _ in before - after}
    added = {(h, r, t, by) for h, r, t, by in after - before}
    assert removed == {
        ("PostgreSQL 14", "CHOSEN_OVER", "PostgreSQL 16"),
        ("Zipkin", "CHOSEN_OVER", "OpenTelemetry OTel"),
        ("ActiveMQ", "REPLACES", "Apache Kafka"),
        ("TLS 1.2", "CHOSEN_OVER", "TLS 1.3"),
    }
    assert added == {
        ("PostgreSQL 16", "REPLACES", "PostgreSQL 14", "system:b465-repair"),
        ("OpenTelemetry OTel", "REPLACES", "Zipkin", "system:b465-repair"),
        ("Apache Kafka", "REPLACES", "ActiveMQ", "system:b465-repair"),
        # "TLS 1.3 REPLACES TLS 1.2" already existed: kept as it was, not re-added
    }
    assert ("TLS 1.3", "REPLACES", "TLS 1.2", "LLM") in after
    # every edge that is not inverted is untouched, annotations included
    untouched = {e for e in before if f"{e[0]} -{e[1]}-> {e[2]}" not in INVERTED}
    assert untouched <= after
    # one annotation per edge: the removal dropped the old reifiers
    reifiers = client.store.query("""
        SELECT (COUNT(?r) AS ?n) WHERE { ?r <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> ?x }""")
    assert int(next(iter(reifiers))["n"].value) == len(after)


@needs_spacy
def test_second_run_is_a_no_op(client, nlp):
    _run(client, nlp, apply=True)
    once = _edges(client)
    verdicts = _run(client, nlp, apply=True)
    assert _edges(client) == once
    assert not [v for v in verdicts if v.verdict == "inverted"]
    assert {v.label for v in verdicts if v.verdict == "right"} >= {
        "PostgreSQL 16 -REPLACES-> PostgreSQL 14", "OpenTelemetry OTel -REPLACES-> Zipkin",
        "Apache Kafka -REPLACES-> ActiveMQ", "TLS 1.3 -REPLACES-> TLS 1.2",
    }


@needs_spacy
def test_cli_dry_run_then_apply(tmp_path):
    from typer.testing import CliRunner

    from campy.cli.graph_repair import graph_app

    db = tmp_path / "brain.db"
    client = _build_store(db)
    del client
    gc.collect()  # release the store's lock before the command opens it

    runner = CliRunner()
    dry = runner.invoke(graph_app, ["repair-supersession-edges", "--db-path", str(db)], terminal_width=250)
    assert dry.exit_code == 0, dry.output
    assert "4 inverted" in dry.output and "dry run" in dry.output
    assert "would be repaired" in dry.output

    applied = runner.invoke(graph_app, ["repair-supersession-edges", "--db-path", str(db), "--apply"],
                            terminal_width=250)
    assert applied.exit_code == 0, applied.output
    assert "4 inverted edge(s) repaired" in applied.output

    again = runner.invoke(graph_app, ["repair-supersession-edges", "--db-path", str(db)], terminal_width=250)
    assert again.exit_code == 0, again.output
    assert "0 inverted" in again.output
