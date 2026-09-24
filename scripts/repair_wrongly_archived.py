#!/usr/bin/env python3
"""B454 one-time repair for two sweep bugs.

1. `sweep.unwind_archive_*` / `resurrect_node_*` took an id list whose SPARQL
   never bound it, so any sweep that archived one node archived EVERY node of
   that table (Concepts, Decisions, Messages, ...).
2. `sweep.decay_pathway_*` deleted the `pathway_strength` triple of any node whose
   decayed value equalled the old one (strength 0) -- every raw Message.

Both are fixed in code; this heals the data. For each sweepable table, an
archived node is un-archived unless it is *legitimately* archived under the
correct rules: pathway_strength < archive_threshold AND (not a Message, or a
Message older than the grace window). Messages missing pathway_strength get
0.0 back. Idempotent. Run with the daemon STOPPED:

    python scripts/repair_wrongly_archived.py ~/.campy/brain.db --dry-run
    python scripts/repair_wrongly_archived.py ~/.campy/brain.db
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import pyoxigraph as ox

CAMPY = "https://campy.dev/ns#"
RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
ARCHIVED = ox.NamedNode(CAMPY + "archived")
STRENGTH = ox.NamedNode(CAMPY + "pathway_strength")
CREATED = ox.NamedNode(CAMPY + "created_at")
DEFAULT = ox.DefaultGraph()
XSD_BOOL = ox.NamedNode("http://www.w3.org/2001/XMLSchema#boolean")
XSD_DEC = ox.NamedNode("http://www.w3.org/2001/XMLSchema#decimal")

TABLES = (
    "Concept", "GlobalConstraint", "GlobalPreference", "Decision", "Constraint",
    "Requirement", "ActionItem", "Message", "DocumentExtract",
)


def _parse_dt(term):
    if term is None:
        return None
    try:
        text = term.value
        dt = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def legitimately_archived(table, strength, created, now, threshold=0.10, grace_days=30.0) -> bool:
    if strength is None or strength >= threshold:
        return False
    if table == "Message" and created is not None and (now - created).total_seconds() < grace_days * 86400:
        return False
    return True


def repair(store, threshold=0.10, grace_days=30.0, dry_run=False) -> dict[str, dict[str, int]]:
    now = datetime.now(timezone.utc)
    true_lit = ox.Literal("true", datatype=XSD_BOOL)
    false_lit = ox.Literal("false", datatype=XSD_BOOL)
    report = {}
    for table in TABLES:
        archived_total = unarchived = kept = strength_restored = 0
        for q in list(store.quads_for_pattern(None, RDF_TYPE, ox.NamedNode(CAMPY + table), DEFAULT)):
            s = q.subject
            strengths = [x.object for x in store.quads_for_pattern(s, STRENGTH, None, DEFAULT)]
            strength = float(strengths[0].value) if strengths else None
            if table == "Message" and strength is None:
                strength_restored += 1
                if not dry_run:
                    store.add(ox.Quad(s, STRENGTH, ox.Literal("0", datatype=XSD_DEC), DEFAULT))
                strength = 0.0
            arch = [x for x in store.quads_for_pattern(s, ARCHIVED, None, DEFAULT)]
            if not any(x.object.value == "true" for x in arch):
                continue
            archived_total += 1
            created = _parse_dt(next((x.object for x in store.quads_for_pattern(s, CREATED, None, DEFAULT)), None))
            if legitimately_archived(table, strength, created, now, threshold, grace_days):
                kept += 1
                continue
            unarchived += 1
            if not dry_run:
                for x in arch:
                    store.remove(x)
                store.add(ox.Quad(s, ARCHIVED, false_lit, DEFAULT))
        report[table] = {"archived": archived_total, "unarchived": unarchived,
                         "kept_archived": kept, "strength_restored": strength_restored}
        print(f"{table:16s} archived={archived_total:>7,} -> unarchived={unarchived:>7,} "
              f"kept={kept:>6,} strength_restored={strength_restored:>6,}")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store_path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--grace-days", type=float, default=30.0)
    args = ap.parse_args(argv)
    store = ox.Store(args.store_path)
    print(f"opened {args.store_path}: {len(store):,} quads")
    repair(store, args.threshold, args.grace_days, args.dry_run)
    if not args.dry_run:
        store.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
