#!/usr/bin/env python3
"""B451 one-time cleanup: collapse duplicate reifiers on `star` edges.

A `star` edge must carry exactly one reifier (`_:r rdf:reifies <<( s p o )>>`
plus its properties). Pure-SPARQL upserts of the form
`INSERT { << ?a p ?b >> pred ?v }` mint a fresh blank-node reifier per solution
(pyoxigraph 0.5 desugaring) and, when combined with an OPTIONAL over the same
quoted triple, grow exponentially -- see B451. The code path is fixed; this
script heals data already polluted by it.

Run with the daemon STOPPED (RocksDB allows one opener) and against a backup
you are happy to lose:

    python scripts/collapse_star_reifiers.py ~/.campy/brain.db --report
    python scripts/collapse_star_reifiers.py ~/.campy/brain.db --collapse CO_OCCURS_WITH

For CO_OCCURS_WITH the survivor keeps count = max(existing counts) and
strength = mean(existing strengths). Re-running is a no-op once every edge has
a single reifier.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time

import pyoxigraph as ox

CAMPY = "https://campy.dev/ns#"
RDF_REIFIES = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies")
DEFAULT = ox.DefaultGraph()


def report(store: "ox.Store", top: int = 10) -> dict[str, dict[str, int]]:
    """Per predicate: how many reifiers, how many distinct triples, worst k."""
    per_triple: collections.Counter = collections.Counter()
    for q in store.quads_for_pattern(None, RDF_REIFIES, None, DEFAULT):
        if isinstance(q.object, ox.Triple):
            per_triple[(q.object.subject, q.object.predicate, q.object.object)] += 1
    by_pred: dict[str, dict[str, int]] = {}
    for (_, p, _), k in per_triple.items():
        d = by_pred.setdefault(p.value, {"reifiers": 0, "triples": 0, "max_k": 0})
        d["reifiers"] += k
        d["triples"] += 1
        d["max_k"] = max(d["max_k"], k)
    rows = sorted(by_pred.items(), key=lambda kv: -kv[1]["reifiers"])[:top]
    for pred, d in rows:
        print(f"{pred.rsplit('#', 1)[-1]:32s} reifiers={d['reifiers']:>10,} "
              f"triples={d['triples']:>8,} worst_k={d['max_k']:>8,}")
    return by_pred


def collapse_edge(store: "ox.Store", s: ox.NamedNode, p: ox.NamedNode, o: ox.NamedNode) -> int:
    """Collapse all reifiers of (s,p,o) into one. Returns reifiers removed.

    CO_OCCURS_WITH is an accumulator: survivor = max(count), mean(strength).
    Every other star edge keeps one reifier intact (the one with the most
    property quads), so no property is lost."""
    triple = ox.Triple(s, p, o)
    reifiers = [q.subject for q in store.quads_for_pattern(None, RDF_REIFIES, triple, DEFAULT)]
    if len(reifiers) <= 1:
        return 0

    if p.value != CAMPY + "CO_OCCURS_WITH":
        sizes = {r: sum(1 for _ in store.quads_for_pattern(r, None, None, DEFAULT)) for r in reifiers}
        survivor = max(reifiers, key=lambda r: (sizes[r], str(r)))
        for r in reifiers:
            if r == survivor:
                continue
            for q in list(store.quads_for_pattern(r, None, None, DEFAULT)):
                store.remove(q)
        return len(reifiers) - 1

    count_iri, strength_iri = CAMPY + "count", CAMPY + "strength"
    counts: list[int] = []
    strengths: list[float] = []
    for r in reifiers:
        for q in store.quads_for_pattern(r, None, None, DEFAULT):
            if q.predicate.value == count_iri:
                counts.append(int(q.object.value))
            elif q.predicate.value == strength_iri:
                strengths.append(float(q.object.value))
    for r in reifiers:
        for q in list(store.quads_for_pattern(r, None, None, DEFAULT)):
            store.remove(q)
    if counts or strengths:
        parts = []
        if counts:
            parts.append(f"<{count_iri}> {max(counts)}")
        if strengths:
            parts.append(f"<{strength_iri}> {sum(strengths) / len(strengths)!r}")
        store.update(
            f"INSERT DATA {{ <{s.value}> <{p.value}> <{o.value}> . "
            f"<< <{s.value}> <{p.value}> <{o.value}> >> " + " ; ".join(parts) + " . }"
        )
    return len(reifiers) - 1


def collapse_predicate(store: "ox.Store", table: str) -> int:
    pred = ox.NamedNode(CAMPY + table)
    edges = {(q.subject, q.object) for q in store.quads_for_pattern(None, pred, None, DEFAULT)}
    removed = 0
    t0 = time.time()
    for i, (s, o) in enumerate(sorted(edges, key=lambda e: (e[0].value, e[1].value)), 1):
        removed += collapse_edge(store, s, pred, o)
        if i % 25 == 0:
            print(f"  {i}/{len(edges)} edges, {removed:,} reifiers removed, {time.time() - t0:.0f}s")
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store_path")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--collapse", metavar="TABLE", nargs="+", help="e.g. CO_OCCURS_WITH EXTENDS")
    args = ap.parse_args(argv)
    if not (args.report or args.collapse):
        ap.error("pass --report and/or --collapse TABLE")
    store = ox.Store(args.store_path)
    print(f"opened {args.store_path}: {len(store):,} quads")
    if args.report:
        report(store)
    if args.collapse:
        for table in args.collapse:
            removed = collapse_predicate(store, table)
            print(f"collapsed {table}: removed {removed:,} duplicate reifiers")
        if args.report:
            report(store)
        store.flush()
        if hasattr(store, "optimize"):
            print("compacting store (Store.optimize)...")
            store.optimize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
