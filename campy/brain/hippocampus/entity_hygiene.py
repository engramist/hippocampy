"""
campy/brain/hippocampus/entity_hygiene.py -- B565: archive the closed-class words already stored as Concepts.

Capture no longer creates them (`temporal_lobe.lexicon.closed_class.is_closed_class`, checked by the Loop, the fact
extractor's entity path and entity admission). This cleanup archives the ones an older capture wrote. The selection is
the named query `entity_hygiene.closed_class_concepts` with the same word list; archiving is `quests.archive_concept`.
No edge is removed, and every read already skips archived Concepts.
"""

from __future__ import annotations

from typing import Any

from campy.brain.temporal_lobe.lexicon.closed_class import CLOSED_CLASS_WORDS


async def archive_closed_class_concepts(gw: Any, *, dry_run: bool = False) -> list[dict]:
    """Archive every live closed-class Concept; returns the rows found (concept_id, label, subject_facts)."""
    rows = await gw.run("entity_hygiene.closed_class_concepts", words=sorted(CLOSED_CLASS_WORDS))
    if not dry_run:
        for row in rows:
            await gw.run("quests.archive_concept", cid=row["concept_id"])
    return rows


async def facts_left_without_subject(gw: Any) -> int:
    """Live facts whose HAS_SUBJECT Concept is an archived closed-class Concept."""
    rows = await gw.run("entity_hygiene.closed_class_subject_facts", words=sorted(CLOSED_CLASS_WORDS))
    return int(rows[0]["facts"]) if rows else 0
