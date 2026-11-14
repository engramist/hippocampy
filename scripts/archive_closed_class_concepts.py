#!/usr/bin/env python3
"""B565: archive the closed-class words stored as Concepts in a store COPY.

Usage: python scripts/archive_closed_class_concepts.py --store PATH_TO_STORE_COPY [--dry-run]

Refuses the live store (anything under ~/.campy). Prints each archived Concept, the number of facts that had one as
subject, and how many facts are left without a live subject.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", required=True, help="a COPY of a store directory (holding brain.db)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    store = Path(args.store).expanduser().resolve()
    live = (Path.home() / ".campy").resolve()
    if store == live or live in store.parents:
        print(f"refusing to touch the live store under {live}; copy it first", file=sys.stderr)
        return 2
    db_path = store / "brain.db"
    if not db_path.exists():
        print(f"no brain.db in {store}", file=sys.stderr)
        return 2

    from campy.brain.hippocampus.entity_hygiene import archive_closed_class_concepts, facts_left_without_subject
    from campy.brain.hippocampus.graph.gateway import GraphGateway
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.graph.queries import REGISTRY

    async def run():
        gw = GraphGateway(OxigraphClient(db_path), REGISTRY)
        rows = await archive_closed_class_concepts(gw, dry_run=args.dry_run)
        for r in rows:
            print(f"{'would archive' if args.dry_run else 'archived'} {r['label']!r} ({r['concept_id']}), "
                  f"subject of {int(r['subject_facts'])} facts")
        print(f"{len(rows)} closed-class Concepts; facts left without a live subject: "
              f"{await facts_left_without_subject(gw)}")

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
