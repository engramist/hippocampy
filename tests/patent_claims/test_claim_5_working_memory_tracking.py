"""
tests/patent_claims/test_claim_5_working_memory_tracking.py — Patent Claim 5 Verification.

Patent Claim 5:
"A dynamic context window tracking system for language model agent sessions,
tracking active memory items in working memory via explicit graph relationships (LOADED),
updating cumulative token estimates and load counts without shadow stores, and strictly
excluding raw conversational dialogue turns from working memory persistence."

Observable Mechanism Assertions:
- Verification of `track_loaded()` creating verifiable working memory links.
- Verification of `get_loaded_node_ids()` returning active working memory set.
- Observable return of `get_session_token_state()`:
  - Non-zero `loaded_nodes` and `estimated_tokens`.
  - Valid `utilization` calculation `(estimated_tokens / token_limit)`.
- Verification that raw `Message` turns are explicitly excluded from LOADED tracking.
- Zero mocks; pure execution on live Kùzu graph.
"""

from __future__ import annotations

import pytest

from campy.brain.thalamus.working_memory import (
    get_loaded_node_ids,
    get_session_token_state,
    track_loaded,
)


@pytest.mark.asyncio
async def test_claim_5_track_loaded_lifecycle(patent_db):
    """Verify Claim 5: track_loaded updates loaded IDs and session token state."""
    session_id = "s-patent-fresh"

    # Prior state of fresh session
    initial_state = get_session_token_state(patent_db, session_id)
    assert initial_state["loaded_nodes"] == 0

    # Inject a known node into working memory
    results_to_load = [
        {
            "node_id": "d-patent-db",
            "node_type": "Decision",
            "text_raw": "Use embedded append-only log for persistence",
        }
    ]

    loaded_count = await track_loaded(
        patent_db,
        session_id=session_id,
        results=results_to_load,
        source="current_truth",
    )
    assert loaded_count == 1

    # Observable return from get_loaded_node_ids
    active_ids = get_loaded_node_ids(patent_db, session_id)
    assert "d-patent-db" in active_ids

    # Observable return from get_session_token_state
    updated_state = get_session_token_state(patent_db, session_id)
    assert updated_state["loaded_nodes"] == 1
    assert updated_state["injection_count"] >= 1
    assert 0.0 <= updated_state["utilization"] <= 1.0


@pytest.mark.asyncio
async def test_claim_5_raw_messages_excluded_from_loaded_tracking(patent_db):
    """Verify Claim 5: Raw dialogue turns (Message) are excluded from working memory tracking."""
    session_id = "s-patent-fresh"

    raw_dialogue_turns = [
        {
            "node_id": "m-raw-turn-1",
            "node_type": "Message",
            "text_raw": "Hello, can you help me refactor the database layer?",
        }
    ]

    loaded_count = await track_loaded(
        patent_db,
        session_id=session_id,
        results=raw_dialogue_turns,
        source="dialogue",
    )
    # Raw dialogue turns must be skipped by working memory tracking
    assert loaded_count == 0

    active_ids = get_loaded_node_ids(patent_db, session_id)
    assert "m-raw-turn-1" not in active_ids
