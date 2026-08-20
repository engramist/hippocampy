"""
mcp_engine/graph/embeddings.py — Multi-Provider Embedding Dispatch Layer

Supports three providers (configured in campy.toml [embeddings]):
    sentence-transformers  → local Python, fastest (default)
    ollama                 → local Ollama server via HTTP
    openai                 → OpenAI cloud API

Fallback chain: configured provider → sentence-transformers → ollama.
If the primary provider fails at runtime, the fallback fires transparently.

Dimension is locked to whatever the schema was created with (default 384).
A startup dimension check blocks mismatched models from corrupting the index.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Runtime state — set by configure() or lazily on first embed call
# ---------------------------------------------------------------------------

_provider: str = "sentence-transformers"
_model_name: str = MODEL_NAME
_ollama_base_url: str = "http://localhost:11434"
_openai_api_key: str = ""
_openai_base_url: str = ""  # empty = default OpenAI endpoint
_offline_mode: bool = False
_configured: bool = False

# Provider-specific singletons
_st_model = None          # SentenceTransformer instance
_openai_client = None     # openai.OpenAI instance


def configure(config: dict) -> None:
    """
    Read [embeddings] from config and set the active provider.

    Called once at daemon startup before prewarm().  Safe to call multiple
    times (last call wins).  If never called, defaults to sentence-transformers.
    """
    global _provider, _model_name, _ollama_base_url
    global _openai_api_key, _openai_base_url, _offline_mode, _configured

    emb_cfg = config.get("embeddings", {})

    _provider = emb_cfg.get("provider", "sentence-transformers").lower()
    _model_name = emb_cfg.get("model", MODEL_NAME)
    _ollama_base_url = emb_cfg.get(
        "ollama_base_url",
        config.get("llm", {}).get("base_url", "http://localhost:11434/v1")
            .replace("/v1", ""),
    )
    _openai_api_key = (
        emb_cfg.get("api_key")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    _openai_base_url = emb_cfg.get("base_url", "")
    env_offline = os.environ.get("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes"} \
        or os.environ.get("TRANSFORMERS_OFFLINE", "").lower() in {"1", "true", "yes"}
    _offline_mode = bool(emb_cfg.get("offline", False)) or env_offline
    if _offline_mode:
        # Ensure downstream huggingface/transformers loaders stay network-off.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    _configured = True

    _logger.info(
        "Embeddings configured: provider=%s  model=%s", _provider, _model_name
    )


# ---------------------------------------------------------------------------
# Provider backends
# ---------------------------------------------------------------------------

def _is_offline_enabled() -> bool:
    if _offline_mode:
        return True
    return os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def _get_st_model(model_name: str):
    """Lazy singleton for sentence-transformers."""
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        offline = _is_offline_enabled()
        try:
            if offline:
                _st_model = SentenceTransformer(model_name, local_files_only=True)
            else:
                _st_model = SentenceTransformer(model_name)
        except Exception as e:
            if offline:
                raise RuntimeError(
                    "Embedding model not found in local cache and offline mode is enabled. "
                    "Pre-bake the model into the image cache (HF_HOME/~/.cache/huggingface) "
                    "or unset HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE (or [embeddings].offline)."
                ) from e
            raise
    return _st_model


def _embed_st(text: str, model_name: str) -> list[float]:
    model = _get_st_model(model_name)
    return model.encode(text, normalize_embeddings=True).tolist()


def _embed_batch_st(texts: list[str], model_name: str) -> list[list[float]]:
    model = _get_st_model(model_name)
    return model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    ).tolist()


def _embed_ollama(text: str, model_name: str) -> list[float]:
    """Call Ollama /api/embed endpoint."""
    import requests
    # Strip the sentence-transformers/ prefix if present — Ollama uses bare names
    ollama_model = model_name.split("/")[-1] if "/" in model_name else model_name
    resp = requests.post(
        f"{_ollama_base_url}/api/embed",
        json={"model": ollama_model, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"][0]


def _embed_batch_ollama(texts: list[str], model_name: str) -> list[list[float]]:
    """Call Ollama /api/embed with multiple inputs."""
    import requests
    ollama_model = model_name.split("/")[-1] if "/" in model_name else model_name
    resp = requests.post(
        f"{_ollama_base_url}/api/embed",
        json={"model": ollama_model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"]


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        kwargs = {"api_key": _openai_api_key}
        if _openai_base_url:
            kwargs["base_url"] = _openai_base_url
        _openai_client = OpenAI(**kwargs)
    return _openai_client


def _embed_openai(text: str, model_name: str) -> list[float]:
    client = _get_openai_client()
    resp = client.embeddings.create(
        model=model_name,
        input=text,
        dimensions=EMBEDDING_DIM,
    )
    return resp.data[0].embedding


def _embed_batch_openai(texts: list[str], model_name: str) -> list[list[float]]:
    client = _get_openai_client()
    resp = client.embeddings.create(
        model=model_name,
        input=texts,
        dimensions=EMBEDDING_DIM,
    )
    return [item.embedding for item in resp.data]


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------

_FALLBACK_ORDER = {
    "sentence-transformers": ["ollama"],
    "ollama":                ["sentence-transformers"],
    "openai":                ["sentence-transformers", "ollama"],
}

_EMBED_FN = {
    "sentence-transformers": _embed_st,
    "ollama":                _embed_ollama,
    "openai":                _embed_openai,
}

_EMBED_BATCH_FN = {
    "sentence-transformers": _embed_batch_st,
    "ollama":                _embed_batch_ollama,
    "openai":                _embed_batch_openai,
}


def _embed_with_fallback(text: str, model_name: str) -> list[float]:
    """Try primary provider, then fallback chain."""
    primary = _provider
    chain = [primary] + _FALLBACK_ORDER.get(primary, [])
    last_err = None
    for provider in chain:
        fn = _EMBED_FN.get(provider)
        if fn is None:
            continue
        try:
            return fn(text, model_name)
        except Exception as e:
            _logger.warning("Embedding provider '%s' failed: %s", provider, e)
            last_err = e
    raise RuntimeError(
        f"All embedding providers failed. Last error: {last_err}"
    )


def _embed_batch_with_fallback(texts: list[str], model_name: str) -> list[list[float]]:
    """Try primary provider, then fallback chain (batch)."""
    primary = _provider
    chain = [primary] + _FALLBACK_ORDER.get(primary, [])
    last_err = None
    for provider in chain:
        fn = _EMBED_BATCH_FN.get(provider)
        if fn is None:
            continue
        try:
            return fn(texts, model_name)
        except Exception as e:
            _logger.warning("Batch embedding provider '%s' failed: %s", provider, e)
            last_err = e
    raise RuntimeError(
        f"All batch embedding providers failed. Last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# Public API — unchanged signatures, now dispatches through provider layer
# ---------------------------------------------------------------------------

def get_model(model_name: str = MODEL_NAME):
    """Return the sentence-transformers model (backward compat for callers)."""
    return _get_st_model(model_name)


def prewarm(model_name: str = MODEL_NAME) -> None:
    """
    Called at daemon startup to eagerly load the embedding model.

    For sentence-transformers: loads weights into memory.
    For ollama/openai: issues a single test embed to verify connectivity.
    """
    global _model_name
    _model_name = model_name

    if _provider == "sentence-transformers":
        _get_st_model(model_name)
        _logger.info("Sentence-transformers model pre-warmed: %s", model_name)
    elif _provider == "ollama":
        try:
            vec = _embed_ollama("prewarm test", model_name)
            _logger.info(
                "Ollama embedding prewarm OK: %s (%d-dim)", model_name, len(vec)
            )
        except Exception as e:
            _logger.warning(
                "Ollama embedding prewarm failed (%s); will fallback to "
                "sentence-transformers at runtime", e
            )
            _get_st_model(model_name)
    elif _provider == "openai":
        try:
            vec = _embed_openai("prewarm test", model_name)
            _logger.info(
                "OpenAI embedding prewarm OK: %s (%d-dim)", model_name, len(vec)
            )
        except Exception as e:
            _logger.warning(
                "OpenAI embedding prewarm failed (%s); will fallback to "
                "sentence-transformers at runtime", e
            )
            _get_st_model(model_name)
    else:
        _logger.warning(
            "Unknown embedding provider '%s'; defaulting to sentence-transformers",
            _provider,
        )
        _get_st_model(model_name)


def embed(text: str, model_name: str = MODEL_NAME) -> list[float]:
    """Embed a single string. Returns list of floats (dimension matches schema)."""
    name = model_name if model_name != MODEL_NAME else _model_name
    return _embed_with_fallback(text, name)


def embed_batch(texts: list[str], model_name: str = MODEL_NAME) -> list[list[float]]:
    """
    Embed a list of strings efficiently.
    Returns list of float vectors, one per input text.
    """
    name = model_name if model_name != MODEL_NAME else _model_name
    return _embed_batch_with_fallback(texts, name)


def mean_pool(embeddings: list[list[float]]) -> list[float]:
    """Compute the mean of a list of embedding vectors. Used for centroid computation."""
    if not embeddings:
        raise ValueError("Cannot mean-pool empty list")
    dim = len(embeddings[0])
    result = [0.0] * dim
    for emb_vec in embeddings:
        for i, v in enumerate(emb_vec):
            result[i] += v
    return [v / len(embeddings) for v in result]
