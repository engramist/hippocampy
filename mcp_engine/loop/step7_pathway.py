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
    Reads current pathway_strength + created_at, computes increment, writes update.
    Returns {updated_concept_id, action, new_strength}.
    """
    # Read current state
    try:
        result = db.execute(
            "MATCH (c:Concept {concept_id: $id}) "
            "RETURN c.pathway_strength, c.created_at",
            {"id": existing_concept_id}
        )
        if not result.has_next():
            return {"action": "additive_skip", "reason": "concept not found"}

        row = result.get_next()
        current_strength = row[0] or 0.5
        created_at_iso   = row[1] or now

    except Exception:
        return {"action": "additive_skip", "reason": "db read error"}

    days = _days_since(created_at_iso)
    new_strength = pathway_strength_increment(current_strength, days)

    try:
        await db.execute_write(
            "MATCH (c:Concept {concept_id: $id}) "
            "SET c.pathway_strength = $strength",
            {"id": existing_concept_id, "strength": new_strength}
        )
    except Exception:
        return {"action": "additive_skip", "reason": "db write error"}

    return {
        "updated_concept_id": existing_concept_id,
        "action":             "additive",
        "new_strength":       new_strength,
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

    try:
        # Archive old concept
        await db.execute_write(
            "MATCH (c:Concept {concept_id: $id}) SET c.archived = true",
            {"id": old_concept_id}
        )

        # DEPRECATED_BY: old → new (reading direction: old was superseded by new)
        await db.execute_write(
            "MATCH (old:Concept {concept_id: $old_id}), "
            "      (new:Concept {concept_id: $new_id}) "
            "MERGE (old)-[:DEPRECATED_BY]->(new)",
            {"old_id": old_concept_id, "new_id": new_concept_id}
        )

        # Create MergeEvent audit node
        await db.execute_write(
            """
            CREATE (me:MergeEvent {
                merge_event_id:        $merge_event_id,
                pre_pathway_strength:  $pre_strength,
                delta_pathway_strength: 0.0,
                alias_added:           [],
                metadata_patch:        $patch,
                created_at:            $now
            })
            """,
            {
                "merge_event_id": merge_event_id,
                "pre_strength":   old_strength,
                "patch":          f"contradiction:old={old_concept_id},new={new_concept_id}",
                "now":            now,
            }
        )

        # TRIGGERED: Message → MergeEvent
        await db.execute_write(
            "MATCH (m:Message {message_id: $mid}), "
            "      (me:MergeEvent {merge_event_id: $meid}) "
            "MERGE (m)-[:TRIGGERED]->(me)",
            {"mid": message_id, "meid": merge_event_id}
        )

        # UPDATES_PATHWAY: MergeEvent → new Concept
        await db.execute_write(
            "MATCH (me:MergeEvent {merge_event_id: $meid}), "
            "      (c:Concept {concept_id: $cid}) "
            "MERGE (me)-[:UPDATES_PATHWAY]->(c)",
            {"meid": merge_event_id, "cid": new_concept_id}
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

    written = 0
    for a_id, b_id in pairs:
        try:
            await db.execute_write(
                """
                MATCH (a:Concept {concept_id: $a_id}),
                      (b:Concept {concept_id: $b_id})
                MERGE (a)-[r:CO_OCCURS_WITH]->(b)
                ON CREATE SET r.count    = 1,
                              r.strength = $strength,
                              r.first_seen = $now
                ON MATCH SET  r.count    = r.count + 1,
                              r.strength = (r.strength + $strength) / 2.0
                """,
                {"a_id": a_id, "b_id": b_id, "strength": min_confidence, "now": now}
            )
            written += 1
        except Exception:
            pass

    return written
