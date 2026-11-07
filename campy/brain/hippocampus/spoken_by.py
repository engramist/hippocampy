"""
campy/brain/hippocampus/spoken_by.py -- B560: a turn's speaker is an edge, not a string.

A Message carries its speaker as a literal ("Caroline"). A question about Caroline needs "the turns Caroline
spoke", and a string match on a label is not a graph relation (P8). With the flag `[loop] spoken_by` (env
`CAMPY_SPOKEN_BY`, default off; on under the principled profile) the Loop links the turn to its speaker's Person
Concept, `Message -SPOKEN_BY-> Concept`, in the same step that seeds that Concept (B472 Phase 2). The concept walk
(`thalamus.bundle_concept_walk`) reads the edge; no string comparison is left in the walk.

The Concept is the one the Loop already finds or creates for a named speaker (exact text, then a recorded label).
`backfill_spoken_by` links the turns of an existing store the same way; it looks the Concept up and never creates one.
Graph store only; every write is a named query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


def spoken_by_enabled(config: dict | None) -> bool:
    """`[loop] spoken_by` (default false; env `CAMPY_SPOKEN_BY=1` turns it on). A config without the key reads as off."""
    return bool(((config or {}).get("loop") or {}).get("spoken_by", False))


async def link_spoken_by(gw: Any, message_id: str, speaker_concept_id: str) -> None:
    """Write `Message -SPOKEN_BY-> speaker Concept` (plain, idempotent)."""
    await gw.run("spoken_by.link_spoken_by", mid=message_id, cid=speaker_concept_id)


async def find_speaker_concept(gw: Any, speaker: str) -> str | None:
    """The live Concept for a speaker name by the Loop's two lookups (exact text, then a label). Never creates one."""
    name = " ".join(str(speaker).split())
    if not name:
        return None
    for query in ("orchestrator.find_concept_by_exact_text", "orchestrator.find_concept_by_label_text"):
        rows = await gw.run(query, t=name)
        if rows:
            row = rows[0]
            cid = row.get("concept_id") or row.get("c.concept_id")
            if cid:
                return str(cid)
    return None


@dataclass
class SpokenByStats:
    turns_seen: int = 0              # live turns naming a speaker with no edge yet
    linked: int = 0                  # edges written (or that would be, on a dry run)
    generic_speaker: int = 0         # "user", "assistant", "Speaker 1": not a person, skipped
    no_concept: int = 0              # a named speaker with no Concept (never created here)
    already_linked_before: int = 0
    linked_after: int = 0
    unresolved_names: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"turns_seen": self.turns_seen, "linked": self.linked, "generic_speaker": self.generic_speaker,
                "no_concept": self.no_concept, "already_linked_before": self.already_linked_before,
                "linked_after": self.linked_after, "unresolved_names": dict(self.unresolved_names)}


async def backfill_spoken_by(gw: Any, *, dry_run: bool = True, is_named=None) -> SpokenByStats:
    """Link every live turn that names a speaker to that speaker's Concept. Idempotent: a turn with an edge is not
    a candidate, and the edge is plain. A dry run counts and writes nothing."""
    if is_named is None:
        from campy.brain.temporal_lobe.loop.orchestrator import _is_named_speaker as is_named
    stats = SpokenByStats()
    stats.already_linked_before = int(((await gw.run("spoken_by.linked_turns")) or [{"turns": 0}])[0].get("turns") or 0)
    rows = await gw.run("spoken_by.unlinked_turns")
    cache: dict[str, str | None] = {}
    for r in rows:
        stats.turns_seen += 1
        speaker = str(r.get("speaker") or "")
        if not is_named(speaker):
            stats.generic_speaker += 1
            continue
        key = " ".join(speaker.split())
        if key not in cache:
            cache[key] = await find_speaker_concept(gw, key)
        cid = cache[key]
        if not cid:
            stats.no_concept += 1
            stats.unresolved_names[key] = stats.unresolved_names.get(key, 0) + 1
            continue
        stats.linked += 1
        if not dry_run:
            await link_spoken_by(gw, str(r["message_id"]), cid)
    stats.linked_after = int(((await gw.run("spoken_by.linked_turns")) or [{"turns": 0}])[0].get("turns") or 0)
    return stats
