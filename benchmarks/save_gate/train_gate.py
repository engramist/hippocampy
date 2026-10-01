"""
B460 item 1 — train, calibrate and evaluate the Step 4 gate model.

Trains campy.brain.temporal_lobe.save_gate_model.GateModel (multinomial
logistic regression + temperature scaling) on the B462 labeled set and
reports how it would gate, scored with the same function as the full-mode
baseline (run_baseline.score_full), so the two reports line up.

Evaluation is nested cross-validation: each outer fold's model and its
temperature are fitted without that fold, so every reported prediction is
held out, calibration included. The saved model is then trained on all
items, with the temperature fitted on k-fold held-out logits.

Pipelines:
  none   one row per statement, features from the statement text alone
         (hashed n-grams + keyword signals). Needs no models.
  full   Steps 1–3 as in run_baseline full mode (spaCy + embedding model):
         one row per typed entity, labelled with its statement's label, so
         the model can also use the gist class and sentence embedding.

Usage:
  python -m benchmarks.save_gate.train_gate                       # report only
  python -m benchmarks.save_gate.train_gate --out gate_model.json # + save model
  python -m benchmarks.save_gate.train_gate --pipeline full --features ngrams,signals,gist,embedding

Then set `[save_gate] model_path` in campy.toml to use the model in the Loop.
Read the report's caveat before doing that: the labeled set is small and
author-written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from benchmarks.save_gate.run_baseline import (
    GOLD_PATH,
    _pct,
    format_full,
    load_gold,
    score_full,
)
from campy.brain.temporal_lobe.loop.step4_pattern import HARD_LOCK, NOISE_FLOOR, entity_sentence
from campy.brain.temporal_lobe.save_gate_model import (
    ARTIFACT_LABELS,
    LABELS,
    FeatureSpec,
    GateModel,
    featurize,
)

CAVEAT = ("The labels are author-written (B462 gold.yaml, n≈150, needs owner review). "
          "Held-out numbers measure fit to that set's phrasing, not real sessions.")


@dataclass
class Row:
    item: int                 # index into the gold items
    text: str                 # the entity's sentence (pipeline none: the statement)
    gist: str | None = None
    embedding: list[float] | None = None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def build_rows(items: list[dict], spec: FeatureSpec, pipeline: str) -> list[Row]:
    if pipeline == "none":
        return [Row(i, it["text"]) for i, it in enumerate(items)]
    from benchmarks.save_gate.run_baseline import build_full_pipeline
    from campy.brain.hippocampus.graph import embeddings as emb

    typed_entities = build_full_pipeline()
    rows = []
    for i, it in enumerate(items):
        for ent in typed_entities(it["text"]):
            sentence = entity_sentence(it["text"], ent["text"])
            rows.append(Row(i, sentence, ent.get("gist_class"),
                            emb.embed(sentence) if spec.embedding else None))
    return rows


def matrix(rows: list[Row], spec: FeatureSpec) -> np.ndarray:
    X = np.zeros((len(rows), spec.size))
    for r, row in enumerate(rows):
        for j, v in featurize(row.text, spec, row.gist, row.embedding).items():
            X[r, j] = v
    return X


# ---------------------------------------------------------------------------
# Model fitting
# ---------------------------------------------------------------------------

def _softmax(Z: np.ndarray) -> np.ndarray:
    Z = Z - Z.max(axis=1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(axis=1, keepdims=True)


def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float, iters: int = 3000,
               lr: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Mean cross-entropy + l2/2·||W||², full-batch Adam. Returns (W [K×d], b [K])."""
    n, d = X.shape
    K = len(LABELS)
    Y = np.eye(K)[y]
    W, b = np.zeros((d, K)), np.zeros(K)
    mW, vW, mb, vb = (np.zeros_like(W), np.zeros_like(W), np.zeros_like(b), np.zeros_like(b))
    b1, b2, eps = 0.9, 0.999, 1e-8
    for t in range(1, iters + 1):
        G = (_softmax(X @ W + b) - Y) / n
        gW, gb = X.T @ G + l2 * W, G.sum(axis=0)
        mW, vW = b1 * mW + (1 - b1) * gW, b2 * vW + (1 - b2) * gW ** 2
        mb, vb = b1 * mb + (1 - b1) * gb, b2 * vb + (1 - b2) * gb ** 2
        W -= lr * (mW / (1 - b1 ** t)) / (np.sqrt(vW / (1 - b2 ** t)) + eps)
        b -= lr * (mb / (1 - b1 ** t)) / (np.sqrt(vb / (1 - b2 ** t)) + eps)
    return W.T.copy(), b


def nll(Z: np.ndarray, y: np.ndarray, T: float) -> float:
    P = _softmax(Z / T)
    return float(-np.mean(np.log(P[np.arange(len(y)), y] + 1e-12)))


