#!/usr/bin/env python3
"""B546: type the object of every live Observation of an existing store, by rule (no model).

    python scripts/backfill_typed_objects.py <store_dir_or_brain.db> [--json] [--limit N] [--sample N]

WRITES to the store: point it at a COPY, or at a real store with the daemon stopped (one opener).
Idempotent: a second run writes nothing new. The rule, the edges it writes and its guards are in
campy/brain/temporal_lobe/observations/typed_objects.py (`backfill_typed_objects`). Entity objects need B544's
admitted entities (Concepts with `ner_label`); without them only nameless objects (ObjectPhrase) are written.

--sample N prints N of the INSTANCE_OF edges the rule wrote (object, kind, the quote) for a hand audit.
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

_AUDIT = """
PREFIX campy: <https://campy.dev/ns#>
SELECT ?oid ?label ?kind ?quote ?obj WHERE {
  ?o a campy:Observation ; campy:observation_id ?oid ; campy:HAS_OBJECT ?e ; campy:evidence_text ?quote ; campy:object_text ?obj .
  ?e campy:INSTANCE_OF ?k . ?k campy:text_raw ?kind .
  { ?e campy:text_raw ?label }
  FILTER NOT EXISTS { ?o campy:archived true }
} ORDER BY ?oid
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="a Campy home (holds brain.db) or a brain.db directory")
    ap.add_argument("--json", action="store_true", help="print the stats as JSON")
    ap.add_argument("--limit", type=int, default=0, help="only the first N Observations (by id)")
    ap.add_argument("--sample", type=int, default=0, help="print N written INSTANCE_OF edges with their quotes")
    ap.add_argument("--seed", type=int, default=5461, help="seed of the --sample draw")
    args = ap.parse_args(argv)

    import logging
    import random

    from campy.brain.brainstem.config import load_config
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.observations.typed_objects import backfill_typed_objects

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    client = OxigraphClient(db_dir)
    stats = asyncio.run(backfill_typed_objects(client, load_config(), limit=args.limit or None, log_every=500))
    d = stats.as_dict()
    if args.json:
        print(json.dumps(d, indent=2))
    else:
        for k, v in d.items():
            print(f"{k:20} {v}")
    if args.sample:
        rows = [(str(r["oid"]), str(r["label"]), str(r["kind"]), str(r["quote"])) for r in client._execute_and_collect(_AUDIT)]
        random.Random(args.seed).shuffle(rows)
        for oid, label, kind, quote in rows[: args.sample]:
            print(f"  {label!r} -> {kind}   | {quote!r}  ({oid[:8]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
