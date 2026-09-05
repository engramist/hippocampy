"""
Step 7 — Pathway Update (Recognition / Availability Heuristic)

Named IP Claims:
  - Hebbian Learning: "neurons that fire together wire together"
    → pathway_strength accumulates when a concept is reinforced
  - Long-Term Potentiation: CO_OCCURS_WITH count threshold crossing → LLM
    auto-promotion trigger (Hebbian Trigger 2 — M5+ implementation)
  - Ebbinghaus Forgetting Curve: decay formula in background sweep

Two update paths based on Step 6 output:

  Additive (similarity > 0.92 OR classification = "additive"):
    pathway_strength += log(1 + 1/days_since_created_at)
    No duplicate node created. Existing node absorbs the new information.

  Contradiction (classification = "contradiction"):
    Archive old Concept (archived = true).
    Draw DEPRECATED_BY edge from old → new.
    Create MergeEvent for deterministic rollback.
    Connect: (Message)-[TRIGGERED]->(MergeEvent)-[UPDATES_PATHWAY]->(new Concept)

After both paths:
  CO_OCCURS_WITH: write (or increment) edges between all concept pairs
  from the same message that cleared the noise floor.

  Edge schema:
  (a)-[r:CO_OCCURS_WITH]->(b)
  Initial: r.count = 1, r.strength = $min_conf
  Subsequent: r.count = r.count + 1, r.strength = (r.strength + $new_conf) / 2

  co_occurrence_threshold (default 10): crossing triggers Hebbian Trigger 2 (M5+).

Background sweep (M4 stub — M5 implements):
  pathway_strength decay: new = current * decay_rate ^ days_since_access
"""

import math
import uuid
from datetime import datetime, timezone

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


# ---------------------------------------------------------------------------
# Pathway strength formulas
# ---------------------------------------------------------------------------

def pathway_strength_increment(current_strength: float,
                               days_since_last_access: float) -> float:
    """
    Hebbian reinforcement formula.
    new_strength = current + log(1 + 1/days_since_last_access)
    Minimum days = 1 second to avoid division by zero.
    """
    if days_since_last_access <= 0:
        days_since_last_access = 1 / 86400
    return current_strength + math.log(1 + 1 / days_since_last_access)


def pathway_strength_decay(current_strength: float, decay_rate: float,
                           days_since_last_access: float) -> float:
    """
    Ebbinghaus Forgetting Curve decay formula.
    new_strength = current * decay_rate ^ days_since_last_access
    Called by background sweep (M5), not by this step.
    """
    return current_strength * (decay_rate ** days_since_last_access)


def _days_since(created_at_iso: str) -> float:
    """Parse ISO timestamp and return elapsed days (float). Min 1 second."""
    try:
        created = datetime.fromisoformat(created_at_iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - created).total_seconds()
        return max(elapsed / 86400, 1 / 86400)
    except Exception:
        return 1.0  # default: 1 day


# ---------------------------------------------------------------------------
# Additive update
# ---------------------------------------------------------------------------

async def apply_additive(existing_concept_id: str, db, now: str) -> dict:
    """
    Strengthen an existing Concept node using the Hebbian reinforcement formula.
    Uses an atomic read-compute-write Cypher query to avoid race conditions (L13).
    Updates last_accessed_at on every access (L14/L15).
    Returns {updated_concept_id, action, new_strength}.

    Design note: Additive updates intentionally do NOT create a MergeEvent.
    MergeEvents are the rollback mechanism for contradictions — they record the
    delta between an old and new concept, enabling the Memory Control Panel to
    undo a merge. Additive updates are cumulative reinforcements with no
    discrete rollback point; the pathway_strength field IS the audit trail.
    Only contradictions (apply_contradiction) are rollback-eligible.
    """
    # Read current state to compute increment
    try:
        rows = _gateway(db).run_sync("pathways.get_concept_pathway_state", id=existing_concept_id)
        if not rows:
            return {"action": "additive_skip", "reason": "concept not found"}

        row = rows[0]
        if isinstance(row, dict):
            current_strength = row.get("c.pathway_strength") or 0.5
            access_time_iso = row.get("c.last_accessed_at") or row.get("c.created_at") or now
        else:
            current_strength = row[0] or 0.5
            access_time_iso = row[1] or row[2] or now

    except Exception:
        return {"action": "additive_skip", "reason": "db read error"}

    days = _days_since(access_time_iso)
    increment = math.log(1 + 1 / days)

    # Atomic update: use increment addition to avoid TOCTOU race (L13 fix)
    # Also update last_accessed_at (L15 fix)
    try:
        await _gateway(db).run(
            "pathways.update_concept_pathway_additive",
            id=existing_concept_id,
            increment=increment,
            now=now,
        )
    except Exception:
        return {"action": "additive_skip", "reason": "db write error"}

    return {
        "updated_concept_id": existing_concept_id,
        "action":             "additive",
        "new_strength":       current_strength + increment,
    }