def fit_temperature(Z: np.ndarray, y: np.ndarray) -> float:
    """T minimising held-out NLL (golden-section search on log T in [-3, 3])."""
    lo, hi = -3.0, 3.0
    g = (5 ** 0.5 - 1) / 2
    for _ in range(80):
        a, c = hi - g * (hi - lo), lo + g * (hi - lo)
        if nll(Z, y, np.exp(a)) < nll(Z, y, np.exp(c)):
            hi = c
        else:
            lo = a
    return float(np.exp((lo + hi) / 2))


def item_folds(items: list[dict], k: int, seed: int, subset: list[int] | None = None) -> list[list[int]]:
    """Stratified (by label) item-index folds."""
    idx = subset if subset is not None else list(range(len(items)))
    rng = np.random.default_rng(seed)
    folds: list[list[int]] = [[] for _ in range(k)]
    for label in LABELS:
        members = [i for i in idx if items[i]["label"] == label]
        rng.shuffle(members)
        for j, i in enumerate(members):
            folds[j % k].append(i)
    return [f for f in folds if f]


def _oof_logits(X, y, row_items, items, train_items, k, seed, l2) -> np.ndarray:
    """Held-out logits for every row of `train_items`, by k-fold over those items."""
    Z = np.full((len(y), len(LABELS)), np.nan)
    for fold in item_folds(items, k, seed, train_items):
        test = np.isin(row_items, fold)
        train = np.isin(row_items, train_items) & ~test
        W, b = fit_logreg(X[train], y[train], l2)
        Z[test] = X[test] @ W.T + b
    return Z


def nested_cv(X, y, row_items, items, k: int, seed: int, l2: float) -> tuple[np.ndarray, list[float]]:
    """Calibrated held-out probabilities for every row, and each outer fold's T."""
    P = np.zeros((len(y), len(LABELS)))
    temps = []
    for fold in item_folds(items, k, seed):
        train_items = [i for i in range(len(items)) if i not in set(fold)]
        inner = _oof_logits(X, y, row_items, items, train_items, k, seed + 1, l2)
        tr = np.isin(row_items, train_items)
        T = fit_temperature(inner[tr], y[tr])
        W, b = fit_logreg(X[tr], y[tr], l2)
        test = np.isin(row_items, fold)
        P[test] = _softmax((X[test] @ W.T + b) / T)
        temps.append(T)
    return P, temps


# ---------------------------------------------------------------------------
# Evaluation (same scoring as the full-mode baseline)
# ---------------------------------------------------------------------------

def gate_results(P: np.ndarray, row_items: np.ndarray, n_items: int) -> list[dict]:
    """Step 4's decision per item from model probabilities (user role, no
    rescue): the strongest entity outcome, as run_baseline.decide_message."""
    rank = {"noise": 0, "tentative": 1, "reified": 2}
    results = [{"outcome": "noise", "artifact_type": "none", "confidence": 0.0}
               for _ in range(n_items)]
    for p, i in zip(P, row_items):
        probs = dict(zip(LABELS, p))
        art = max(ARTIFACT_LABELS, key=probs.get)
        conf = float(probs[art])
        outcome = "reified" if conf >= HARD_LOCK else "tentative" if conf >= NOISE_FLOOR else "noise"
        best = results[i]
        if outcome != "noise" and (rank[outcome], conf) > (rank[best["outcome"]], best["confidence"]):
            results[i] = {"outcome": outcome, "artifact_type": art, "confidence": conf}
    return results


