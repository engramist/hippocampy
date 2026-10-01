"""
B462 — Save-gate baseline harness.

Runs the labeled statements in benchmarks/save_gate/gold.yaml through the
Loop's save decision and reports how often it is right.

Two modes:

  full      Steps 1 (spaCy NER), 2 (gist, System 1 only: no LLM, as on a
            machine without Ollama), 3 (schema.org routing) and 4 (artifact
            gate + amygdala salience rescue), using the same functions
            run_loop calls. Needs en_core_web_md and the embedding model.
            Gist centroids are bootstrapped from GistSeedExamples.md, i.e. a
            fresh install's state.

  signals   Step 4's keyword layer only; needs no models. When any keyword
            signal fires, Step 4's artifact type is decided by keywords alone
            (the gist class only adds +0.10 when it agrees), so this mode
            reports that type exactly. When no signal fires, the type comes
            from the gist prior, which this mode cannot know: those items are
            counted as "undetermined".

Usage:
  python -m benchmarks.save_gate.run_baseline --mode signals
  python -m benchmarks.save_gate.run_baseline --mode full [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import yaml

from campy.brain.temporal_lobe.category_spec import CATEGORIES, load_spec
from campy.brain.temporal_lobe.loop.step4_pattern import (
    HARD_LOCK,
    NOISE_FLOOR,
    apply_salience_rescue,
    classify_artifact,
    entity_sentence,
    signal_scores,
)

GOLD_PATH = Path(__file__).with_name("gold.yaml")
ARTIFACT_TYPES = ("decision", "constraint", "requirement", "action_item")
RELIABILITY_BINS = ((0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01))


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    """Load the labeled set and check every label against the category spec."""
    with open(path, encoding="utf-8") as fh:
        items = yaml.safe_load(fh)["items"]
    known = set(load_spec().categories)
    for item in items:
        if item["label"] not in known:
            raise ValueError(f"{item['id']}: label {item['label']!r} not in category spec")
    return items


# ---------------------------------------------------------------------------
# Per-message save decision
# ---------------------------------------------------------------------------

def _outcome(step4: dict) -> str:
    """What the Loop does with one entity: noise, tentative Concept, or reified artifact."""
    if not step4["should_proceed"]:
        return "noise"
    if not step4["confidence_low"] and step4["artifact_type"] in ARTIFACT_TYPES:
        return "reified"
    return "tentative"


_OUTCOME_RANK = {"noise": 0, "tentative": 1, "reified": 2}


def decide_message(text: str, typed_entities: list[dict], role: str = "user",
                   gate_model=None, embed: Callable[[str], list[float]] | None = None) -> dict:
    """
    Run the Step 4 gate over one message's typed entities (output of Steps
    1–3) exactly as run_loop does, and reduce to a message-level result: the
    strongest entity outcome (reified > tentative > noise, then confidence).

    gate_model: a B460 GateModel to score with instead of keyword counts;
    embed(sentence) is used when that model needs sentence embeddings.

    Returns {outcome, artifact_type, confidence, entities}.
    """
    best = {"outcome": "noise", "artifact_type": "none", "confidence": 0.0}
    per_entity = []
    for entity in typed_entities:
        embedding = None
        if gate_model is not None and gate_model.needs_embedding and embed is not None:
            embedding = embed(entity_sentence(text, entity.get("text") or text))
        step4 = classify_artifact(
            text,
            entity.get("gist_class"),
            entity.get("schema_org_type"),
            entity_text=entity.get("text"),
            role=role,
            gate_model=gate_model,
            embedding=embedding,
        )
        step4, _salience, rescued = apply_salience_rescue(step4, text)
        outcome = _outcome(step4)
        row = {
            "text": entity.get("text"),
            "gist_class": entity.get("gist_class"),
            "outcome": outcome,
            "artifact_type": step4["artifact_type"],
            "confidence": round(step4["confidence"], 3),
            "rescued": rescued,
        }
        per_entity.append(row)
        if outcome == "noise":
            continue
        key = (_OUTCOME_RANK[outcome], step4["confidence"])
        if key > (_OUTCOME_RANK[best["outcome"]], best["confidence"]):
            best = {"outcome": outcome, "artifact_type": step4["artifact_type"],
                    "confidence": step4["confidence"]}
    return {**best, "entities": per_entity}


def build_full_pipeline(config: dict | None = None) -> Callable[[str], list[dict]]:
    """
    Return text -> typed entities, running Steps 1–3 the way run_loop does
    (no LLM for System 2). Imports models lazily so signals mode and tests
    never need them.
    """
    from campy.brain.hippocampus.graph import embeddings as emb
    from campy.brain.hippocampus.schema import _parse_seed_examples
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    from campy.brain.temporal_lobe.loop.step2_gist import classify_concept
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org

    config = config or {}
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2")
    spacy_model = config.get("spacy_model", "en_core_web_md")
    seed_path = Path(__file__).resolve().parents[2] / "campy" / "data" / "GistSeedExamples.md"

    # Fresh-install centroids: same computation as schema._bootstrap_centroids.
    centroids: dict[str, list[float]] = {}
    for class_name, sentences in _parse_seed_examples(str(seed_path)).items():
        if not sentences:
            continue
        centroid = emb.mean_pool(emb.embed_batch(sentences, model_name=embedding_model))
        norm = sum(v * v for v in centroid) ** 0.5
        centroids[class_name] = [v / norm for v in centroid] if norm > 0 else centroid

    def typed_entities(text: str) -> list[dict]:
        _doc, entities = extract_entities(text, model_name=spacy_model)
        typed = []
        for entity in entities:
            gist = classify_concept(entity["text"], embedding_model, centroids,
                                    llm_client=None, context=text)
            if gist["system"] == "noise":
                continue
            schema = route_to_schema_org(gist["gist_class"], entity.get("label"))
            typed.append({**entity, "gist_class": gist["gist_class"],
                          "schema_org_type": schema["schema_org_type"]})
        return typed

    return typed_entities


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _prf(pred: list[str], gold: list[str], label: str) -> dict:
    tp = sum(1 for p, g in zip(pred, gold) if p == label and g == label)
    fp = sum(1 for p, g in zip(pred, gold) if p == label and g != label)
    fn = sum(1 for p, g in zip(pred, gold) if p != label and g == label)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"precision": precision, "recall": recall, "support": tp + fn, "predicted": tp + fp}


def score_full(items: list[dict], results: list[dict]) -> dict:
    """Metrics for full mode. results[i] is decide_message() for items[i]."""
    gold = [it["label"] for it in items]
    # What the graph ends up with as a confirmed artifact.
    reified = [r["artifact_type"] if r["outcome"] == "reified" else "none" for r in results]
    # Type of whatever was stored (tentative or reified).
    stored = [r["artifact_type"] if r["outcome"] != "noise" else "none" for r in results]

    pos = [i for i, g in enumerate(gold) if g != "none"]
    neg = [i for i, g in enumerate(gold) if g == "none"]

    bins = []
    for lo, hi in RELIABILITY_BINS:
        idx = [i for i, r in enumerate(results)
               if r["outcome"] != "noise" and lo <= r["confidence"] < hi]
        correct = sum(1 for i in idx if results[i]["artifact_type"] == gold[i])
        bins.append({"bin": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(idx),
                     "accuracy": correct / len(idx) if idx else None,
                     "mean_confidence": (sum(results[i]["confidence"] for i in idx) / len(idx)
                                         if idx else None)})

    by_probe: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        by_probe[it["probe"]].append(i)

    return {
        "n": len(items),
        "reified_accuracy": sum(p == g for p, g in zip(reified, gold)) / len(gold),
        "reified_per_category": {c: _prf(reified, gold, c) for c in CATEGORIES},
        "stored_type_accuracy_on_positives":
            sum(stored[i] == gold[i] for i in pos) / len(pos) if pos else None,
        "false_save_rate": sum(reified[i] != "none" for i in neg) / len(neg) if neg else None,
        "false_store_rate": sum(stored[i] != "none" for i in neg) / len(neg) if neg else None,
        "missed_save_rate": sum(stored[i] == "none" for i in pos) / len(pos) if pos else None,
        "reliability": bins,
        "reified_accuracy_by_probe": {
            p: {"n": len(ix), "accuracy": sum(reified[i] == gold[i] for i in ix) / len(ix)}
            for p, ix in sorted(by_probe.items())
        },
        "confusion_reified": dict(Counter(f"{g}->{p}" for p, g in zip(reified, gold))),
    }


def keyword_type(text: str) -> tuple[str | None, int]:
    """Step 4's keyword decision: (artifact_type, hits), or (None, 0) if no signal fires."""
    scores = signal_scores(text)
    best = max(scores, key=lambda k: scores[k])
    return (best, scores[best]) if scores[best] > 0 else (None, 0)


