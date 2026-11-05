#!/usr/bin/env python3
"""B534: apply the WordNet kind-hierarchy rule to every kind already in a store.

    python scripts/backfill_wordnet_kinds.py <store_dir_or_brain.db> [--dry-run] [--json] [--sense-cutoff X]

WRITES to the store unless --dry-run: point it at a COPY, or at a real store with the daemon stopped
(one opener). The rule is `lexicon.wordnet.plan_links`: for each live kind, WordNet's hypernyms of its head
noun are matched against the labels (and altLabels) of the OTHER live kinds, and `child BROADER parent` is
written for the nearest matches with `campy:link_source "wordnet"` on the edge. Closed set: no kind is
created. Idempotent. Needs the optional extra `wordnet` and the corpus (`python -m nltk.downloader wordnet`);
without them it reports that and writes nothing.

The report lists every proposed link with the WordNet path, the kinds still without a parent, and the
links per source (the `kinds.broader_links_by_source` query).
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


async def run(db_dir: Path, dry_run: bool, cutoff: float | None) -> dict:
    from campy.brain.hippocampus import kinds as kinds_mod
    from campy.brain.hippocampus.graph.gateway import get_gateway
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

    gw = get_gateway(OxigraphClient(db_dir))
    if not wn_mod.available():
        return {"error": "WordNet is not installed (pip install nltk; python -m nltk.downloader wordnet); nothing written"}
    kwargs = {} if cutoff is None else {"cutoff": cutoff}
    kinds = await kinds_mod.load_kinds(gw)
    links = wn_mod.plan_links(kinds, **kwargs)
    out: dict = {
        "kinds": len(kinds),
        "links_by_source_before": {r["source"]: int(r["n"]) for r in await gw.run("kinds.broader_links_by_source")},
        "proposed": [{"child": l.child_label, "parent": l.parent_label, "path": " > ".join(l.path)} for l in links],
    }
    if not dry_run:
        for l in links:
            await kinds_mod.link_broader_sourced(gw, l.child, l.parent, l.source)
        out["links_by_source_after"] = {r["source"]: int(r["n"]) for r in await gw.run("kinds.broader_links_by_source")}
    after = await kinds_mod.load_kinds(gw)
    with_parent = {c for c, k in after.items() if k.broader} | ({l.child for l in links} if dry_run else set())
    out["kinds_without_parent"] = sorted(k.pref for c, k in after.items() if c not in with_parent)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="a Campy home (holds brain.db) or a brain.db directory")
    ap.add_argument("--dry-run", action="store_true", help="plan and report, write nothing")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--sense-cutoff", type=float, default=None,
                    help="also walk later senses at least this fraction as frequent as the first (default: first sense only)")
    args = ap.parse_args(argv)
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    report = asyncio.run(run(db_dir, args.dry_run, args.sense_cutoff))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for k, v in report.items():
        if k == "proposed":
            print(f"proposed: {len(v)}")
            for row in v:
                print(f"  {row['child']} -> {row['parent']}   [{row['path']}]")
        else:
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
