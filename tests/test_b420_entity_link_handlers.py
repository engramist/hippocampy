"""tests/test_b420_entity_link_handlers.py — B420 proof.

The Python handlers for arc.link_entity_rule / arc.link_entity_hypothesis
(gateway.py) wrote the wrong edge (ANCHORED_TO — classified "plain", so passing
{weight, step} raises) from the wrong source (an InvestigationThread minted from
params["tid"], which is actually the task_id) and ignored `eref` entirely. As a
result the GridEntity→Rule / GridEntity→Hypothesis evidence edge was never
created, arc_get_entity_neighborhood always returned empty, and entity Cynefin
mapping could never progress.

These tests drive the real GraphGateway + OxigraphClient + REGISTRY path and
assert a NON-EMPTY neighborhood after a link — the round-trip the ARC client's
entity mapping depends on.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b420.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


TASK = "wa30-test"
EREF = 9


def _make_entity(client):
    client.write_node("GridEntity", {
        "entity_id": f"{TASK}_e14_{EREF}", "task_id": TASK,
        "region_index": EREF, "color_id": 14, "pixel_count": 12,
    })


@pytest.mark.asyncio
async def test_link_entity_rule_makes_rule_recallable_in_neighborhood(gw, ox_client):
    _make_entity(ox_client)
    ox_client.write_node("Rule", {
        "rule_id": "rule-1", "task_id": TASK, "action_family": "ACTION6",
        "from_color": 7, "to_color": 4, "confidence": 0.5, "falsified": False,
    })

    await gw.run("arc.link_entity_rule", tid=TASK, eref=EREF, rid="rule-1",
                 weight=1.0, step=5)

    rows = await gw.run("arc.get_entity_rules", tid=TASK, eref=EREF)
    assert rows, "ENTITY_RULE edge was not created — entity has no rule evidence"
    assert rows[0]["r.rule_id"] == "rule-1"


@pytest.mark.asyncio
async def test_link_entity_hypothesis_makes_hypothesis_recallable(gw, ox_client):
    _make_entity(ox_client)
    ox_client.write_node("Hypothesis", {
        "id": "hyp-1", "description": "wall blocks movement", "task_id": TASK,
        "confidence": 0.6, "status": "active",
    })

    await gw.run("arc.link_entity_hypothesis", tid=TASK, eref=EREF, hid="hyp-1",
                 weight=1.0, step=5)

    rows = await gw.run("arc.get_entity_hypotheses", tid=TASK, eref=EREF)
    assert rows, "ENTITY_HYPOTHESIS edge was not created — entity has no hypothesis evidence"
    assert rows[0]["h.id"] == "hyp-1"
