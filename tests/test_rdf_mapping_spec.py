"""Executable conformance tests for docs/rdf-schema-mapping.md §3-§4 (B389).

No mocks — every test runs against a real in-memory `pyoxigraph.Store()`.
Per spec §9: "tests/test_rdf_mapping_spec.py (B389) must encode these as
executable conformance tests so the spec cannot drift from the client."
Each test below is annotated with the spec section it proves.
"""

from __future__ import annotations

import pyoxigraph as ox
import pytest

from campy.brain.hippocampus.graph.oxigraph_client import (
    CAMPY_NS,
    OxigraphClient,
    literal_for,
    mint_uri,
)


@pytest.fixture
def client():
    c = OxigraphClient()
    try:
        yield c
    finally:
        c.close()


# --- §3 / §3.1 — node property serialization, datatype mapping -------------


def test_node_write_asserts_class_triple(client):
    uri = client.write_node("Concept", {"concept_id": "c1"})
    assert uri == "https://campy.dev/id/Concept/c1"
    rows = list(client.store.query(
        f"SELECT ?c WHERE {{ <{uri}> a ?c }}"
    ))
    assert [str(r["c"]) for r in rows] == [f"<{CAMPY_NS}Concept>"]


def test_node_write_one_predicate_per_property(client):
    uri = client.write_node("Concept", {
        "concept_id": "c1",
        "text_raw": "GraphGateway",
    })
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:text_raw ?o }}"
    ))
    assert [str(r["o"]) for r in rows] == ['"GraphGateway"']


# --- §3.2 — datatype fidelity trap: explicit datatype, never bare number ---


def test_double_literal_carries_explicit_xsd_double_never_decimal():
    lit = literal_for("DOUBLE", 0.8)
    assert str(lit.datatype) == "<http://www.w3.org/2001/XMLSchema#double>"
    assert str(lit.datatype) != "<http://www.w3.org/2001/XMLSchema#decimal>"


def test_bare_turtle_number_would_have_parsed_as_decimal_not_double():
    # Empirical proof of the trap the spec warns about (§3.2): a bare
    # numeric literal parsed from Turtle text is xsd:decimal, not
    # xsd:double — which is exactly why literal_for() always supplies an
    # explicit datatype instead of ever emitting bare Turtle text.
    parsed = list(ox.parse(input="<http://a> <http://b> 0.8 .", format=ox.RdfFormat.TURTLE))
    assert str(parsed[0].object.datatype) == "<http://www.w3.org/2001/XMLSchema#decimal>"


def test_double_survives_round_trip_through_the_store(client):
    uri = client.write_node("Concept", {"concept_id": "c1", "confidence": 0.8})
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:confidence ?o }}"
    ))
    assert len(rows) == 1
    assert str(rows[0]["o"].datatype) == "<http://www.w3.org/2001/XMLSchema#double>"
    # str() on a Literal renders full N-Triples form ('"0.8"^^<...#double>');
    # .value is the bare lexical form.
    assert rows[0]["o"].value == "0.8"


def test_float_datatype_preserved(client):
    lit = literal_for("FLOAT", 1.5)
    assert str(lit.datatype) == "<http://www.w3.org/2001/XMLSchema#float>"


def test_boolean_datatype_both_spellings(client):
    # §3.1: "both spellings exist in schema; both map here" (BOOL / BOOLEAN).
    assert str(literal_for("BOOL", True)) == '"true"^^<http://www.w3.org/2001/XMLSchema#boolean>'
    assert str(literal_for("BOOLEAN", False)) == '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>'


def test_int32_and_int64_both_carry_explicit_integer_datatype(client):
    # Deviation from the spec's literal §3.1 table, empirically forced:
    # pyoxigraph 0.5.11 canonicalizes every XSD-integer-derived datatype
    # (int, long, short, byte, ...) to xsd:integer at the storage layer —
    # see oxigraph_client.literal_for()'s docstring for the full probe.
    # What matters for this test (and for §3.2's invariant) is that the
    # tag is always explicit and never a bare/undeclared number.
    for kuzu_type in ("INT32", "INT64"):
        lit = literal_for(kuzu_type, 5)
        assert str(lit.datatype) == "<http://www.w3.org/2001/XMLSchema#integer>"


