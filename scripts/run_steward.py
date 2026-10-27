#!/usr/bin/env python3
"""B535: run the vocabulary steward over a store.

    python scripts/run_steward.py <store_dir_or_brain.db> [--enable] [--max-calls N] [--tasks parent,kind,review]
                                  [--only LABEL,...] [--rounds N] [--second-model NAME] [--json]

WRITES to the store: point it at a COPY (never ~/.campy while a daemon is using it). The steward is behind the
flag `[observations] vocab_steward` (env CAMPY_VOCAB_STEWARD=1); `--enable` sets it for this run. The model is
the store's config (`<store>/config.toml`, else `~/.campy` is NOT read: the defaults apply) under `[llm.steward]`
over `[llm]`; `--second-model NAME` adds a second source on the same endpoint (a different model family from the
steward's, set to NAME), off by default. Start with `--max-calls 10`.

It proposes, it never publishes: every answer is a candidate (invisible to retrieval) until a declared rule
promotes it (see `campy.brain.temporal_lobe.steward.PROMOTION_RULE`). The report lists every proposal: task,
input, answer, reason, and where the pair stands afterwards; then the parentless and kindless counts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def load_config(db_root: Path, enable: bool, second_model: str | None) -> dict:
    import tomllib

    cfg: dict = {}
    toml = db_root / "config.toml"
    if toml.exists():
        cfg = tomllib.loads(toml.read_text())
    cfg.setdefault("llm", {})
    cfg.setdefault("observations", {})
    if os.environ.get("CAMPY_VOCAB_STEWARD", "").strip().lower() in {"1", "true", "yes", "on"} or enable:
        cfg["observations"]["vocab_steward"] = True
    if second_model:
        cfg["llm"]["steward_second"] = {"model": second_model}
    return cfg


async def counts(gw) -> dict:
    parentless = await gw.run("steward.parentless_kinds")
    kindless = await gw.run("steward.owned_without_kind")
    kinds = await gw.run("kinds.live_kinds")
    return {"kinds": len(kinds), "kinds_without_parent": len(parentless), "owned_entities_without_kind": len(kindless)}


async def run(db_dir: Path, args) -> dict:
    from campy.brain.hippocampus.graph.gateway import get_gateway
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe import steward

    cfg = load_config(db_dir.parent, args.enable, args.second_model)
    gw = get_gateway(OxigraphClient(db_dir))
    before = await counts(gw)
    only = {x.strip().casefold() for x in args.only.split(",")} if args.only else None
    report = await steward.run_steward(gw, cfg, tasks=tuple(args.tasks.split(",")), max_calls=args.max_calls,
                                       rounds=args.rounds, only=only)
    return {"before": before, "after": await counts(gw), "summary": report.as_dict(),
            "records": [r.__dict__ for r in report.records],
            "status_counts": [dict(r) for r in await gw.run("steward.status_counts")]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store")
    ap.add_argument("--enable", action="store_true", help="turn the flag on for this run")
    ap.add_argument("--max-calls", type=int, default=None, help="cap on steward model calls (start with 10)")
    ap.add_argument("--tasks", default="parent,kind,review")
    ap.add_argument("--only", default="", help="comma-separated subject labels")
    ap.add_argument("--rounds", type=int, default=2, help="evidence sets asked per subject")
    ap.add_argument("--second-model", default=None, help="model name for the second source (off by default)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    p = Path(args.store).expanduser()
    db_dir = p / "brain.db" if (p / "brain.db").exists() else p
    out = asyncio.run(run(db_dir, args))
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    print("summary:", out["summary"])
    print("before:", out["before"], "\nafter: ", out["after"])
    for r in out["records"]:
        print(f"[{r['task']}] {r['subject']} -> {r['answer']}  ({r['outcome']})  reason: {r['reason']}")
    print("status counts:", out["status_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
