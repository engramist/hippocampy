"""
B484: fill `time_start`/`time_end`/`time_precision` on Observations written
before time normalisation existed.

`backfill_time(db)` resolves every live Observation that has a `time_text` but
no `time_start`, against its `observed_at` (the evidence Message's date), with
`timeparse.normalize_time`. It never touches `time_text`, the embedding, the
text, the content hash or evidence, so nothing needs re-embedding or
re-extracting.

Idempotent: a row it fills is no longer listed; a row whose phrase cannot be
resolved is left unchanged (and is re-evaluated, harmlessly, next call).
It WRITES, so it belongs in an ingest / maintenance step or on a copy of a
store, never in the read path of `ask`. The read path does not need it:
`render_observation` resolves a NULL `time_start` on the fly (no write).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.temporal_lobe.observations.timeparse import normalize_time

_logger = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    candidates: int = 0
    filled: int = 0
    unresolved: int = 0     # phrase not resolvable, or no usable observed_at

    def as_details(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items()}


async def backfill_time(db: Any, *, limit: int | None = None) -> BackfillStats:
    """Fill the resolved date range of existing Observations. `limit` caps how
    many rows are written this call (None = all)."""
    gw = get_gateway(db)
    stats = BackfillStats()
    rows = await gw.run("observations.list_untimed")
    for row in rows:
        stats.candidates += 1
        if limit is not None and stats.filled >= limit:
            continue
        resolved = normalize_time(row.get("time_text"), obs._as_datetime(row.get("observed_at")))
        if resolved is None:
            stats.unresolved += 1
            continue
        await gw.run(
            "observations.set_time", oid=row["observation_id"],
            time_start=resolved.start, time_end=resolved.end, time_precision=resolved.precision,
        )
        stats.filled += 1
    _logger.info("[Observations] time backfill: %s", stats.as_details())
    return stats


@dataclass
class RoleBackfillStats:
    observations: int = 0
    subject_before: int = 0
    object_before: int = 0
    subject_after: int = 0
    object_after: int = 0
    ambiguous: int = 0      # no object edge: more than one OBSERVATION_ABOUT Concept fits object_text

    def as_details(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items()}


async def _role_counts(gw: Any) -> tuple[int, int, int]:
    row = dict((await gw.run("observations.role_link_counts"))[0])
    return int(row["observations"]), int(row["with_subject"]), int(row["with_object"])


async def backfill_roles(db: Any) -> RoleBackfillStats:
    """B522: give existing Observations their HAS_SUBJECT / HAS_OBJECT edges.

    HAS_SUBJECT from `subject_id`; HAS_OBJECT from `object_id`, else from the one non-subject,
    non-kind OBSERVATION_ABOUT Concept whose label appears as whole words in `object_text`
    (several candidates: skipped and counted as ambiguous). An empty `object_id` is then filled
    from the object edge. Each step is one set-based graph update, so nothing is held in Python.
    Idempotent; it never removes an edge and never touches OBSERVATION_ABOUT. It WRITES: run it
    on a copy of a store or as a maintenance step, not in the read path."""
    gw = get_gateway(db)
    stats = RoleBackfillStats()
    stats.observations, stats.subject_before, stats.object_before = await _role_counts(gw)
    await gw.run("observations.backfill_subject_roles")
    await gw.run("observations.backfill_object_roles_from_id")
    await gw.run("observations.backfill_object_roles_from_text")
    await gw.run("observations.set_object_id_from_role", oid=None)
    _, stats.subject_after, stats.object_after = await _role_counts(gw)
    stats.ambiguous = len(await gw.run("observations.ambiguous_object_candidates"))
    _logger.info("[Observations] role backfill: %s", stats.as_details())
    return stats
