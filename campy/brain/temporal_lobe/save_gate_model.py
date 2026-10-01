"""
B460 item 1 — learned, calibrated Step 4 save-gate classifier.

Step 4's confidence today is `0.67 + 0.15 * keyword_hits` plus hand-set gist
priors: a score, not a probability. This module replaces that score with
the probability of each category in campy/data/artifact_categories.yaml
(decision, constraint, requirement, action_item, none), so the thresholds
stacked on it can mean what they say (HARD_LOCK = 0.90 → ~90% of reified
artifacts are the right type).

The model is a multinomial logistic regression over features the Loop
already has, with a temperature fitted on held-out predictions:

  * keyword signals: Step 4's regex hit counts, as features, not the score;
  * hashed word unigrams and bigrams of the entity's sentence (no model to
    download, no vocabulary file);
  * optionally the entity's gist class (Step 2) and the sentence embedding,
    when the model was trained with them.

Training, calibration and evaluation live in benchmarks/save_gate/
train_gate.py (numpy). This module only featurizes and predicts, in pure
Python, so the daemon gains no dependency.

The model is a file artifact (JSON), not agent state: it is loaded from
`[save_gate] model_path` and parsed once per path and mtime. No path configured,
or an unreadable file, means Step 4 behaves exactly as before.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from campy.brain.temporal_lobe.loop.step4_pattern import signal_scores

_logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
LABELS = ("decision", "constraint", "requirement", "action_item", "none")
ARTIFACT_LABELS = LABELS[:4]
# Step 2's classes (step2_gist.GIST_CLASSES; a test keeps them in sync).
GIST_FEATURE_CLASSES = ("Restriction", "PlannedEvent", "PhysicalThing",
                        "Magnitude", "Category", "Agent", "Event")
EMBEDDING_DIM = 384
_SIGNAL_TYPES = ("decision", "constraint", "requirement", "action_item")
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


@dataclass(frozen=True)
class FeatureSpec:
    ngram_dims: int = 1024      # hashed unigrams + bigrams; 0 disables
    signals: bool = True        # Step 4 keyword hit counts
    gist: bool = False          # one-hot Step 2 gist class
    embedding: bool = False     # 384-d sentence embedding

    @property
    def size(self) -> int:
        return (self.ngram_dims
                + (2 * len(_SIGNAL_TYPES) if self.signals else 0)
                + (len(GIST_FEATURE_CLASSES) + 1 if self.gist else 0)
                + (EMBEDDING_DIM if self.embedding else 0))

    def to_dict(self) -> dict:
        return {"ngram_dims": self.ngram_dims, "signals": self.signals,
                "gist": self.gist, "embedding": self.embedding}

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureSpec":
        return cls(int(d.get("ngram_dims", 1024)), bool(d.get("signals", True)),
                   bool(d.get("gist", False)), bool(d.get("embedding", False)))


def tokens(text: str) -> list[str]:
    words = _TOKEN.findall(text.lower())
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


def _bucket(token: str, dims: int) -> int:
    return zlib.crc32(token.encode("utf-8")) % dims


def featurize(text: str, spec: FeatureSpec, gist_class: str | None = None,
              embedding: Sequence[float] | None = None) -> dict[int, float]:
    """Sparse feature vector {index: value} for one entity sentence."""
    x: dict[int, float] = {}
    off = 0
    if spec.ngram_dims:
        toks = set(tokens(text))
        if toks:
            v = 1.0 / math.sqrt(len(toks))  # L2-normalised presence
            for t in toks:
                i = _bucket(t, spec.ngram_dims)
                x[i] = x.get(i, 0.0) + v
        off += spec.ngram_dims
    if spec.signals:
        scores = signal_scores(text)
        for j, t in enumerate(_SIGNAL_TYPES):
            n = scores[t]
            if n:
                x[off + 2 * j] = min(n, 3) / 3.0
                x[off + 2 * j + 1] = 1.0
        off += 2 * len(_SIGNAL_TYPES)
    if spec.gist:
        j = (GIST_FEATURE_CLASSES.index(gist_class)
             if gist_class in GIST_FEATURE_CLASSES else len(GIST_FEATURE_CLASSES))
        x[off + j] = 1.0
        off += len(GIST_FEATURE_CLASSES) + 1
    if spec.embedding:
        if embedding is None or len(embedding) != EMBEDDING_DIM:
            raise ValueError("this gate model needs a 384-d sentence embedding")
        for j, v in enumerate(embedding):
            if v:
                x[off + j] = float(v)
    return x


@dataclass
class GateModel:
    spec: FeatureSpec
    weights: list[list[float]]          # one row per label, spec.size columns
    bias: list[float]
    temperature: float = 1.0
    labels: tuple[str, ...] = LABELS
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if tuple(self.labels) != LABELS:
            raise ValueError(f"gate model labels {self.labels} != {LABELS}")
        if len(self.weights) != len(LABELS) or any(len(r) != self.spec.size for r in self.weights):
            raise ValueError("gate model weights do not match its feature spec")
        if not self.temperature > 0:
            raise ValueError("gate model temperature must be > 0")

    @property
    def needs_embedding(self) -> bool:
        return self.spec.embedding

    def predict_proba(self, text: str, gist_class: str | None = None,
                      embedding: Sequence[float] | None = None) -> dict[str, float]:
        x = featurize(text, self.spec, gist_class, embedding)
        logits = [(b + sum(row[i] * v for i, v in x.items())) / self.temperature
                  for row, b in zip(self.weights, self.bias)]
        m = max(logits)
        exps = [math.exp(z - m) for z in logits]
        total = sum(exps)
        return {label: e / total for label, e in zip(LABELS, exps)}

    def to_dict(self) -> dict:
        return {"format_version": FORMAT_VERSION, "labels": list(self.labels),
                "spec": self.spec.to_dict(), "temperature": self.temperature,
                "bias": self.bias, "weights": self.weights, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict) -> "GateModel":
        if d.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"unsupported gate model format {d.get('format_version')!r}")
        return cls(FeatureSpec.from_dict(d["spec"]), [list(map(float, r)) for r in d["weights"]],
                   [float(b) for b in d["bias"]], float(d["temperature"]),
                   tuple(d["labels"]), dict(d.get("metadata") or {}))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "GateModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=4)
def _load_file(path: str, mtime: float) -> GateModel | None:
    """Parse the model file once per (path, mtime); a changed file reloads.
    Holds no agent state: the file is the model."""
    try:
        model = GateModel.load(path)
        _logger.info("[Gate:Model] loaded %s (%s)", path, model.metadata.get("trained_on", "?"))
        return model
    except Exception as e:  # missing, unreadable, wrong format
        _logger.warning("[Gate:Model] not using %s: %s; Step 4 keeps keyword scoring", path, e)
        return None


def load_gate_model(config: dict | None) -> GateModel | None:
    """The configured gate model, or None (Step 4 then uses its keyword
    scoring). Never raises: a bad file is logged once and ignored."""
    path = ((config or {}).get("save_gate") or {}).get("model_path")
    if not path:
        return None
    path = os.path.expanduser(str(path))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = -1.0
    return _load_file(path, mtime)
