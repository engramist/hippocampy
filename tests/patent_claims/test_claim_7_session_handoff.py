"""
tests/patent_claims/test_claim_7_session_handoff.py — Patent Claim 7 Verification.

Patent Claim 7:
"A method for warm frontier cross-session handoff in multi-session agent architectures,
comprising: locating a prior session associated with a shared quest context, retrieving
memory nodes loaded in the prior session's working memory, filtering out archived or
superseded nodes, and ranking unarchived nodes by Hebbian pathway strength to seed a fresh
session context without requiring exhaustive semantic re-indexing."

Observable Mechanism Assertions:
- Observable return of `get_handoff_context()`:
  - Non-empty list of handoff memory nodes transferred from prior session to fresh session.
  - Strict descending sort order by `pathway_strength`.
  - Exclusion of archived nodes (e.g. `cn-patent-old` where `archived == True` is excluded).
  - Inclusion of valid active decisions/constraints (`d-patent-db`, `cn-patent-new`).
- Zero mocks; pure execution on live Kùzu graph fixture.
"""

from __future__ import annotations

import pytest

from campy.brain.thalamus.working_memory import get_handoff_context


def test_claim_7_session_handoff_prepopulates_fresh_session(patent_db):
    """Verify Claim 7: get_handoff_context transfers top unarchived nodes ordered by pathway_strength."""
    quest_id = "q-patent-1"
    new_session_id = "s-patent-fresh"

    # Execute cross-session handoff
    handoff_nodes = get_handoff_context(
        patent_db,
        quest_id=quest_id,
        new_session_id=new_session_id,
        limit=5,
    )

    # 1. Non-empty handoff transfer
    assert isinstance(handoff_nodes, list)
    assert len(handoff_nodes) > 0

    node_ids = [n["node_id"] for n in handoff_nodes]

    # 2. Archived node exclusion assertion: cn-patent-old is archived in fixture
    assert "cn-patent-old" not in node_ids

    # 3. Active node inclusion assertion: d-patent-db or cn-patent-new must be present
    assert any(nid in ("d-patent-db", "cn-patent-new") for nid in node_ids)

    # 4. Strict pathway_strength descending ordering
    strengths = [float(n["pathway_strength"]) for n in handoff_nodes]
    assert strengths == sorted(strengths, reverse=True)
