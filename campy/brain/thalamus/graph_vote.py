"""
campy/brain/thalamus/graph_vote.py -- B548: the graph votes in fusion.

Conversation seed selection fuses a vector list and a lexical list. This adds the graph's list: the evidence
turns of the subject's live Observations that match what the question asks, ranked by one NamedQuery
(`thalamus.graph_vote_turns`, graph/queries/thalamus.py). The rule lives in that query (the subject, the kind
asked and the entities named are parameters the B547 analysis resolved from closed sets); this module only
decides whether to ask and passes the resolved ids. It filters and ranks nothing.

No vote (the two-list path, byte-identical to before) when: the flag is off; the B547 analysis is absent
(`question_analysis` off or failed); no subject resolved; the subject is a tie; the question names neither
a kind nor a named Concept beyond the subject (the query returns nothing); the query fails.

`[retrieval] graph_vote` (default false; env `CAMPY_GRAPH_VOTE=1`); on under the `principled` profile.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def graph_vote_enabled(config: dict | None) -> bool:
    """`[retrieval] graph_vote` (default false; env `CAMPY_GRAPH_VOTE=1` turns it on). Reads the B547 analysis,
    so it does nothing while `question_analysis` is off."""
    return bool(((config or {}).get("retrieval") or {}).get("graph_vote", False))


def vote_parameters(analysis) -> dict | None:
    """The query's parameters from the B547 analysis, or None when there is no vote to ask for."""
    if analysis is None or not analysis.subject_id or analysis.tie:
        return None
    anchors = set(analysis.anchor_ids) | {analysis.subject_id}
    # people are subjects (B547), not entities of the fact; the query decides which Concepts count as entities
    entities = [c["id"] for c in analysis.concepts
                if c["role"] != "person" and c["id"] not in anchors and c["id"] != analysis.kind_id]
    kinds = [analysis.kind_id] if analysis.kind_id else []
    return {"sids": [analysis.subject_id], "kind_ids": kinds, "ent_ids": entities, "need_kind": 1 if kinds else 0}


async def graph_vote_turns(db, config: dict, analysis) -> list[str]:
    """The message URIs the graph proposes for this question, best first; [] for no vote."""
    if not graph_vote_enabled(config):
        return []
    params = vote_parameters(analysis)
    if params is None or not (params["kind_ids"] or params["ent_ids"]):
        return []
    try:
        from campy.brain.hippocampus.graph.gateway import get_gateway

        rows = await get_gateway(db).run("thalamus.graph_vote_turns", **params)
        return [str(r["m"]) for r in (rows or [])]
    except Exception as e:
        _logger.warning("Error in graph vote; the conversation stage fuses two lists: %s", e)
        return []
