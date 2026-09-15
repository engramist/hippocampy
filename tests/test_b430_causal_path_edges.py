"""tests/test_b430_causal_path_edges.py — B430 proof.

`arc_get_causal_path` (a live, registered MCP tool) is built on a Cypher/SPARQL
pattern that mandatorily traverses `DERIVED_FROM_FACT` (ActionFact->ActionEffect)
and `REQUIRES_ENTITY` (GridEntity<->VictoryCondition). Neither edge had a writer
anywhere in the repo — confirmed live against the real production store (even
after migrating in 44,427 real historical edges): zero triples of either type,
ever. The tool has been structurally incapable of returning `path_exists: True`
since it was built.

Root cause + fix, with zero domain-semantics guessing:

- `DERIVED_FROM_FACT`: `arc_record_action_effect` already computes both
  `fact_id` (`f"{task_id}_{action_id}"`) and `effect_id`
  (`f"{task_id}_{action_id}_step{step}"`) deterministically in the SAME call
  that creates both nodes — every effect observation IS, by definition, one of
  the observations the fact aggregates. Wire the edge there; zero new params,
  zero guessing.
- `REQUIRES_ENTITY`: no existing call site carries entity awareness at all
  (`arc_update_goal_confidence` never has). Rather than invent a heuristic
  (e.g. guessing at a color-match), extend it with an OPTIONAL `entity_ref`
  parameter — the same additive pattern `record_rule`/`arc_confirm_hypothesis`
  already use — so existing callers are unaffected and a caller that DOES know
  which entity a goal update is about can now say so.

Both are "star" (property-bearing), classified from schema.py's own Kùzu DDL
(the authoritative source, NOT the pre-existing read query's accessor style,
which was the wrong signal an earlier draft of this fix used): `step` on
DERIVED_FROM_FACT, `requirement` on REQUIRES_ENTITY — and REQUIRES_ENTITY's
declared direction is FROM VictoryCondition TO GridEntity, not the reverse.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, EDGE_REIFICATION
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus.tools.arc_queries import (
    arc_record_action_effect,
    arc_update_goal_confidence,
    arc_get_causal_path,
)

TASK = "b430-test"


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b430.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


def test_both_edges_are_now_classified_star():
    # Per schema.py's own DDL (the authoritative source): both carry a real
    # non-FROM/TO column (step, requirement) -- "star", not "plain".
    assert EDGE_REIFICATION.get("DERIVED_FROM_FACT") == "star"
    assert EDGE_REIFICATION.get("REQUIRES_ENTITY") == "star"


@pytest.mark.asyncio
async def test_arc_record_action_effect_writes_derived_from_fact(gw, ox_client):
    result = await arc_record_action_effect(
        {"task_id": TASK, "action_id": "ACTION6", "step": 1,
         "effect": {"n_cells_changed": 3, "apparent_effect": "moved"}},
        ox_client, {},
    )
    assert result["ok"] is True
    fact_id, effect_id = result["fact_id"], result["effect_id"]

    n = list(ox_client.store.query(
        f'SELECT (COUNT(*) AS ?n) WHERE {{ '
        f'?af <https://campy.dev/ns#fact_id> "{fact_id}" ; '
        f'<https://campy.dev/ns#DERIVED_FROM_FACT> ?ae . '
        f'?ae <https://campy.dev/ns#effect_id> "{effect_id}" . }}'
    ))[0]["n"].value
    assert int(n) == 1, "DERIVED_FROM_FACT was not written between the fact and its effect"


@pytest.mark.asyncio
async def test_multiple_effects_all_derive_the_same_fact(gw, ox_client):
    """Every observation of the same (task_id, action_id) across different
    steps contributes to the SAME ActionFact — each must get its own
    DERIVED_FROM_FACT edge (star-shaped from one fact to many effects)."""
    for step in (1, 2, 3):
        await arc_record_action_effect(
            {"task_id": TASK, "action_id": "ACTION6", "step": step, "effect": {}},
            ox_client, {},
        )
    fact_id = f"{TASK}_ACTION6"
    n = list(ox_client.store.query(
        f'SELECT (COUNT(?ae) AS ?n) WHERE {{ '
        f'?af <https://campy.dev/ns#fact_id> "{fact_id}" ; '
        f'<https://campy.dev/ns#DERIVED_FROM_FACT> ?ae . }}'
    ))[0]["n"].value
    assert int(n) == 3


@pytest.mark.asyncio
async def test_goal_confidence_without_entity_ref_is_unaffected(gw, ox_client):
    """Regression: every existing caller omits entity_ref — behavior must be
    byte-identical to before this change."""
    result = await arc_update_goal_confidence(
        {"goal_id": "vc1", "task_id": TASK, "new_confidence": 0.5, "has_meaningful_progress": True},
        ox_client, {},
    )
    assert result["status"] == "ok"
    n = list(ox_client.store.query(
        'SELECT (COUNT(*) AS ?n) WHERE { ?ge <https://campy.dev/ns#REQUIRES_ENTITY> ?vc }'
    ))[0]["n"].value
    assert int(n) == 0, "no entity_ref supplied — no edge should be written"


@pytest.mark.asyncio
async def test_goal_confidence_with_entity_ref_writes_requires_entity(gw, ox_client):
    ox_client.write_node("GridEntity", {"entity_id": f"{TASK}_e0_5", "task_id": TASK, "region_index": 5})

    result = await arc_update_goal_confidence(
        {"goal_id": "vc1", "task_id": TASK, "new_confidence": 0.5,
         "has_meaningful_progress": True, "entity_ref": 5, "requirement": "must be moved onto target"},
        ox_client, {},
    )
    assert result["status"] == "ok"

    # Direction per schema.py: FROM VictoryCondition TO GridEntity.
    n = list(ox_client.store.query(
        f'SELECT ?req WHERE {{ '
        f'?vc <https://campy.dev/ns#condition_id> "vc1" . '
        f'?ge <https://campy.dev/ns#entity_id> "{TASK}_e0_5" . '
        f'<< ?vc <https://campy.dev/ns#REQUIRES_ENTITY> ?ge >> '
        f'<https://campy.dev/ns#requirement> ?req . }}'
    ))
    rows = list(n)
    assert len(rows) == 1, "REQUIRES_ENTITY (VictoryCondition->GridEntity, star) was not written"
    assert rows[0]["req"].value == "must be moved onto target"


@pytest.mark.asyncio
async def test_arc_get_causal_path_now_finds_a_real_path(gw, ox_client):
    """The actual regression this card exists for: arc_get_causal_path must be
    able to return path_exists=True at least once it has real data — before
    this fix it was structurally incapable of this for ANY input, ever."""
    ox_client.write_node("GridEntity", {"entity_id": f"{TASK}_e0_5", "task_id": TASK, "region_index": 5})

    effect_result = await arc_record_action_effect(
        {"task_id": TASK, "action_id": "ACTION6", "step": 1, "effect": {}},
        ox_client, {},
    )
    # MOVED_BY (B421) is the other mandatory hop — write it directly.
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    ox_client.write_edge(
        "MOVED_BY", mint_uri("GridEntity", f"{TASK}_e0_5"),
        mint_uri("ActionEffect", effect_result["effect_id"]),
        {"delta_row": 1.0, "delta_col": 0.0},
    )
    await arc_update_goal_confidence(
        {"goal_id": "vc1", "task_id": TASK, "new_confidence": 0.5,
         "has_meaningful_progress": True, "entity_ref": 5},
        ox_client, {},
    )

    result = await arc_get_causal_path(
        {"task_id": TASK, "action_id": "ACTION6", "goal_id": "vc1"}, ox_client, {},
    )
    assert result["path_exists"] is True, (
        "arc_get_causal_path still cannot find a path even with a fully wired "
        "ActionFact->ActionEffect->GridEntity->VictoryCondition chain"
    )
