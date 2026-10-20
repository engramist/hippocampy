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
