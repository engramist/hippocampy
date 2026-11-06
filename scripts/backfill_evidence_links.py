#!/usr/bin/env python3
"""B554: link every live Observation of an existing store to the admitted entities its evidence names (no model).

    python scripts/backfill_evidence_links.py <store_dir_or_brain.db> [--apply] [--json] [--limit N] [--sample N]

Default is a DRY RUN: it plans and counts and writes nothing. `--apply` WRITES to the store: point it at a COPY,
or at a real store with the daemon stopped (one opener). Idempotent (a second run writes nothing new) and
additive (it never removes an edge). The rule, the edge it writes and its guards are in
campy/brain/temporal_lobe/observations/evidence_entities.py (`backfill_evidence_links`). It needs B544's admitted
entities (Concepts with `ner_label` and MENTIONS); on a store without them it plans nothing.

--sample N prints N of the OBSERVATION_ABOUT edges to admitted entities (entity, label, the quote) for a hand audit.
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
SELECT ?oid ?label ?ner ?quote WHERE {
  ?o a campy:Observation ; campy:observation_id ?oid ; campy:OBSERVATION_ABOUT ?e ; campy:evidence_text ?quote .
  ?e campy:text_raw ?label ; campy:ner_label ?ner .
  FILTER NOT EXISTS { ?o campy:archived true }
} ORDER BY ?oid
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="a Campy home (holds brain.db) or a brain.db directory")
    ap.add_argument("--apply", action="store_true", help="write the links (default: dry run, writes nothing)")
    ap.add_argument("--json", action="store_true", help="print the stats as JSON")
    ap.add_argument("--limit", type=int, default=0, help="only the first N Observations (by id)")
    ap.add_argument("--sample", type=int, default=0, help="print N admitted-entity links with their quotes")
    ap.add_argument("--seed", type=int, default=5541, help="seed of the --sample draw")
    args = ap.parse_args(argv)

    import logging
    import random

    from campy.brain.brainstem.config import load_config
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.observations.evidence_entities import backfill_evidence_links

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    client = OxigraphClient(db_dir)
    stats = asyncio.run(backfill_evidence_links(client, load_config(), dry_run=not args.apply,
                                                limit=args.limit or None, log_every=500))
    d = stats.as_dict()
    if args.json:
        print(json.dumps(d, indent=2))
    else:
        for k, v in d.items():
            print(f"{k:20} {v}")
    if args.sample:
        rows = [(str(r["oid"]), str(r["label"]), str(r["ner"]), str(r["quote"])) for r in client._execute_and_collect(_AUDIT)]
        random.Random(args.seed).shuffle(rows)
        for oid, label, ner, quote in rows[: args.sample]:
            print(f"  {label!r} [{ner}]   | {quote!r}  ({oid[:8]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
