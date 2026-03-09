"""
mcp_engine/graph/embeddings.py — Sentence-Transformers Wrapper

Model: sentence-transformers/all-MiniLM-L6-v2
Output: FLOAT[384] vectors — matches Kùzu FLOAT[384] schema declaration.

WARNING: Changing the model requires full re-embedding of all nodes in the graph.
Run: sidequests reembed --confirm

Pre-warming: model is loaded at daemon startup to avoid cold-start latency
on first ingestion call (~90MB load into memory).

M1 scope: implement embed() + embed_batch() + pre-warm at startup.
"""

# from sentence_transformers import SentenceTransformer  # uncomment when implementing

EMBEDDING_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingClient:

    def __init__(self, model_name: str = MODEL_NAME):
        # TODO M1: load SentenceTransformer(model_name)
        # Called at daemon startup to pre-warm (avoids cold-start on first message)
        self.model_name = model_name
        self.dim = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns list of 384 floats."""
        # TODO M1: return model.encode(text).tolist()
        pass

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings. Used for centroid bootstrap at M1."""
        # TODO M1: return model.encode(texts).tolist()
        pass
