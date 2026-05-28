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

  MERGE (a)-[r:CO_OCCURS_WITH]->(b)
  ON CREATE SET r.count = 1, r.strength = $min_conf, r.first_seen = $now
  ON MATCH  SET r.count = r.count + 1, r.strength = (r.strength + $new_conf) / 2

  co_occurrence_threshold (default 10): crossing triggers Hebbian Trigger 2 (M5+).

Background sweep (M4 stub — M5 implements):
  pathway_strength decay: new = current * decay_rate ^ days_since_access
"""

import math
import uuid
from datetime import datetime, timezone


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
        result = db.execute(
            "MATCH (c:Concept {concept_id: $id}) "
            "RETURN c.pathway_strength, c.last_accessed_at, c.created_at",
            {"id": existing_concept_id}
        )
        if not result.has_next():
            return {"action": "additive_skip", "reason": "concept not found"}

        row = result.get_next()
        current_strength = row[0] or 0.5
        # Use last_accessed_at if available, fall back to created_at (L14 fix)
        access_time_iso  = row[1] or row[2] or now

    except Exception:
        return {"action": "additive_skip", "reason": "db read error"}

    days = _days_since(access_time_iso)
    increment = math.log(1 + 1 / days)

    # Atomic update: use increment addition to avoid TOCTOU race (L13 fix)
    # Also update last_accessed_at (L15 fix)
    try:
        await db.execute_write(
            "MATCH (c:Concept {concept_id: $id}) "
            "SET c.pathway_strength = c.pathway_strength + $increment, "
            "    c.last_accessed_at = timestamp($now)",
            {"id": existing_concept_id, "increment": increment, "now": now}
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
        result = db.execute(
            "MATCH (c:Concept {concept_id: $id}) RETURN c.pathway_strength",
            {"id": old_concept_id}
        )
        old_strength = result.get_next()[0] if result.has_next() else 0.5
    except Exception:
        old_strength = 0.5

    merge_event_id = str(uuid.uuid4())

    # Batched into a single write to avoid partial application (L16 fix).
    # If any part fails, no changes are committed.
    try:
        await db.execute_write(
            """
            MATCH (old:Concept {concept_id: $old_id}),
                  (new:Concept {concept_id: $new_id})
            SET old.archived = true
            MERGE (old)-[:DEPRECATED_BY]->(new)
            CREATE (me:MergeEvent {
                merge_event_id:        $merge_event_id,
                pre_pathway_strength:  $pre_strength,
                delta_pathway_strength: 0.0,
                alias_added:           [],
                metadata_patch:        $patch,
                created_at:            timestamp($now)
            })
            MERGE (me)-[:UPDATES_PATHWAY]->(new)
            """,
            {
                "old_id":         old_concept_id,
                "new_id":         new_concept_id,
                "merge_event_id": merge_event_id,
                "pre_strength":   old_strength,
                "patch":          f"contradiction:old={old_concept_id},new={new_concept_id}",
                "now":            now,
            }
        )

        # TRIGGERED edge requires Message node — only create if Message exists (O5)
        await db.execute_write(
            "MATCH (m:Message {message_id: $mid}), "
            "      (me:MergeEvent {merge_event_id: $meid}) "
            "MERGE (m)-[:TRIGGERED]->(me)",
            {"mid": message_id, "meid": merge_event_id}
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
                               db, now: str, co_occurrence_threshold: int = 10) -> int:
    """
    Write CO_OCCURS_WITH edges for all pairs of concept_ids from the same message.
    Uses MERGE for idempotent upsert: increments count, updates rolling mean strength.
    Edges are stored as A→B where A.concept_id < B.concept_id (lexicographic)
    to avoid duplicate bidirectional pairs.

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
    # Deduplicate (e.g. if same concept_id appears twice in list)
    pairs = list(set(pairs))

    # L17 fix: batch all pairs into a single UNWIND query instead of
    # n*(n-1)/2 individual write-locked DB calls.
    pairs_params = [{"a_id": a, "b_id": b} for a, b in pairs]
    try:
        await db.execute_write(
            """
            UNWIND $pairs AS pair
            MATCH (a:Concept {concept_id: pair.a_id}),
                  (b:Concept {concept_id: pair.b_id})
            MERGE (a)-[r:CO_OCCURS_WITH]->(b)
            ON CREATE SET r.count     = 1,
                          r.strength  = $strength,
                          r.first_seen = timestamp($now)
            ON MATCH SET  r.count    = r.count + 1,
                          r.strength = (r.strength + $strength) / 2.0
            """,
            {"pairs": pairs_params, "strength": min_confidence, "now": now}
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
        result = db.execute(
            """
            MATCH (anchor:Concept {concept_id: $id})
            MATCH (anchor)-[*1..2]-(neighbor:Concept)
            WHERE neighbor.confidence_low = true
              AND neighbor.archived = false
              AND neighbor.concept_id <> $id
            RETURN DISTINCT neighbor.concept_id,
                   neighbor.confidence,
                   neighbor.pathway_strength
            """,
            {"id": concept_id}
        )

        candidates = []
        while result.has_next():
            row = result.get_next()
            candidates.append({
                "concept_id":       row[0],
                "confidence":       row[1] or 0.5,
                "pathway_strength": row[2] or 0.5,
            })
    except Exception:
        return 0

    for candidate in candidates:
        cid = candidate["concept_id"]
        try:
            # Count high-confidence neighbors (relationship density signal)
            nbr_result = db.execute(
                """
                MATCH (c:Concept {concept_id: $cid})-[]-(n:Concept)
                WHERE n.archived = false AND n.confidence >= 0.60
                RETURN count(n) AS neighbor_count,
                       avg(n.pathway_strength) AS avg_strength
                """,
                {"cid": cid}
            )

            if not nbr_result.has_next():
                continue

            row = nbr_result.get_next()
            neighbor_count = row[0] or 0
            avg_neighbor_strength = row[1] or 0.0

            # Compute new confidence based on graph context
            # Base: existing confidence
            # Boost: +0.05 per high-confidence neighbor (max +0.30)
            # Boost: +0.10 if avg neighbor strength > 0.70
            old_conf = candidate["confidence"]
            density_boost = min(neighbor_count * 0.05, 0.30)
            strength_boost = 0.10 if avg_neighbor_strength > 0.70 else 0.0
            new_conf = min(old_conf + density_boost + strength_boost, 0.99)

            # Only write if confidence actually changed meaningfully
            if new_conf - old_conf < 0.02:
                continue

            promote = new_conf >= 0.90
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $cid}) "
                "SET c.confidence = $conf, "
                "    c.confidence_low = $low",
                {
                    "cid":  cid,
                    "conf": new_conf,
                    "low":  not promote,
                }
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
        prev_r = db.execute(
            "MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid}) "
            "WHERE d.decision_id <> $did "
            "RETURN d.decision_id, d.created_at "
            "ORDER BY d.created_at DESC LIMIT 1",
            {"sid": session_id, "did": decision_id},
        )
        if not prev_r.has_next():
            return

        prev_row = prev_r.get_next()
        prev_id = prev_row[0]

        # Count prior decisions (exclude current) to compute a step_number
        cnt_r = db.execute(
            "MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid}) "
            "WHERE d.decision_id <> $did RETURN count(d)",
            {"sid": session_id, "did": decision_id},
        )
        prior_count = int(cnt_r.get_next()[0]) if cnt_r.has_next() else 0
        step_number = prior_count + 1

        # Create/merge the DECISION_CHAIN edge
        await db.execute_write(
            "MATCH (p:Decision {decision_id: $prev}), (c:Decision {decision_id: $curr}) "
            "MERGE (p)-[r:DECISION_CHAIN]->(c) "
            "ON CREATE SET r.session_id = $sid, r.step_number = $step "
            "ON MATCH SET r.step_number = $step",
            {"prev": prev_id, "curr": decision_id, "sid": session_id, "step": step_number},
        )
    except Exception:
        # Non-fatal — decision chaining is a convenience feature
        return