def test_int_datatype_survives_round_trip_through_the_store(client):
    uri = client.write_node("Concept", {"concept_id": "c1", "embedding_dim": 384})
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:embedding_dim ?o }}"
    ))
    assert str(rows[0]["o"].datatype) == "<http://www.w3.org/2001/XMLSchema#integer>"


def test_timestamp_maps_to_xsd_datetime(client):
    import datetime as dt
    lit = literal_for("TIMESTAMP", dt.datetime(2026, 9, 4, 10, 0, 0, tzinfo=dt.timezone.utc))
    assert str(lit.datatype) == "<http://www.w3.org/2001/XMLSchema#dateTime>"
    assert str(lit).startswith('"2026-09-04T10:00:00')


# --- §3.3 — STRING[] as repeated triples, unordered -------------------------


def test_string_array_emits_repeated_triples_set_equal(client):
    literals = literal_for("STRING[]", ["alpha", "beta", "gamma"])
    assert isinstance(literals, list)
    assert {str(l) for l in literals} == {'"alpha"', '"beta"', '"gamma"'}


def test_string_array_round_trip_is_set_equal_not_order_sensitive(client):
    # `properties` is a STRING[] column on SchemaOrgType per schema.py.
    uri = client.write_node("SchemaOrgType", {
        "name": "Demand",
        "properties": ["b", "a", "c"],
    })
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:properties ?o }}"
    ))
    assert {str(r["o"]) for r in rows} == {'"b"', '"a"', '"c"'}
    assert len(rows) == 3  # three distinct triples, not a serialized list


# --- §3.4 — NULL emits no triple, never a sentinel --------------------------


def test_null_property_emits_no_triple(client):
    uri = client.write_node("Concept", {
        "concept_id": "c1",
        "archived": None,
        "confidence": 0.5,
    })
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:archived ?o }}"
    ))
    assert rows == []
    # sibling non-null property on the same node is unaffected
    rows2 = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:confidence ?o }}"
    ))
    assert len(rows2) == 1


def test_null_never_written_as_sentinel_string(client):
    uri = client.write_node("Concept", {"concept_id": "c1", "archived": None})
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?p ?o WHERE {{ <{uri}> ?p ?o . "
        f'FILTER(?o = "" || ?o = "null" || ?o = "None") }}'
    ))
    assert rows == []


# --- §5 — FLOAT[384] never written to RDF -----------------------------------


def test_float384_embedding_is_skipped_not_written(client):
    uri = client.write_node("Concept", {
        "concept_id": "c1",
        "embedding": [0.1] * 384,
    })
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{uri}> campy:embedding ?o }}"
    ))
    assert rows == []


def test_literal_for_rejects_float384_directly():
    with pytest.raises(ValueError, match="FLOAT\\[384\\]"):
        literal_for("FLOAT[384]", [0.1] * 384)


# --- §4.1 — plain relationships ---------------------------------------------


def test_plain_edge_asserts_a_single_triple(client):
    s = mint_uri("SideQuest", "sq1")
    o = mint_uri("MainQuest", "mq1")
    client.write_edge("BELONGS_TO", s, o)
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{s}> campy:BELONGS_TO ?o }}"
    ))
    assert [str(r["o"]) for r in rows] == [f"<{o}>"]


def test_plain_edge_rejects_properties(client):
    s = mint_uri("SideQuest", "sq1")
    o = mint_uri("MainQuest", "mq1")
    with pytest.raises(ValueError, match="plain"):
        client.write_edge("BELONGS_TO", s, o, {"bogus": 1})


# --- §4.2a — star: plain triple + quoted-triple annotation, both queryable --


def test_star_edge_asserts_both_plain_triple_and_quoted_annotation(client):
    s = mint_uri("Concept", "c_a")
    o = mint_uri("Concept", "c_b")
    client.write_edge("ENABLES", s, o, {"confidence": 0.8, "inferred_by": "step3b"})

    plain = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{s}> campy:ENABLES ?o }}"
    ))
    assert [str(r["o"]) for r in plain] == [f"<{o}>"]

    annotation = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?conf WHERE {{ "
        f"<< <{s}> campy:ENABLES <{o}> >> campy:confidence ?conf }}"
    ))
    assert len(annotation) == 1
    assert annotation[0]["conf"].value == "0.8"
    assert str(annotation[0]["conf"].datatype) == "<http://www.w3.org/2001/XMLSchema#double>"