def calibration(P: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    """Top-label reliability over all rows (5-way) and expected calibration error."""
    conf, pred = P.max(axis=1), P.argmax(axis=1)
    correct = (pred == y).astype(float)
    table, ece = [], 0.0
    for lo in np.linspace(0, 1, bins, endpoint=False):
        m = (conf >= lo) & (conf < lo + 1 / bins + (1e-9 if lo + 1 / bins >= 1 else 0))
        if m.any():
            gap = abs(conf[m].mean() - correct[m].mean())
            ece += m.mean() * gap
            table.append({"bin": f"{lo:.1f}-{lo + 1 / bins:.1f}", "n": int(m.sum()),
                          "mean_confidence": float(conf[m].mean()), "accuracy": float(correct[m].mean())})
    return {"accuracy": float(correct.mean()), "ece": float(ece), "nll": nll(np.log(P + 1e-12), y, 1.0),
            "reliability": table}


def acceptance(metrics: dict, min_n: int = 10) -> dict:
    """B460's reliability criterion: max |confidence - accuracy| <= 0.10 over
    stored-item bins with >= min_n items."""
    gaps = [abs(b["mean_confidence"] - b["accuracy"]) for b in metrics["reliability"]
            if b["n"] >= min_n and b["accuracy"] is not None]
    return {"bins_checked": len(gaps), "max_gap": max(gaps) if gaps else None,
            "passes": bool(gaps) and max(gaps) <= 0.10}


def format_report(m: dict) -> str:
    cal, acc = m["calibration"], m["acceptance"]
    gap = "n/a" if acc["max_gap"] is None else f"{acc['max_gap']:.3f}"
    out = [f"Gate model — nested {m['folds']}-fold CV, pipeline={m['pipeline']}, "
           f"features={m['features']}, l2={m['l2']}",
           f"  rows={m['rows']}  temperatures per outer fold: "
           + ", ".join(f"{t:.2f}" for t in m["temperatures"]),
           f"  5-way accuracy {_pct(cal['accuracy'])}   ECE {cal['ece']:.3f}   NLL {cal['nll']:.3f}",
           f"  B460 reliability criterion (stored bins with n>=10, max gap <= 0.10): "
           f"{'PASS' if acc['passes'] else 'FAIL'} (bins={acc['bins_checked']}, max gap={gap})",
           "", "  top-label reliability, all rows: bin      n  mean-conf  accuracy"]
    for b in cal["reliability"]:
        out.append(f"    {b['bin']:<28} {b['n']:4d}  {b['mean_confidence']:9.2f}  {_pct(b['accuracy'])}")
    out += ["", format_full(m["gate"]), "", f"NOTE: {CAVEAT}"]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def feature_names(spec: FeatureSpec) -> str:
    return ",".join(n for n, on in (("ngrams", spec.ngram_dims > 0), ("signals", spec.signals),
                                    ("gist", spec.gist), ("embedding", spec.embedding)) if on)


def parse_features(s: str) -> FeatureSpec:
    parts = {p.strip() for p in s.split(",") if p.strip()}
    unknown = parts - {"ngrams", "signals", "gist", "embedding"}
    if unknown:
        raise SystemExit(f"unknown features: {sorted(unknown)}")
    return FeatureSpec(ngram_dims=1024 if "ngrams" in parts else 0, signals="signals" in parts,
                       gist="gist" in parts, embedding="embedding" in parts)


def run(items: list[dict], spec: FeatureSpec, pipeline: str = "none", folds: int = 5,
        seed: int = 0, l2: float = 0.01) -> tuple[dict, GateModel]:
    rows = build_rows(items, spec, pipeline)
    if not rows:
        raise SystemExit("no training rows (the pipeline found no entities)")
    X = matrix(rows, spec)
    y = np.array([LABELS.index(items[r.item]["label"]) for r in rows])
    row_items = np.array([r.item for r in rows])

    P, temps = nested_cv(X, y, row_items, items, folds, seed, l2)
    gate = score_full(items, gate_results(P, row_items, len(items)))
    metrics = {"pipeline": pipeline, "features": feature_names(spec),
               "l2": l2, "folds": folds, "seed": seed, "rows": len(rows), "temperatures": temps,
               "calibration": calibration(P, y), "gate": gate, "acceptance": acceptance(gate),
               "caveat": CAVEAT}

    all_items = list(range(len(items)))
    T = fit_temperature(_oof_logits(X, y, row_items, items, all_items, folds, seed, l2), y)
    W, b = fit_logreg(X, y, l2)
    model = GateModel(spec, W.tolist(), b.tolist(), T, metadata={
        "trained_on": f"{GOLD_PATH.name} sha256:{hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest()[:16]}",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline": pipeline, "items": len(items), "rows": len(rows), "l2": l2,
        "cv": {"accuracy": metrics["calibration"]["accuracy"], "ece": metrics["calibration"]["ece"],
               "reified_accuracy": gate["reified_accuracy"], "false_save_rate": gate["false_save_rate"],
               "reliability_criterion": metrics["acceptance"]},
        "caveat": CAVEAT,
    })
    return metrics, model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pipeline", choices=("none", "full"), default="none")
    ap.add_argument("--features", default="ngrams,signals",
                    help="comma list of ngrams, signals, gist, embedding (gist/embedding need --pipeline full)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--l2", type=float, default=0.01)
    ap.add_argument("--out", help="save the model trained on all items to this path")
    ap.add_argument("--json", help="write the CV report to this path")
    args = ap.parse_args(argv)

    spec = parse_features(args.features)
    if (spec.gist or spec.embedding) and args.pipeline != "full":
        ap.error("gist and embedding features need --pipeline full")
    metrics, model = run(load_gold(), spec, args.pipeline, args.folds, args.seed, args.l2)
    print(format_report(metrics))
    if args.json:
        Path(args.json).write_text(json.dumps(metrics, indent=2))
    if args.out:
        model.save(args.out)
        print(f"\nSaved model to {args.out} (temperature {model.temperature:.2f}). "
              "Use it with [save_gate] model_path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
