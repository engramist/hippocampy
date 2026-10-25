#!/usr/bin/env python3
"""Gate-slice planner: a gate must be able to see its lever (B520).

A lever is gated on a slice of LoCoMo-10 (categories 1-4). If the slice holds few questions of the
construction the lever targets, the gate cannot move whatever the lever does (B505, count/sum answers:
4 counting questions in 120). If every lever is gated on the same conversations, they are reused
adaptively and stop being held out (PRINCIPLES.md 4).

This script counts, per conversation, the category 1-4 questions that match a named construction,
checks an existing slice, and proposes a slice with at least --min-targets target questions,
preferring conversations not in benchmarks/gate_history.json.

The CONSTRUCTIONS below route evaluation only. They decide which questions a reviewer counts as the
lever's target. They are never read by retrieval or answering code.

Examples:
    python scripts/gate_slice.py --construction count
    python scripts/gate_slice.py --construction count --conversations conv-30,conv-44 --max-questions 60
    python scripts/gate_slice.py --construction count --record

The dataset is read with the benchmark runner's own loader, so the slice is what the runner would
run. Find the runner checkout with --runner-dir or BENCHMARK_RUNNER_DIR; by default sibling
directories of this repo (and its parents) are searched for locomo10/dataset.py.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HISTORY = REPO / "benchmarks" / "gate_history.json"
CATEGORIES = [1, 2, 3, 4]

# Evaluation routing only (not answering logic): named structural question forms, matched on the
# question as asked (lower-cased, before any category suffix).
CONSTRUCTIONS = {
    "count": r"\bhow many\b|\bhow much\b|\bnumber of\b|\btotal\b",
    "temporal": r"\bwhen\b|\bhow long ago\b|\bbefore\b|\bafter\b",
    "latest": r"\bcurrent(ly)?\b|\bnow\b|\bmost recent(ly)?\b|\blatest\b",
    "list": r"\bwhat\b.*\ball\b|\bwhich\b",
    "all": r".",
}


def matches(construction, question):
    return bool(re.search(CONSTRUCTIONS[construction], question.lower()))


def find_runner_dir(explicit=None):
    cands = [explicit, os.environ.get("BENCHMARK_RUNNER_DIR")]
    for anc in [REPO, *REPO.parents][:4]:
        if anc.is_dir():
            cands.extend(sorted(p for p in anc.iterdir() if p.is_dir()))
    for c in cands:
        if c and (Path(c) / "locomo10" / "dataset.py").is_file():
            return Path(c)
    raise SystemExit("cannot find the benchmark runner (locomo10/dataset.py); pass --runner-dir or set BENCHMARK_RUNNER_DIR")


def load(runner_dir, **opts):
    sys.path.insert(0, str(runner_dir))
    from locomo10.dataset import ensure_dataset, load_conversations  # the runner's own loader
    return load_conversations(ensure_dataset(), categories=CATEGORIES, **opts)


def count_targets(convs, construction):
    return {c.sample_id: sum(matches(construction, q.raw_question) for q in c.questions) for c in convs}


def read_history(path=HISTORY):
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"gates": []}
    return data


def used_conversations(history):
    return {c for g in history.get("gates", []) for c in g.get("conversations", [])}


def propose(full, capped, used, min_targets):
    """Pick conversations (unused first, then most targets) until the capped slice holds min_targets.
    `full`/`capped`: {conversation: targets} without / with the per-conversation question cap."""
    order = sorted(capped, key=lambda c: (c in used, -capped[c], c))
    picked, total = [], 0
    for c in order:
        if total >= min_targets:
            break
        if capped[c] > 0:
            picked.append(c)
            total += capped[c]
    return picked, total


def flags(conversations, max_questions):
    return (f"--suite locomo10 --locomo10-conversation-ids {','.join(conversations)} "
            f"--locomo10-max-questions {max_questions} --locomo10-categories 1,2,3,4")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--construction", default="count", choices=sorted(CONSTRUCTIONS))
    ap.add_argument("--min-targets", type=int, default=10)
    ap.add_argument("--max-questions", type=int, default=60, help="per-conversation cap (runner default for gates: 60)")
    ap.add_argument("--conversations", help="check this explicit slice, e.g. conv-30,conv-44")
    ap.add_argument("--runner-dir")
    ap.add_argument("--history", default=str(HISTORY))
    ap.add_argument("--record", action="store_true", help="append the proposed slice to the gate history")
    a = ap.parse_args(argv)

    runner = find_runner_dir(a.runner_dir)
    uncapped = load(runner)
    full = count_targets(uncapped, a.construction)
    total_q = {c.sample_id: len(c.questions) for c in uncapped}
    capped = count_targets(load(runner, max_questions=a.max_questions), a.construction)
    history = read_history(a.history)
    used = used_conversations(history)

    print(f"construction: {a.construction}  (category 1-4 questions; cap {a.max_questions}/conversation)")
    print(f"{'conversation':<10} {'questions':>9} {'targets':>8} {'in capped':>10}  history")
    for cid in sorted(full):
        print(f"{cid:<10} {total_q[cid]:>9} {full[cid]:>8} {capped[cid]:>10}  {'used' if cid in used else 'unused'}")

    if a.conversations:
        ids = [x for x in a.conversations.split(",") if x]
        sl = count_targets(load(runner, conversation_ids=ids, max_questions=a.max_questions), a.construction)
        n = sum(sl.values())
        print(f"\nexplicit slice {','.join(ids)} at {a.max_questions}/conversation: {n} {a.construction} targets"
              f" ({'enough' if n >= a.min_targets else 'TOO FEW'} for min {a.min_targets})")

    picked, total = propose(full, capped, used, a.min_targets)
    if total < a.min_targets:
        print(f"\nno slice reaches {a.min_targets} targets at cap {a.max_questions}; best: {total} from {','.join(picked)}")
        return 1
    print(f"\nproposed slice: {','.join(picked)} at {a.max_questions}/conversation = {total} {a.construction} targets")
    print("runner flags:  " + flags(picked, a.max_questions))
    print(f"PR line:       Targets in gate: {total}")
    if a.record:
        history.setdefault("gates", []).append({"label": f"{a.construction} gate", "conversations": picked,
                                                "max_questions": a.max_questions})
        Path(a.history).write_text(json.dumps(history, indent=2) + "\n")
        print(f"recorded in {a.history}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
