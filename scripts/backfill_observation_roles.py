#!/usr/bin/env python3
"""B522: backfill HAS_SUBJECT / HAS_OBJECT edges on existing Observations.

    python scripts/backfill_observation_roles.py <store_dir_or_brain.db> [--json]

WRITES to the store: point it at a COPY, or at a real store with the daemon stopped (one opener).
Idempotent; adds edges and fills an empty object_id, never removes anything. The rule is
documented in campy/brain/temporal_lobe/observations/backfill.py (`backfill_roles`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="a Campy home (holds brain.db) or a brain.db directory")
    ap.add_argument("--json", action="store_true", help="print the stats as JSON")
    args = ap.parse_args(argv)

    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.observations.backfill import backfill_roles

    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    stats = asyncio.run(backfill_roles(OxigraphClient(db_dir)))
    d = stats.as_details()
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    n = d["observations"] or 1
    print(f"Observations {d['observations']}")
    print(f"HAS_SUBJECT  {d['subject_before']} -> {d['subject_after']} ({100 * d['subject_after'] / n:.1f}%)")
    print(f"HAS_OBJECT   {d['object_before']} -> {d['object_after']} ({100 * d['object_after'] / n:.1f}%)")
    print(f"ambiguous (several candidate objects, skipped): {d['ambiguous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
