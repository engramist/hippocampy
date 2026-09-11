"""tests/test_b422_handler_edge_schema_guard.py — B422 guard + mechanic-link proof.

B413 / B420 / B421 / B422 are all one class: a gateway `_handle_oxigraph_handler`
branch hand-writes `write_edge(label, mint_uri(T1,…), mint_uri(T2,…), props)` whose
label / node tables / property keys drift from what `schema.py` declares, and nothing
catches it until a live run raises. This module adds the guard the class kept asking for:
statically scan every handler `write_edge` call and assert it matches the schema, so the
whole class fails at CI instead of in production. Plus a round-trip proof that the five
mechanic-link handlers actually persist their edges after the B422 fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import (
    EDGE_REIFICATION,
    NODE_PRIMARY_KEYS,
    REL_COLUMNS,
    OxigraphClient,
)
from campy.brain.hippocampus.graph.queries import REGISTRY

_GATEWAY = Path(__file__).resolve().parent.parent / "campy/brain/hippocampus/graph/gateway.py"
_WRITE_EDGE_RE = re.compile(
    r'self\._client\.write_edge\(\s*"([A-Z_]+)"\s*,(.*?)\)\s*\n', re.S
)


def _handler_write_edge_calls():
    """Yield (edge_label, [node_tables], [prop_keys]) for every statically-analyzable
    write_edge call in the gateway handler cluster."""
    src = _GATEWAY.read_text()
    for m in _WRITE_EDGE_RE.finditer(src):
        edge = m.group(1)
        args = m.group(2)
        tables = re.findall(r'mint_uri\("([A-Za-z]+)"', args)
        props = re.findall(r'"([a-z_]+)":', args)
        yield edge, tables, props


def test_every_handler_write_edge_matches_schema():
    """The guard: label classified, node tables exist, props declared (star/occurrence)
    or absent (plain). Catches the B413/B420/B421/B422 class at test time."""
    violations = []
    for edge, tables, props in _handler_write_edge_calls():
        cls = EDGE_REIFICATION.get(edge)
        if cls is None:
            violations.append(f"{edge}: edge label not classified in EDGE_REIFICATION")
        for t in tables:
            if t not in NODE_PRIMARY_KEYS:
                violations.append(f"{edge}: node table {t!r} not in NODE_PRIMARY_KEYS")
        if props:
            if cls == "plain":
                violations.append(f"{edge}: {props} passed to a 'plain' edge (no props allowed)")
            elif cls in ("star", "occurrence"):
                undeclared = [p for p in props if p not in REL_COLUMNS.get(edge, {})]
                if undeclared:
                    violations.append(
                        f"{edge}: undeclared columns {undeclared} "
                        f"(declared: {sorted(REL_COLUMNS.get(edge, {}))})"
                    )
    assert not violations, "handler write_edge calls drift from schema:\n" + "\n".join(violations)


_MECHANIC_CASES = [
    ("arc.link_mechanic_action_pattern", "ArcMechanic", "mechanic_id",
     "ArcActionPattern", "pattern_id", "ARC_MECHANIC_HAS_ACTION_PATTERN",
     dict(mechanic_id="m1", pattern_id="p1", confidence=0.9)),
    ("arc.link_mechanic_effect_pattern", "ArcMechanic", "mechanic_id",
     "ArcEffectPattern", "pattern_id", "ARC_MECHANIC_CAUSES_EFFECT_PATTERN",
     dict(mechanic_id="m1", pattern_id="ep1", confidence=0.8)),
    ("arc.link_mechanic_precondition", "ArcMechanic", "mechanic_id",
     "ArcPrecondition", "precondition_id", "ARC_MECHANIC_REQUIRES",
     dict(mech_id="m1", pre_id="pre1", confidence=0.7)),
    ("arc.link_mechanic_failure_mode", "ArcMechanic", "mechanic_id",
     "ArcFailureMode", "failure_mode_id", "ARC_MECHANIC_FAILS_AS",
     dict(mech_id="m1", fail_id="f1")),
    ("arc.link_failure_recovery_policy", "ArcFailureMode", "failure_mode_id",
     "ArcRecoveryPolicy", "recovery_policy_id", "ARC_FAILURE_RECOVERED_BY",
     dict(fail_id="f1", pol_id="rp1", confidence=0.6)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("qname,src_tbl,src_pk,dst_tbl,dst_pk,edge,params", _MECHANIC_CASES)
async def test_mechanic_link_persists_edge(tmp_path, qname, src_tbl, src_pk, dst_tbl, dst_pk, edge, params):
    client = OxigraphClient(tmp_path / f"{edge}.db")
    gw = GraphGateway(client, REGISTRY)
    # source + dest nodes must exist for the link to have endpoints
    src_id = params.get("mechanic_id") or params.get("mech_id") or params.get("fail_id")
    dst_id = params.get("pattern_id") or params.get("pre_id") or params.get("fail_id") or params.get("pol_id")
    client.write_node(src_tbl, {src_pk: src_id})
    client.write_node(dst_tbl, {dst_pk: dst_id})

    await gw.run(qname, **params)

    import pyoxigraph as ox
    q = f'SELECT (COUNT(*) AS ?n) WHERE {{ ?s <https://campy.dev/ns#{edge}> ?o }}'
    n = int(list(client.store.query(q))[0]["n"].value)
    assert n == 1, f"{qname} did not persist a {edge} edge"
