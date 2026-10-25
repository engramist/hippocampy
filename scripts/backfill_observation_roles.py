#!/usr/bin/env python3
"""B522: backfill HAS_SUBJECT / HAS_OBJECT edges on existing Observations.

    python scripts/backfill_observation_roles.py <store_dir_or_brain.db> [--json]

WRITES to the store: point it at a COPY, or at a real store with the daemon stopped (one opener).
Idempotent; adds edges and fills an empty object_id, never removes anything. The rule is
documented in campy/brain/temporal_lobe/observations/backfill.py (`backfill_roles`).

With --ownership it then runs the B523 first-person possession rule over every live user Message
linked to an entity Concept (campy/brain/temporal_lobe/observations/ownership.py) and writes an
`owns` Observation per firing, with --sample N printing N firings with their quotes.
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
    ap.add_argument("--ownership", action="store_true", help="also run the B523 first-person possession rule")
    ap.add_argument("--sample", type=int, default=0, help="with --ownership: print N firings with their quotes")
    args = ap.parse_args(argv)

    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.observations.backfill import backfill_roles

    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    client = OxigraphClient(db_dir)
    stats = asyncio.run(backfill_roles(client))
    d = stats.as_details()
    fired: list = []
    if args.ownership:
        from campy.brain.brainstem.config import load_config
        from campy.brain.temporal_lobe.observations.ownership import backfill_ownership

        own = asyncio.run(backfill_ownership(client, load_config(), record=fired))
        d["ownership"] = own.as_details()
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    n = d["observations"] or 1
    print(f"Observations {d['observations']}")
    print(f"HAS_SUBJECT  {d['subject_before']} -> {d['subject_after']} ({100 * d['subject_after'] / n:.1f}%)")
    print(f"HAS_OBJECT   {d['object_before']} -> {d['object_after']} ({100 * d['object_after'] / n:.1f}%)")
    print(f"ambiguous (several candidate objects, skipped): {d['ambiguous']}")
    if args.ownership:
        print(f"ownership rule: {d['ownership']}")
        for mid, label, quote, status, how in fired[: args.sample]:
            print(f"  [{status}] [{how}] {label}: {quote!r}  (msg {mid[:8]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