def test_star_edge_second_write_overwrites_not_accumulates(client):
    # The core "star" invariant: at most ONE edge/annotation per (s,p,o).
    # A second write must not leave the first write's stale properties
    # behind (verified against real pyoxigraph's own reifier-accumulation
    # behavior — see oxigraph_client._remove_existing_reifiers()'s
    # docstring for why this needs an explicit cleanup step).
    s = mint_uri("Concept", "c_a")
    o = mint_uri("Concept", "c_b")
    client.write_edge("ENABLES", s, o, {"confidence": 0.8, "inferred_by": "step3b"})
    client.write_edge("ENABLES", s, o, {"confidence": 0.95, "inferred_by": "step3b_v2"})

    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?p ?o WHERE {{ "
        f"<< <{s}> campy:ENABLES <{o}> >> ?p ?o }}"
    ))
    by_pred = {str(r["p"]): str(r["o"]) for r in rows if "reifies" not in str(r["p"])}
    assert by_pred == {
        f"<{CAMPY_NS}confidence>": '"0.95"^^<http://www.w3.org/2001/XMLSchema#double>',
        f"<{CAMPY_NS}inferred_by>": '"step3b_v2"',
    }
    # plain traversal keeps working throughout
    plain = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{s}> campy:ENABLES ?o }}"
    ))
    assert [str(r["o"]) for r in plain] == [f"<{o}>"]


def test_spec_4_2c_reclassified_tables_write_as_star(client):
    # Spec §4.2c (2026-09-05): ANOMALY_DETECTED, CO_OCCURS_WITH, and
    # OUTCOME_SIGNAL all write via MERGE + SET at their sole Cypher call
    # site, so they are "star" (not "occurrence", despite an earlier spec
    # draft naming them by shape) — this proves the reclassification
    # actually behaves like every other star table: both the plain triple
    # and the quoted annotation are queryable, and a second write overwrites
    # rather than accumulating a second reifier.
    s = mint_uri("Concept", "c_x")
    o = mint_uri("Concept", "c_y")
    client.write_edge("CO_OCCURS_WITH", s, o, {"count": 1, "strength": 0.5})
    client.write_edge("CO_OCCURS_WITH", s, o, {"count": 2, "strength": 0.75})

    plain = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{s}> campy:CO_OCCURS_WITH ?o }}"
    ))
    assert [str(r["o"]) for r in plain] == [f"<{o}>"]

    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?p ?v WHERE {{ "
        f"<< <{s}> campy:CO_OCCURS_WITH <{o}> >> ?p ?v }}"
    ))
    by_pred = {str(r["p"]): str(r["v"]) for r in rows if "reifies" not in str(r["p"])}
    assert by_pred == {
        f"<{CAMPY_NS}count>": '"2"^^<http://www.w3.org/2001/XMLSchema#integer>',
        f"<{CAMPY_NS}strength>": '"0.75"^^<http://www.w3.org/2001/XMLSchema#double>',
    }


def test_star_edge_repeated_identical_write_is_idempotent(client):
    s = mint_uri("Concept", "c_a")
    o = mint_uri("Concept", "c_b")
    client.write_edge("ENABLES", s, o, {"confidence": 0.8})
    client.write_edge("ENABLES", s, o, {"confidence": 0.8})
    rows = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?conf WHERE {{ "
        f"<< <{s}> campy:ENABLES <{o}> >> campy:confidence ?conf }}"
    ))
    assert len(rows) == 1


# --- §4.2b — occurrence: N writes retain N occurrences, plain still matches -


