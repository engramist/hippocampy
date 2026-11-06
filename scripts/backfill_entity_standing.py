#!/usr/bin/env python3
"""B549: derive the standing of every admitted entity of an existing store and trim-merge wrapped spans (no model).

    python scripts/backfill_entity_standing.py <store_dir_or_brain.db> [--apply] [--json] [--sample N]

Default is a DRY RUN: it assesses and counts and writes nothing. `--apply` WRITES to the store: point it at a COPY,
or at a real store with the daemon stopped (one opener). Idempotent (a second run writes nothing new). Order:
assess every live Concept with a `ner_label` (`entity_standing`), trim-merge the Concepts whose text is a wrapper
plus a known name ("Yep Deb" -> "Deb": MENTIONS / OBSERVATION_ABOUT / HAS_SUBJECT / HAS_OBJECT edges move to the
target, the wrapper is archived and its text kept as an alt label), then assess again. The only edges removed are
those re-pointed edges. A kind that is a confirmed entity is listed, never edited. The rule is in
campy/brain/hippocampus/entity_standing.py. It needs B544's admitted entities; without them nothing is planned.

--sample N prints N entities with their standing for a hand audit.
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
    ap.add_argument("--apply", action="store_true", help="write the standing and the merges (default: dry run)")
    ap.add_argument("--json", action="store_true", help="print the stats as JSON")
    ap.add_argument("--sample", type=int, default=0, help="print N entities with their standing")
    ap.add_argument("--seed", type=int, default=549, help="seed of the --sample draw")
    args = ap.parse_args(argv)

    import logging
    import random

    from campy.brain.brainstem.config import load_config
    from campy.brain.hippocampus.entity_standing import backfill_entity_standing
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    client = OxigraphClient(db_dir)
    stats = asyncio.run(backfill_entity_standing(client, load_config(), dry_run=not args.apply, log_every=50))
    d = stats.as_dict()
    if args.json:
        print(json.dumps(d, indent=2))
    else:
        for k, v in d.items():
            print(f"{k:20} {v}")
    if args.sample and args.apply:
        rows = [(str(r["text_raw"]), str(r["ner_label"]), str(r.get("entity_standing")))
                for r in client._execute_and_collect(
                    "SELECT ?text_raw ?ner_label ?entity_standing WHERE { ?c a campy:Concept ; campy:text_raw ?text_raw ;"
                    " campy:ner_label ?ner_label . FILTER NOT EXISTS { ?c campy:archived true }"
                    " OPTIONAL { ?c campy:entity_standing ?entity_standing } }")]
        random.Random(args.seed).shuffle(rows)
        for text, label, standing in rows[: args.sample]:
            print(f"  {text!r} [{label}] {standing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
