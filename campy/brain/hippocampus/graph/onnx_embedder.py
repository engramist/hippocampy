"""
onnx_embedder.py -- all-MiniLM-L6-v2 on ONNX Runtime, no fastembed (B512).

Reproduces, step for step, what ``fastembed.TextEmbedding`` did for
``sentence-transformers/all-MiniLM-L6-v2`` (fastembed 0.8.0), so the vectors
already indexed in the graph stay valid. B512 replaced fastembed because every
fastembed release caps ``pillow<13`` (37 advisories on pillow 12.3.0, B500)
and Campy embeds text only.

The pipeline, as read from fastembed 0.8.0:

* Files: HuggingFace repo ``qdrant/all-MiniLM-L6-v2-onnx`` -- ``model.onnx``,
  ``config.json``, ``tokenizer.json``, ``tokenizer_config.json`` and
  ``special_tokens_map.json`` (a third-party ONNX conversion of the same
  weights).
* Tokenizer: ``tokenizers.Tokenizer.from_file(tokenizer.json)``, truncation
  at ``tokenizer_config.json`` ``model_max_length`` (256), right-padding to the
  longest sequence in the batch with ``config.json`` ``pad_token_id`` (0).
* ONNX inputs: ``input_ids``, ``attention_mask``, ``token_type_ids`` (all
  zeros), int64. CPU execution provider, ``ORT_ENABLE_ALL`` graph
  optimisation, ONNX Runtime's default thread settings (fastembed only pins
  threads in its own worker processes, which Campy never used).
* Output: first model output (last hidden state, float32), masked mean
  pooling carried out in float64 (the float32 x int64 mask product promotes),
  then L2 normalisation (eps 1e-12). Result: float64, shape (n, 384).
* Batching: 256 texts per ONNX call (padding is per batch).

Cache / offline behaviour (also as fastembed): ``HF_HUB_OFFLINE`` in
{1, true, yes, on} or ``local_files_only=True`` means no network at all. The
local cache is always tried first. Where the files live:
``FASTEMBED_CACHE_PATH`` if set, else a cache that an earlier fastembed
install left in ``<tempdir>/fastembed_cache`` (reused, so existing installs do
not re-download), else the standard huggingface_hub cache (``HF_HOME``).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

#: HuggingFace repo holding the ONNX conversion of ``MODEL_NAME``.
_HF_REPO = "qdrant/all-MiniLM-L6-v2-onnx"
_MODEL_FILE = "model.onnx"
_FILES = (
    _MODEL_FILE,
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
_REQUIRED = (_MODEL_FILE, "config.json", "tokenizer.json", "tokenizer_config.json")
_DEFAULT_BATCH_SIZE = 256
_OFFLINE_VALUES = {"1", "TRUE", "YES", "ON"}


def _env_offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "").strip().upper() in _OFFLINE_VALUES


def _legacy_fastembed_cache() -> Path:
    return Path(tempfile.gettempdir()) / "fastembed_cache"


def _snapshot(cache_dir: Optional[str], local_files_only: bool) -> Path:
    """Resolve the model snapshot directory, raising if a file is missing."""
    from huggingface_hub import snapshot_download

    path = Path(
        snapshot_download(
            repo_id=_HF_REPO,
            allow_patterns=list(_FILES),
            cache_dir=cache_dir,
            local_files_only=local_files_only,
        )
    )
    missing = [f for f in _REQUIRED if not (path / f).exists()]
    if missing:
        raise FileNotFoundError(f"{_HF_REPO} snapshot at {path} is missing {missing}")
    return path


def resolve_model_dir(
    model_name: str = MODEL_NAME,
    local_files_only: bool = False,
    cache_dir: Optional[str] = None,
) -> Path:
    """Locate (downloading if allowed) the model files; see module docstring."""
    if model_name != MODEL_NAME:
        raise ValueError(
            f"Unsupported local embedding model {model_name!r}: this backend only "
            f"runs {MODEL_NAME!r} (the schema is FLOAT[{EMBEDDING_DIM}]). Use the "
            "ollama or openai embedding provider for other models."
        )
    offline = local_files_only or _env_offline()

    env_dir = os.environ.get("FASTEMBED_CACHE_PATH")
    if cache_dir is not None:
        candidates: list[Optional[str]] = [str(cache_dir)]
    elif env_dir:
        candidates = [env_dir]
    else:
        legacy = _legacy_fastembed_cache()
        candidates = ([str(legacy)] if legacy.is_dir() else []) + [None]

    last_err: Optional[Exception] = None
    for cand in candidates:
        try:
            return _snapshot(cand, local_files_only=True)
        except Exception as e:  # not cached there
            last_err = e
    if offline:
        raise FileNotFoundError(
            f"{_HF_REPO} is not in the local cache and offline mode is on"
        ) from last_err
    return _snapshot(candidates[-1], local_files_only=False)


def _load_tokenizer(model_dir: Path):
    from tokenizers import Tokenizer

    config = json.loads((model_dir / "config.json").read_text())
    tok_cfg = json.loads((model_dir / "tokenizer_config.json").read_text())
    lengths = [tok_cfg[k] for k in ("model_max_length", "max_length") if k in tok_cfg]
    if not lengths:
        raise ValueError("tokenizer_config.json has no model_max_length / max_length")
    tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=min(lengths))
    if not tokenizer.padding:
        tokenizer.enable_padding(
            pad_id=config.get("pad_token_id", 0), pad_token=tok_cfg["pad_token"]
        )
    return tokenizer


def _normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    norm = np.maximum(np.linalg.norm(x, ord=2, axis=1, keepdims=True), eps)
    return x / norm


def _mean_pool(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    # float32 hidden * int64 mask promotes to float64, as in fastembed.
    mask = np.expand_dims(attention_mask, axis=-1).astype(np.int64)
    mask = np.tile(mask, (1, 1, hidden.shape[-1]))
    return np.sum(hidden * mask, axis=1) / np.maximum(np.sum(mask, axis=1), 1e-9)


class OnnxTextEmbedder:
    """Drop-in for ``fastembed.TextEmbedding`` as Campy used it."""

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        local_files_only: bool = False,
        cache_dir: Optional[str] = None,
        threads: Optional[int] = None,
    ) -> None:
        import onnxruntime as ort

        self.model_name = model_name
        self.model_dir = resolve_model_dir(model_name, local_files_only, cache_dir)
        self.tokenizer = _load_tokenizer(self.model_dir)

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads is not None:
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(self.model_dir / _MODEL_FILE),
            providers=["CPUExecutionProvider"],
            sess_options=so,
        )
        self._input_names = {n.name for n in self.session.get_inputs()}

    def _embed_batch(self, texts: list[str]) -> np.ndarray:
        encoded = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {"input_ids": input_ids}
        if "attention_mask" in self._input_names:
            feed["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        hidden = self.session.run(None, feed)[0]
        return _normalize(_mean_pool(hidden, attention_mask))

    def embed(
        self, documents: "str | Iterable[str]", batch_size: int = _DEFAULT_BATCH_SIZE
    ) -> Iterable[np.ndarray]:
        """Yield one float64 vector of shape (384,) per document."""
        docs = [documents] if isinstance(documents, str) else list(documents)
        for start in range(0, len(docs), batch_size):
            yield from self._embed_batch(docs[start:start + batch_size])
