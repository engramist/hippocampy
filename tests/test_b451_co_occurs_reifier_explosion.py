"""tests/test_b451_co_occurs_reifier_explosion.py -- B451 proof.

`pathways.unwind_co_occurs_with` was a pure-SPARQL upsert:

    INSERT { << ?a CO_OCCURS_WITH ?b >> count ?new_count ... }
    WHERE  { ... OPTIONAL { << ?a CO_OCCURS_WITH ?b >> count ?old_count } ... }

pyoxigraph 0.5 desugars `<< s p o >> pred obj` into a FRESH blank-node reifier
per solution, and the OPTIONAL matches every existing reifier -- so re-writing
the same pair doubled its reifier count each time (k -> 2k). Live, this grew
the store from 1.9 GB to 7.7 GB (6.5M orphan `campy:count` triples) and blew
the daemon's footprint past 40 GB inside minutes until macOS killed it.
"""

from __future__ import annotations

import pytest
import pyoxigraph as ox

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import (
    CAMPY_NS,
    RDF_NS,
    RDF_REIFIES,
    OxigraphClient,
    mint_uri,
)
from campy.brain.hippocampus.graph.queries import REGISTRY


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b451.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


def _add_concept(client, cid):
    uri = mint_uri("Concept", cid)
    client.store.update(
        f"INSERT DATA {{ <{uri}> a <{CAMPY_NS}Concept> ; <{CAMPY_NS}concept_id> \"{cid}\" . }}"
    )
    return uri


def _reifiers(client, a_uri, b_uri):
    triple = ox.Triple(
        ox.NamedNode(a_uri), ox.NamedNode(CAMPY_NS + "CO_OCCURS_WITH"), ox.NamedNode(b_uri)
    )
    return [
        q.subject
        for q in client.store.quads_for_pattern(None, RDF_REIFIES, triple, ox.DefaultGraph())
    ]


def _props(client, reifier):
    out = {}
    for q in client.store.quads_for_pattern(reifier, None, None, ox.DefaultGraph()):
        if q.predicate == RDF_REIFIES:
            continue
        out[q.predicate.value.rsplit("#", 1)[-1]] = q.object.value
    return out


@pytest.mark.asyncio
async def test_repeated_writes_keep_exactly_one_reifier(gw, ox_client):
    """AC: writing the same pair N times leaves ONE reifier whose count == N
    (the old SPARQL left 2^(N-1) -- 512 after 10 writes, 2^29 after 30)."""
    a, b = _add_concept(ox_client, "a1"), _add_concept(ox_client, "b1")
    for _ in range(10):
        await gw.run(
            "pathways.unwind_co_occurs_with",
            pairs=[{"a_id": "a1", "b_id": "b1"}],
            strength=0.6,
        )
    reifs = _reifiers(ox_client, a, b)
    assert len(reifs) == 1
    props = _props(ox_client, reifs[0])
    assert int(props["count"]) == 10
    assert float(props["strength"]) == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_store_size_is_linear_not_exponential(gw, ox_client):
    a, b = _add_concept(ox_client, "a2"), _add_concept(ox_client, "b2")
    await gw.run("pathways.unwind_co_occurs_with", pairs=[{"a_id": "a2", "b_id": "b2"}], strength=0.5)
    size_after_one = len(ox_client.store)
    for _ in range(15):
        await gw.run("pathways.unwind_co_occurs_with", pairs=[{"a_id": "a2", "b_id": "b2"}], strength=0.5)
    assert len(ox_client.store) == size_after_one


@pytest.mark.asyncio
async def test_missing_concept_writes_nothing(gw, ox_client):
    _add_concept(ox_client, "only_a")
    before = len(ox_client.store)
    await gw.run(
        "pathways.unwind_co_occurs_with",
        pairs=[{"a_id": "only_a", "b_id": "ghost"}],
        strength=0.6,
    )
    assert len(ox_client.store) == before


@pytest.mark.asyncio
async def test_polluted_edge_collapses_to_one_reifier(gw, ox_client):
    """An edge already polluted by the old bug (several reifiers) is healed
    on its next write: one reifier, count = max(existing) + 1."""
    a, b = _add_concept(ox_client, "a3"), _add_concept(ox_client, "b3")
    for n in (3, 7, 5):
        ox_client.store.update(
            f"INSERT DATA {{ <{a}> <{CAMPY_NS}CO_OCCURS_WITH> <{b}> . "
            f"<< <{a}> <{CAMPY_NS}CO_OCCURS_WITH> <{b}> >> <{CAMPY_NS}count> {n} ; "
            f"<{CAMPY_NS}strength> 0.4 . }}"
        )
    assert len(_reifiers(ox_client, a, b)) == 3
    await gw.run("pathways.unwind_co_occurs_with", pairs=[{"a_id": "a3", "b_id": "b3"}], strength=0.8)
    reifs = _reifiers(ox_client, a, b)
    assert len(reifs) == 1
    props = _props(ox_client, reifs[0])
    assert int(props["count"]) == 8
    assert float(props["strength"]) == pytest.approx((0.4 + 0.8) / 2.0)


@pytest.mark.asyncio
async def test_multiple_pairs_in_one_call(gw, ox_client):
    uris = {c: _add_concept(ox_client, c) for c in ("x", "y", "z")}
    await gw.run(
        "pathways.unwind_co_occurs_with",
        pairs=[{"a_id": "x", "b_id": "y"}, {"a_id": "x", "b_id": "z"}, {"a_id": "y", "b_id": "z"}],
        strength=0.6,
    )
    for a, b in (("x", "y"), ("x", "z"), ("y", "z")):
        assert len(_reifiers(ox_client, uris[a], uris[b])) == 1


def test_collapse_script_heals_polluted_store(tmp_path):
    """The one-time cleanup script leaves one reifier per edge, keeping
    max(count) and mean(strength); re-running is a no-op."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "collapse_star_reifiers",
        Path(__file__).resolve().parent.parent / "scripts" / "collapse_star_reifiers.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    store = ox.Store()
    a, b = "https://campy.dev/id/Concept/p", "https://campy.dev/id/Concept/q"
    for n, st in ((2, 0.2), (9, 0.6), (4, 1.0)):
        store.update(
            f"INSERT DATA {{ <{a}> <{CAMPY_NS}CO_OCCURS_WITH> <{b}> . "
            f"<< <{a}> <{CAMPY_NS}CO_OCCURS_WITH> <{b}> >> <{CAMPY_NS}count> {n} ; "
            f"<{CAMPY_NS}strength> {st} . }}"
        )
    triple = ox.Triple(ox.NamedNode(a), ox.NamedNode(CAMPY_NS + "CO_OCCURS_WITH"), ox.NamedNode(b))

    def reifs():
        return [q.subject for q in store.quads_for_pattern(None, RDF_REIFIES, triple, ox.DefaultGraph())]

    assert len(reifs()) == 3
    assert mod.collapse_predicate(store, "CO_OCCURS_WITH") == 2
    (r,) = reifs()
    props = {q.predicate.value.rsplit("#", 1)[-1]: q.object.value
             for q in store.quads_for_pattern(r, None, None, ox.DefaultGraph())
             if q.predicate != RDF_REIFIES}
    assert int(props["count"]) == 9
    assert float(props["strength"]) == pytest.approx(0.6)
    assert mod.collapse_predicate(store, "CO_OCCURS_WITH") == 0
