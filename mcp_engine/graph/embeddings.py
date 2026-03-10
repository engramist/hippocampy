"""
mcp_engine/graph/embeddings.py — Sentence-Transformers Wrapper

Model: sentence-transformers/all-MiniLM-L6-v2 (384-dim)
Pre-warmed at daemon startup to avoid cold-start latency on first message.
"""

from sentence_transformers import SentenceTransformer

EMBEDDING_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def get_model(model_name: str = MODEL_NAME) -> SentenceTransformer:
    """Lazy singleton — loads once, reused for all embed calls."""
    global _model
    if _model is None:
        _model = SentenceTransformer(model_name)
    return _model


def prewarm(model_name: str = MODEL_NAME) -> None:
    """Called at daemon startup to load model into memory before first request."""
    get_model(model_name)


def embed(text: str, model_name: str = MODEL_NAME) -> list[float]:
    """Embed a single string. Returns list of 384 floats."""
    return get_model(model_name).encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str], model_name: str = MODEL_NAME) -> list[list[float]]:
    """
    Embed a list of strings efficiently.
    Used for centroid bootstrap at M1 (105 seed examples).
    Returns list of 384-float vectors, one per input text.
    """
    return get_model(model_name).encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    ).tolist()


def mean_pool(embeddings: list[list[float]]) -> list[float]:
    """Compute the mean of a list of embedding vectors. Used for centroid computation."""
    if not embeddings:
        raise ValueError("Cannot mean-pool empty list")
    dim = len(embeddings[0])
    result = [0.0] * dim
    for emb in embeddings:
        for i, v in enumerate(emb):
            result[i] += v
    return [v / len(embeddings) for v in result]