# ---------------------------------------------------------------------------
# Contradiction resolution
# ---------------------------------------------------------------------------

async def apply_contradiction(new_concept_id: str, old_concept_id: str,
                              message_id: str, db, now: str) -> dict:
    """
    Archive the old Concept, draw DEPRECATED_BY old→new, create MergeEvent.

    Audit trail:
      (Message)-[TRIGGERED]->(MergeEvent)-[UPDATES_PATHWAY]->(new Concept)

    Returns {action, merge_event_id, old_concept_id, new_concept_id}.
    """
    # Read old concept's pathway_strength for MergeEvent delta record
    try:
        rows = _gateway(db).run_sync("pathways.get_concept_strength", id=old_concept_id)
        if rows:
            row = rows[0]
            old_strength = (row.get("c.pathway_strength") if isinstance(row, dict) else row[0]) or 0.5
        else:
            old_strength = 0.5
    except Exception:
        old_strength = 0.5

    merge_event_id = str(uuid.uuid4())

    # Batched into a single write to avoid partial application (L16 fix).
    try:
        await _gateway(db).run(
            "pathways.apply_contradiction",
            old_id=old_concept_id,
            new_id=new_concept_id,
            merge_event_id=merge_event_id,
            pre_strength=old_strength,
            patch=f"contradiction:old={old_concept_id},new={new_concept_id}",
            now=now,
        )

        # TRIGGERED edge requires Message node — only create if Message exists (O5)
        await _gateway(db).run(
            "pathways.link_message_merge_event",
            mid=message_id,
            meid=merge_event_id,
        )

    except Exception as e:
        return {"action": "contradiction_error", "reason": str(e)}

    return {
        "action":          "contradiction",
        "merge_event_id":  merge_event_id,
        "old_concept_id":  old_concept_id,
        "new_concept_id":  new_concept_id,
    }


# ---------------------------------------------------------------------------
# CO_OCCURS_WITH — Hebbian implicit layer
# ---------------------------------------------------------------------------

async def write_co_occurs_with(concept_ids: list[str], min_confidence: float,
                               db, now: str, co_occurrence_threshold: int = 10,
                               max_pairs: int = 45) -> int:
    """
    Write CO_OCCURS_WITH edges for all pairs of concept_ids from the same message.
    Uses upsert: increments count, updates rolling mean strength.
    Edges are stored as A→B where A.concept_id < B.concept_id (lexicographic)
    to avoid duplicate bidirectional pairs.

    B283: pair generation is quadratic in concepts-per-message (15 concepts =
    105 edges) — an unbounded supernode feeder. max_pairs caps writes per
    message (default 45 ≈ 10 concepts); selection is deterministic
    (lexicographic) because per-pair confidence is not available at this
    call site. Set max_pairs=0 to disable the cap.

    Returns number of edges written/updated.
    """
    if len(concept_ids) < 2:
        return 0

    # Generate unique sorted pairs
    pairs = [
        (a, b) if a < b else (b, a)
        for i, a in enumerate(concept_ids)
        for b in concept_ids[i+1:]
    ]
    # Deduplicate (e.g. if same concept_id appears twice in list), then sort
    # for deterministic cap selection (B283).
    pairs = sorted(set(pairs))

    if max_pairs > 0 and len(pairs) > max_pairs:
        pairs = pairs[:max_pairs]

    # L17 fix: batch all pairs into a single UNWIND query instead of
    # n*(n-1)/2 individual write-locked DB calls.
    pairs_params = [{"a_id": a, "b_id": b} for a, b in pairs]
    try:
        await _gateway(db).run(
            "pathways.unwind_co_occurs_with",
            pairs=pairs_params,
            strength=min_confidence,
        )
        written = len(pairs)
    except Exception:
        written = 0

    return written


