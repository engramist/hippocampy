"""tests/test_b421_moved_by_link_handler.py — B421 proof.

The gateway handler for arc.link_entity_moved_by wrote a MOVED_BY edge with the
wrong property keys ({dr, dc} instead of the declared delta_row/delta_col) from a
non-existent node table (mint_uri("Entity", ...) — the table is GridEntity). Since
MOVED_BY is a "star" edge, write_edge validates columns and raised
"MOVED_BY.dr is not a declared column", so the edge was never written:
arc_get_entity_movement returned nothing and arc_perceive_state degraded on every
entity move.

This drives the real GraphGateway + OxigraphClient + REGISTRY path and asserts the
movement round-trips.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY

TASK = "sb26-test"
STEP = 5


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b421.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


@pytest.mark.asyncio
async def test_link_entity_moved_by_round_trips_delta(gw, ox_client):
    ox_client.write_node("GridEntity", {
        "entity_id": f"{TASK}_e3_1", "task_id": TASK, "region_index": 1, "color_id": 3,
    })
    ox_client.write_node("ActionEffect", {
        "effect_id": f"{TASK}_ae_step5", "task_id": TASK, "action_id": "ACTION2", "step": STEP,
    })

    await gw.run("arc.link_entity_moved_by",
                 eid=f"{TASK}_e3_1", aeid=f"{TASK}_ae_step5", dr=1.0, dc=-2.0)

    rows = await gw.run("arc.get_entity_movement", tid=TASK, step=STEP)
    assert rows, "MOVED_BY edge was not written — entity movement not recorded"
    row = rows[0]
    assert row["ge.entity_id"] == f"{TASK}_e3_1"
    assert row["m.delta_row"] == 1.0
    assert row["m.delta_col"] == -2.0