def score_signals(items: list[dict]) -> dict:
    """Metrics for signals mode (no models)."""
    rows = []
    for it in items:
        ktype, hits = keyword_type(it["text"])
        rows.append({"id": it["id"], "gold": it["label"], "probe": it["probe"],
                     "keyword_type": ktype, "hits": hits,
                     # classify_artifact's keyword confidence before the gist
                     # agreement boost (+0.10) and single-token cap.
                     "base_confidence": min(0.67 + hits * 0.15, 0.97) if hits else None})

    fired = [r for r in rows if r["keyword_type"]]
    by_gold: dict[str, dict] = {}
    for c in CATEGORIES:
        g_rows = [r for r in rows if r["gold"] == c]
        g_fired = [r for r in g_rows if r["keyword_type"]]
        by_gold[c] = {
            "n": len(g_rows),
            "keywords_fired": len(g_fired),
            "keyword_type_correct": sum(r["keyword_type"] == c for r in g_fired),
        }
    none_fired = [r for r in fired if r["gold"] == "none"]
    by_probe: dict[str, dict] = {}
    for p in sorted({r["probe"] for r in rows}):
        p_rows = [r for r in rows if r["probe"] == p]
        by_probe[p] = {"n": len(p_rows),
                       "keywords_fired": sum(1 for r in p_rows if r["keyword_type"]),
                       "keyword_type_correct": sum(r["keyword_type"] == r["gold"] for r in p_rows)}
    return {
        "n": len(rows),
        "coverage": len(fired) / len(rows),
        "keyword_type_accuracy_when_fired":
            sum(r["keyword_type"] == r["gold"] for r in fired) / len(fired) if fired else None,
        "by_gold_label": by_gold,
        "none_items_where_keywords_fired": len(none_fired),
        "none_items_that_would_proceed": len(none_fired),  # every keyword hit is >= 0.82 > NOISE_FLOOR
        "by_probe": by_probe,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _pct(x) -> str:
    return "  n/a" if x is None else f"{100 * x:5.1f}%"


def format_signals(m: dict) -> str:
    out = [f"Save-gate baseline — signals mode (Step 4 keyword layer), n={m['n']}",
           f"  keywords fire on            {_pct(m['coverage'])} of statements",
           f"  type correct when they fire {_pct(m['keyword_type_accuracy_when_fired'])}",
           f"  'none' statements where keywords fire (each clears NOISE_FLOOR={NOISE_FLOOR}): "
           f"{m['none_items_where_keywords_fired']}/{m['by_gold_label']['none']['n']}",
           "", "  by gold label:      n  fired  type-correct"]
    for c, v in m["by_gold_label"].items():
        out.append(f"    {c:<14} {v['n']:4d}  {v['keywords_fired']:5d}  {v['keyword_type_correct']:5d}")
    out += ["", "  by probe:          n  fired  type-correct"]
    for p, v in m["by_probe"].items():
        out.append(f"    {p:<14} {v['n']:4d}  {v['keywords_fired']:5d}  {v['keyword_type_correct']:5d}")
    return "\n".join(out)


def format_full(m: dict) -> str:
    out = [f"Save-gate baseline — full mode (Steps 1–4, no LLM), n={m['n']}",
           f"  reified-type accuracy (HARD_LOCK={HARD_LOCK}) {_pct(m['reified_accuracy'])}",
           f"  false-save rate  (gold none -> reified)      {_pct(m['false_save_rate'])}",
           f"  false-store rate (gold none -> any node)     {_pct(m['false_store_rate'])}",
           f"  missed-save rate (gold type -> nothing)      {_pct(m['missed_save_rate'])}",
           f"  stored type correct on positives             {_pct(m['stored_type_accuracy_on_positives'])}",
           "", "  reified, per category:  precision  recall  support  predicted"]
    for c, v in m["reified_per_category"].items():
        out.append(f"    {c:<20} {_pct(v['precision'])}  {_pct(v['recall'])}  "
                   f"{v['support']:7d}  {v['predicted']:9d}")
    out += ["", "  reliability (stored items): bin        n  mean-conf  accuracy"]
    for b in m["reliability"]:
        mc = "  n/a" if b["mean_confidence"] is None else f"{b['mean_confidence']:.2f}"
        out.append(f"    {b['bin']:<26} {b['n']:4d}  {mc:>9}  {_pct(b['accuracy'])}")
    out += ["", "  reified accuracy by probe:"]
    for p, v in m["reified_accuracy_by_probe"].items():
        out.append(f"    {p:<14} n={v['n']:3d}  {_pct(v['accuracy'])}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("signals", "full"), default="signals")
    ap.add_argument("--json", help="write metrics (and per-item rows) to this path")
    ap.add_argument("--gate-model", help="full mode: score Step 4 with this B460 gate model "
                                         "(train_gate.py --out) instead of keyword counts")
    args = ap.parse_args(argv)
    if args.gate_model and args.mode != "full":
        ap.error("--gate-model needs --mode full")

    items = load_gold()
    if args.mode == "signals":
        metrics = score_signals(items)
        print(format_signals(metrics))
    else:
        pipeline = build_full_pipeline()
        gate_model, embed = None, None
        if args.gate_model:
            from campy.brain.hippocampus.graph import embeddings as emb
            from campy.brain.temporal_lobe.save_gate_model import GateModel
            gate_model, embed = GateModel.load(args.gate_model), emb.embed
        results = [decide_message(it["text"], pipeline(it["text"]), gate_model=gate_model, embed=embed)
                   for it in items]
        metrics = score_full(items, results)
        metrics["rows"] = [{"id": it["id"], "gold": it["label"], **r}
                           for it, r in zip(items, results)]
        print(format_full(metrics))

    if args.json:
        Path(args.json).write_text(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