def test_occurrence_edge_n_writes_retain_n_occurrences_and_plain_still_matches(client):
    s = mint_uri("Session", "s1")
    o = mint_uri("Decision", "d1")
    for i in range(3):
        client.write_edge("LOADED", s, o, {
            "token_estimate": 100 + i,
            "source": "bundle_compiler",
            "load_hits": 1,
        })

    tokens = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?tok WHERE {{ "
        f"<< <{s}> campy:LOADED <{o}> >> campy:occurrence/campy:token_estimate ?tok }}"
    ))
    assert len(tokens) == 3
    assert {str(r["tok"]) for r in tokens} == {
        '"100"^^<http://www.w3.org/2001/XMLSchema#integer>',
        '"101"^^<http://www.w3.org/2001/XMLSchema#integer>',
        '"102"^^<http://www.w3.org/2001/XMLSchema#integer>',
    }

    plain = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?o WHERE {{ <{s}> campy:LOADED ?o }}"
    ))
    assert [str(r["o"]) for r in plain] == [f"<{o}>"]


def test_occurrence_uris_are_ulid_minted_not_derived(client):
    s = mint_uri("Session", "s1")
    o = mint_uri("Decision", "d1")
    client.write_edge("LOADED", s, o, {"token_estimate": 1, "source": "x", "load_hits": 1})
    occ = list(client.store.query(
        f"PREFIX campy: <{CAMPY_NS}> SELECT ?occ WHERE {{ "
        f"<< <{s}> campy:LOADED <{o}> >> campy:occurrence ?occ }}"
    ))
    assert len(occ) == 1
    uri = str(occ[0]["occ"]).strip("<>")
    assert uri.startswith("https://campy.dev/id/Occurrence/")
    ulid_part = uri.rsplit("/", 1)[-1]
    assert len(ulid_part) == 26


# --- EDGE_REIFICATION exhaustiveness -----------------------------------------


def test_edge_reification_covers_every_live_rel_table_or_escalates():
    from campy.brain.hippocampus.graph.oxigraph_client import (
        EDGE_REIFICATION,
        UNCLASSIFIED_ESCALATED_TABLES,
    )
    from campy.brain.hippocampus.schema import get_relationship_types

    live = set(get_relationship_types())
    classified = set(EDGE_REIFICATION)
    escalated = set(UNCLASSIFIED_ESCALATED_TABLES)

    assert classified & escalated == set(), "a table cannot be both classified and escalated"
    assert live - classified - escalated == set(), "every live rel table must be classified or escalated"
    assert (classified | escalated) - live == set(), "no stale entries for tables that no longer exist"


def test_missing_edge_reification_entry_raises_at_write_time(client):
    with pytest.raises(ValueError):
        client.write_edge("TOTALLY_MADE_UP_TABLE_NAME", "urn:a", "urn:b")


def test_escalated_table_raises_with_explanation_at_write_time(client):
    # ANOMALY_DETECTED/CO_OCCURS_WITH/OUTCOME_SIGNAL were resolved by spec
    # §4.2c and reclassified "star" (see test_star_edge_* above and
    # test_oxigraph_client.py's test_classify_edge_returns_star_for_spec_
    # 4_2c_reclassified_tables). ADJACENT_TO remains escalated per spec
    # §4.2d: no write call site exists anywhere in the repo.
    with pytest.raises(ValueError, match="deliberately unclassified"):
        client.write_edge("ADJACENT_TO", "urn:a", "urn:b")


# --- §7.2 — NamedQuery.sparql static-string validation ----------------------


def test_named_query_sparql_field_rejects_format_placeholder():
    from campy.brain.hippocampus.graph.gateway import NamedQuery

    with pytest.raises(ValueError, match="format placeholder"):
        NamedQuery(
            name="x.y",
            cypher="MATCH (n) RETURN n",
            params=(),
            mutating=False,
            description="d",
            sparql="SELECT ?o WHERE { ?s <https://campy.dev/ns#p> {table} }",
        )


def test_named_query_sparql_field_accepts_bound_variable_form():
    from campy.brain.hippocampus.graph.gateway import NamedQuery

    q = NamedQuery(
        name="x.y",
        cypher="MATCH (n) RETURN n",
        params=("id",),
        mutating=False,
        description="d",
        sparql="SELECT ?o WHERE { VALUES ?s { ?id } ?s <https://campy.dev/ns#p> ?o }",
    )
    assert q.sparql is not None
