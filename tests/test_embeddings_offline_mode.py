from __future__ import annotations

import types

import pytest


class _FakeFEOk:
    last_local_files_only = None

    def __init__(self, model_name, local_files_only=False):
        _FakeFEOk.last_local_files_only = local_files_only


class _FakeFEMissing:
    def __init__(self, model_name, local_files_only=False):
        raise ValueError("model not found")


def _reset_embeddings_module(mod):
    mod._fe_model = None
    mod._offline_mode = False


def test_offline_mode_uses_local_files_only(monkeypatch):
    import campy.brain.hippocampus.graph.embeddings as emb

    _reset_embeddings_module(emb)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "fastembed",
        types.SimpleNamespace(TextEmbedding=_FakeFEOk),
    )

    emb._get_fe_model("sentence-transformers/all-MiniLM-L6-v2")

    assert _FakeFEOk.last_local_files_only is True


def test_offline_mode_cache_miss_has_actionable_error(monkeypatch):
    import campy.brain.hippocampus.graph.embeddings as emb

    _reset_embeddings_module(emb)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "fastembed",
        types.SimpleNamespace(TextEmbedding=_FakeFEMissing),
    )

    with pytest.raises(RuntimeError, match="Embedding model not found in local cache"):
        emb._get_fe_model("sentence-transformers/all-MiniLM-L6-v2")


def test_offline_env_var_overrides_config_when_true(monkeypatch):
    import campy.brain.hippocampus.graph.embeddings as emb

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    emb.configure({"embeddings": {"offline": False}})

    assert emb._offline_mode is True
    assert emb._is_offline_enabled() is True


def test_offline_cache_miss_message_survives_ollama_fallback_failure(monkeypatch):
    """VibeGuide round-3 verification, Finding 3: the actionable offline
    error is real and unit-tested at the direct call
    (test_offline_mode_cache_miss_has_actionable_error above), but through
    the public `_embed_with_fallback` path it used to be swallowed --
    caught, demoted to a warning, and replaced by whatever the Ollama
    fallback's own (unhelpful) connection error was. In the exact scenario
    this feature targets (offline + uncached model + no network at all),
    Ollama is unreachable too, and the pre-bake instruction never reached
    the operator. This proves the aggregate error now contains both
    providers' reasons, so the actionable text survives."""
    import campy.brain.hippocampus.graph.embeddings as emb

    _reset_embeddings_module(emb)
    emb._provider = "sentence-transformers"
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "fastembed",
        types.SimpleNamespace(TextEmbedding=_FakeFEMissing),
    )

    def _fake_ollama_unreachable(text, model_name):
        raise ConnectionError("Connection refused")

    # _EMBED_FN captured a direct reference to _embed_ollama at module-def
    # time, so patching the module attribute alone wouldn't affect the
    # lookup _embed_with_fallback actually uses.
    monkeypatch.setitem(emb._EMBED_FN, "ollama", _fake_ollama_unreachable)

    with pytest.raises(RuntimeError) as exc_info:
        emb._embed_with_fallback("some text", "sentence-transformers/all-MiniLM-L6-v2")

    message = str(exc_info.value)
    assert "Embedding model not found in local cache" in message, (
        "actionable offline-cache-miss message was swallowed by the "
        "fallback chain: %r" % message
    )
    assert "Connection refused" in message
