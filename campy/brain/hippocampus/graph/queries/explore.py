"""explore.py — named queries and frontier exploration query builder for explore_graph tool.

B432 (2026-09-16): the `explore.start_node_*` queries' `sparql=` bodies used
to `SELECT ?node` where `?node` was the subject variable itself — a bare URI
string, not hydrated properties. `explore_graph.py`'s `_node_payload()`
expects a dict (`node.get("_label")`, `.get(pk)`, etc.), so every real call
crashed with `AttributeError` on a string, silently swallowed by a bare
`except Exception: continue` — every start-node lookup "failed" and
`explore_graph()` always reported "not found" against the shipped Oxigraph
engine. There's no clean static SPARQL that says "select every declared
column of whatever table this node is" (the column set varies per table),
so `sparql=None` routes these through `gateway.py`'s
`_handle_oxigraph_handler` `explore.start_node_*` branch instead, which
calls `OxigraphClient.get_node(table, uri)` to hydrate the real properties.
Frontier expansion (the actual multi-hop traversal) has its own, separate
fix — see `explore_graph.py`'s `_execute_frontier_query` and
`OxigraphClient.expand_frontier()`.
"""

from __future__ import annotations

from typing import Dict, List
from campy.brain.hippocampus.graph.gateway import NamedQuery

EXPLORE_QUERIES: tuple[NamedQuery, ...] = (
    # Start node lookups for each node table.
    # B399: columns are explicitly aliased (`AS node`, `AS internal_id`)
    # rather than left as bare `n, id(n)`. GraphGateway._materialize_rows()
    # converts each row into a dict keyed by Kùzu's own column-name string
    # whenever get_column_names() is available and lengths line up — for
    # an *unaliased* `id(n)` that key is the undocumented, kuzu-internal
    # `"n._ID"`, not `"id(n)"`. explore_graph.py's positional `row[0]` /
    # `row[1]` access (unchanged since before B386, when this went through
    # a raw db.execute()/has_next()/get_next() loop that returned plain
    # positional lists) silently KeyError'd against that dict — caught by
    # a broad `except Exception: continue` — so every start-node lookup
    # "failed" and explore_graph() always reported "not found". Explicit
    # aliases make the dict keys stable and self-documenting instead of
    # depending on Kùzu's internal naming for an unaliased expression.
    NamedQuery(
        name="explore.start_node_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Concept table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Decision table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Constraint table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Requirement table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in ActionItem table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_lesson",
        cypher="MATCH (n:Lesson) WHERE n.lesson_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Lesson table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_procedure",
        cypher="MATCH (n:Procedure) WHERE n.procedure_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Procedure table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_plan",
        cypher="MATCH (n:Plan) WHERE n.plan_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Plan table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.quest_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in MainQuest table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.quest_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in SideQuest table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_document",
        cypher="MATCH (n:Document) WHERE n.document_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Document table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
    NamedQuery(
        name="explore.start_node_message",
        cypher="MATCH (n:Message) WHERE n.message_id = $id RETURN n AS node, id(n) AS internal_id LIMIT 1",
        params=("id",),
        mutating=False,
        description="Lookup start node in Message table",
        sparql=None,  # B432: hydrated by gateway.py's Python handler instead — see module docstring.
    ),
)


def internal_id_literal(internal_ids: List[Dict[str, int]]) -> str:
    """Build a Cypher list literal of INTERNAL_ID(table, offset) constructors."""
    parts = [f"INTERNAL_ID({int(iid['table'])}, {int(iid['offset'])})" for iid in internal_ids]
    return "[" + ", ".join(parts) + "]"


def build_frontier_query(edge_types: List[str], direction: str, internal_ids: List[Dict[str, int]]) -> str:
    """One query per direction per depth level, unlabeled on both ends."""
    rel_pattern = "|".join(edge_types)
    id_literal = internal_id_literal(internal_ids)
    if direction == "outgoing":
        match_clause = f"MATCH (a)-[r:{rel_pattern}]->(b)"
    elif direction == "incoming":
        match_clause = f"MATCH (a)<-[r:{rel_pattern}]-(b)"
    else:
        match_clause = f"MATCH (a)-[r:{rel_pattern}]-(b)"
    return f"{match_clause} WHERE id(a) IN {id_literal} RETURN a, b, label(r), coalesce(r.confidence, 1.0)"
