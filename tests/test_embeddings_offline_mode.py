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
