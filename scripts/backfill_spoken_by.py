#!/usr/bin/env python3
"""B560: link every turn of an existing store to its speaker's Concept by `SPOKEN_BY` (no model).

    python scripts/backfill_spoken_by.py <store_dir_or_brain.db> [--apply] [--json]

Default is a DRY RUN: it counts and writes nothing. `--apply` WRITES to the store: point it at a COPY, or at a real
store with the daemon stopped (one opener). Idempotent (a turn that has the edge is not a candidate, and the edge is
plain, so a second run writes nothing). A speaker that is a role or placeholder ("user", "assistant", "Speaker 1") is
skipped; a named speaker with no Concept is listed and never created (the Loop seeds one for every named speaker it
processes, so a store built since B472 Phase 2 has them). The rule is in campy/brain/hippocampus/spoken_by.py.
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
    ap.add_argument("--apply", action="store_true", help="write the edges (default: dry run)")
    ap.add_argument("--json", action="store_true", help="print the stats as JSON")
    args = ap.parse_args(argv)

    import logging

    from campy.brain.hippocampus.graph.gateway import get_gateway
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.spoken_by import backfill_spoken_by

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    client = OxigraphClient(db_dir)
    stats = asyncio.run(backfill_spoken_by(get_gateway(client), dry_run=not args.apply)).as_dict()
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        for k, v in stats.items():
            print(f"{k:22} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
