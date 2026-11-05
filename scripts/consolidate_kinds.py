#!/usr/bin/env python3
"""B525: consolidate the kind labels of an existing store (kind hygiene, see campy/brain/hippocampus/kinds.py).

    python scripts/consolidate_kinds.py <store_dir_or_brain.db> [--dry-run] [--json]

WRITES to the store unless --dry-run: point it at a COPY, or at a real store with the daemon stopped
(one opener). The rule is `kinds.plan_hygiene`: each kind label becomes a clean singular noun ("my
dogs" -> "dog"); kinds that collapse to one label merge (INSTANCE_OF and BROADER edges re-pointed,
the old wording kept as an altLabel, the merged kind archived, never deleted); a meta-noun kind
("name", "thing", ...) loses its INSTANCE_OF edges (plain edges have no archive form, so those edges
are the only thing removed) and is archived. Idempotent: a second run plans nothing.

It also reports, as data only, how many kinds are a young-of/subtype word of another kind in the store
("puppy" next to "dog"). No BROADER link is added for them; that is a separate question.
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

# young-of words and the adult kind they are usually a young of (reported only)
YOUNG_OF = {
    "puppy": "dog", "pup": "dog", "kitten": "cat", "kitty": "cat", "foal": "horse", "calf": "cow",
    "lamb": "sheep", "piglet": "pig", "chick": "chicken", "cub": "bear", "fawn": "deer", "duckling": "duck",
}


async def run(db_dir: Path, dry_run: bool) -> dict:
    from campy.brain.hippocampus import kinds as kinds_mod
    from campy.brain.hippocampus.concept_links import norm_key
    from campy.brain.hippocampus.graph.gateway import get_gateway
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

    gw = get_gateway(OxigraphClient(db_dir))
    kinds = await kinds_mod.load_kinds(gw)
    counts = {str(r["concept_id"]): int(r["n"]) for r in await gw.run("kinds.instance_counts")}
    plan = kinds_mod.plan_hygiene(kinds, counts)

    def stale(k) -> bool:
        clean = kinds_mod.normalise_kind_label(k.pref)
        return clean is None or clean != k.pref

    out = {
        "kinds_before": len(kinds),
        "kinds_with_unclean_label_before": sum(1 for k in kinds.values() if stale(k)),
        "planned": {"relabel": len(plan.relabel), "merge": len(plan.merge), "meta_noun_kinds": len(plan.drop_meta)},
        "meta_noun_labels": sorted(kinds[c].pref for c in plan.drop_meta),
        "merges": sorted(f"{kinds[c].pref} -> {plan.relabel.get(s, kinds[s].pref)}" for c, s in plan.merge.items()),
        "relabels": sorted(f"{kinds[c].pref} -> {v}" for c, v in plan.relabel.items()),
    }
    if not dry_run:
        out["applied"] = await kinds_mod.apply_hygiene(gw, plan, kinds)
    after = await kinds_mod.load_kinds(gw)
    out["kinds_after"] = len(after)
    out["kinds_with_unclean_label_after"] = sum(1 for k in after.values() if stale(k))
    keys = {norm_key(k.pref) for k in after.values()}
    out["young_of_pairs_in_store"] = sorted(f"{y} / {a}" for y, a in YOUNG_OF.items() if y in keys and a in keys)
    out["young_of_kinds_without_adult_kind"] = sorted(y for y in YOUNG_OF if y in keys and YOUNG_OF[y] not in keys)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="a Campy home (holds brain.db) or a brain.db directory")
    ap.add_argument("--dry-run", action="store_true", help="plan and report, write nothing")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    report = asyncio.run(run(db_dir, args.dry_run))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for k, v in report.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