# ---------------------------------------------------------------------------
# Event-driven confidence re-scoring (O7 fix)
# ---------------------------------------------------------------------------

async def rescore_nearby_low_confidence(concept_id: str, db) -> int:
    """
    After a pathway update, re-score confidence_low nodes within 1-2 hops.
    Per CLAUDE.md: "After every pathway update, re-score all confidence_low
    nodes within 1-2 hops."

    Re-scoring factors:
    - Relationship density (more connected = higher confidence)
    - Pathway strength of neighboring nodes
    - If a confidence_low node now has multiple high-confidence neighbors,
      its confidence can be auto-promoted above the 0.90 threshold.

    Returns count of nodes re-scored.
    """
    rescored = 0

    try:
        # Find confidence_low nodes within 1-2 hops of the updated concept
        rows = _gateway(db).run_sync("pathways.find_low_confidence_hops", id=concept_id)

        candidates = []
        for row in rows:
            if isinstance(row, dict):
                cid = row.get("neighbor.concept_id")
                conf = row.get("neighbor.confidence") or 0.5
                pstr = row.get("neighbor.pathway_strength") or 0.5
            else:
                cid = row[0]
                conf = row[1] or 0.5
                pstr = row[2] or 0.5
            candidates.append({
                "concept_id":       cid,
                "confidence":       conf,
                "pathway_strength": pstr,
            })
    except Exception:
        return 0

    for candidate in candidates:
        cid = candidate["concept_id"]
        try:
            # Count high-confidence neighbors (relationship density signal)
            nbr_rows = _gateway(db).run_sync("pathways.count_high_confidence_neighbors", cid=cid)
            if not nbr_rows:
                continue

            row = nbr_rows[0]
            if isinstance(row, dict):
                neighbor_count = row.get("neighbor_count") or 0
                avg_neighbor_strength = row.get("avg_strength") or 0.0
            else:
                neighbor_count = row[0] or 0
                avg_neighbor_strength = row[1] or 0.0

            # Compute new confidence based on graph context
            old_conf = candidate["confidence"]
            density_boost = min(neighbor_count * 0.05, 0.30)
            strength_boost = 0.10 if avg_neighbor_strength > 0.70 else 0.0
            new_conf = min(old_conf + density_boost + strength_boost, 0.99)

            # Only write if confidence actually changed meaningfully
            if new_conf - old_conf < 0.02:
                continue

            promote = new_conf >= 0.90
            await _gateway(db).run(
                "pathways.update_concept_confidence",
                cid=cid,
                conf=new_conf,
                low=not promote,
            )
            rescored += 1

        except Exception:
            pass

    return rescored


async def create_decision_chain(decision_id: str, session_id: str, db) -> None:
    """
    Link a newly-created Decision to the previous Decision in the same Session.
    Writes a DECISION_CHAIN edge with session_id and step_number.

    This function is idempotent and tolerant of missing session context.
    """
    if not session_id or session_id == "unknown":
        return

    try:
        # Find the most recent previous Decision in this session (exclude current)
        prev_rows = _gateway(db).run_sync("pathways.get_previous_decision", sid=session_id, did=decision_id)
        if not prev_rows:
            return

        prev_row = prev_rows[0]
        prev_id = prev_row.get("d.decision_id") if isinstance(prev_row, dict) else prev_row[0]

        # Count prior decisions (exclude current) to compute a step_number
        cnt_rows = _gateway(db).run_sync("pathways.count_prior_decisions", sid=session_id, did=decision_id)
        prior_count = 0
        if cnt_rows:
            r = cnt_rows[0]
            prior_count = int(list(r.values())[0] if isinstance(r, dict) else r[0])
        step_number = prior_count + 1

        # Create/merge the DECISION_CHAIN edge
        await _gateway(db).run(
            "pathways.merge_decision_chain",
            prev=prev_id,
            curr=decision_id,
            sid=session_id,
            step=step_number,
        )
    except Exception:
        # Non-fatal — decision chaining is a convenience feature
        return
