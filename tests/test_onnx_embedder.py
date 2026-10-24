"""B512: direct ONNX Runtime embedder (replaces fastembed).

Tests that need the model skip when it is not in the local cache -- they never
touch the network. The golden vectors in tests/fixtures/onnx_embedder_golden.json
were produced by fastembed 0.8.0 (the backend this replaced); matching them is
the standing proof that the swap did not change a single stored-vector value.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from campy.brain.hippocampus.graph import onnx_embedder as oe

GOLDEN = Path(__file__).parent / "fixtures" / "onnx_embedder_golden.json"


# --- pure unit tests (no model) ---------------------------------------------

def test_unsupported_model_name_is_rejected():
    with pytest.raises(ValueError, match="Unsupported local embedding model"):
        oe.resolve_model_dir("BAAI/bge-small-en-v1.5")


def test_offline_with_empty_cache_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(FileNotFoundError, match="offline"):
        oe.resolve_model_dir(cache_dir=str(tmp_path))


def test_local_files_only_with_empty_cache_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        oe.resolve_model_dir(local_files_only=True, cache_dir=str(tmp_path))


def test_normalize_unit_length_and_zero_vector_is_finite():
    x = np.array([[3.0, 4.0], [0.0, 0.0]])
    out = oe._normalize(x)
    assert np.allclose(np.linalg.norm(out[0]), 1.0)
    assert np.isfinite(out).all()


def test_mean_pool_ignores_masked_positions():
    hidden = np.array([[[1.0, 1.0], [3.0, 5.0], [99.0, 99.0]]], dtype=np.float32)
    mask = np.array([[1, 1, 0]], dtype=np.int64)
    assert np.allclose(oe._mean_pool(hidden, mask), [[2.0, 3.0]])
    assert oe._mean_pool(hidden, mask).dtype == np.float64


# --- model-backed tests -------------------------------------------------------

@pytest.fixture(scope="module")
def embedder():
    try:
        return oe.OnnxTextEmbedder(local_files_only=True)
    except Exception as e:  # model not cached on this machine / CI
        pytest.skip(f"embedding model not in local cache: {e}")


def test_shape_dtype_and_unit_norm(embedder):
    vecs = list(embedder.embed(["hello world", "another sentence entirely"]))
    assert len(vecs) == 2
    for v in vecs:
        assert v.shape == (oe.EMBEDDING_DIM,)
        assert v.dtype == np.float64
        assert abs(np.linalg.norm(v) - 1.0) < 1e-9
        assert all(isinstance(f, float) for f in v.tolist())


def test_empty_and_whitespace_strings_embed(embedder):
    for text in ("", " ", "\n\t"):
        (v,) = embedder.embed([text])
        assert v.shape == (oe.EMBEDDING_DIM,)
        assert np.isfinite(v).all()
        assert abs(np.linalg.norm(v) - 1.0) < 1e-9


def test_str_input_is_one_document(embedder):
    assert len(list(embedder.embed("just one"))) == 1


def test_empty_list_yields_nothing(embedder):
    assert list(embedder.embed([])) == []


def test_batching_preserves_order_and_values(embedder):
    texts = [f"sentence number {i} " + "word " * (i % 7) for i in range(40)]
    whole = np.array(list(embedder.embed(texts)))
    small = np.array(list(embedder.embed(texts, batch_size=7)))
    singles = np.array([next(iter(embedder.embed([t]))) for t in texts])
    assert whole.shape == (40, oe.EMBEDDING_DIM)
    assert np.allclose(whole, small, atol=1e-6)
    assert np.allclose(whole, singles, atol=1e-6)


def test_truncation_at_256_tokens(embedder):
    base = ["token"] * 256
    a = next(iter(embedder.embed([" ".join(base)])))
    b = next(iter(embedder.embed([" ".join(base + ["extra"] * 50)])))
    # [CLS] + 254 words + [SEP] fit; anything past the limit is cut identically.
    c = next(iter(embedder.embed([" ".join(base[:254])])))
    assert np.allclose(a, b, atol=1e-6)
    assert np.allclose(a, c, atol=1e-6)


def test_matches_fastembed_golden_vectors(embedder):
    golden = json.loads(GOLDEN.read_text())
    got = [next(iter(embedder.embed([t]))) for t in golden["texts"]]
    for text, g, want in zip(golden["texts"], got, golden["vectors"]):
        assert np.allclose(g, np.array(want), atol=1e-6), repr(text[:40])


def test_offline_cache_is_used_without_network(embedder, tmp_path, monkeypatch):
    """Copy the cached snapshot elsewhere, point at it, forbid the network."""
    snapshot = embedder.model_dir
    repo_root = snapshot.parent.parent  # models--qdrant--...
    cache = tmp_path / "cache"
    shutil.copytree(repo_root, cache / repo_root.name, symlinks=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(cache))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # unreachable
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    other = oe.OnnxTextEmbedder()
    assert str(other.model_dir).startswith(str(cache))
    (v,) = other.embed(["offline works"])
    (w,) = embedder.embed(["offline works"])
    assert np.array_equal(v, w)


def test_matches_live_fastembed_when_installed(embedder):
    """Bit-for-bit against the old backend, wherever it is still installed."""
    fastembed = pytest.importorskip("fastembed")
    try:
        old = fastembed.TextEmbedding(
            model_name=oe.MODEL_NAME, local_files_only=True
        )
    except Exception as e:
        pytest.skip(f"fastembed model not cached: {e}")
    texts = ["Alice moved to Berlin in 2021.", "", "x" * 3000, "café 日本語"]
    a = np.array(list(old.embed(texts)))
    b = np.array(list(embedder.embed(texts)))
    assert float(np.abs(a - b).max()) < 1e-9
