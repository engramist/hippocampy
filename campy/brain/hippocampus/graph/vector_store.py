"""
campy/brain/hippocampus/graph/vector_store.py — sqlite-vec + FTS5 vector/lexical store

B390: the vector (ANN) and lexical (full-text) planes leave the graph before
the Oxigraph cutover, because neither has a SPARQL equivalent — see
docs/rdf-schema-mapping.md §5. This module is a standalone, embedded SQLite
store proving that component in isolation, against the still-working Kùzu
tree. It replaces Kùzu's `QUERY_VECTOR_INDEX` / `QUERY_FTS_INDEX` call shape
with the same two-stage contract:

    1. ANN / FTS  -> [(uri, score)]   (this module)
    2. graph hydration on those URIs  -> caller's job (NOT this module)

THIS MODULE MUST NOT IMPORT `kuzu`, `pyoxigraph`, OR ANYTHING FROM
`campy/brain/hippocampus/graph/kuzu_client.py`, `gateway.py`, OR
`graph/queries/`. It knows nothing about either graph engine. Wiring this
store into retrieval is B397's job, not this card's.

Row identity: every row is keyed by the full RDF instance URI string (e.g.
``https://campy.dev/id/Concept/c_01H8XK``), minted by ``mint_uri()`` below
per docs/rdf-schema-mapping.md §2 — a pure function of ``(table,
primary_key)``. This is the same key Oxigraph will use, so the two stores
join with no translation table once B397 lands.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

import sqlite_vec

# --- §2 URI minting -------------------------------------------------------

# Per docs/rdf-schema-mapping.md §2:
#   @prefix cid: <https://campy.dev/id/>
#   Instance URIs: cid:{TableName}/{primary_key_value}
CID_BASE = "https://campy.dev/id/"

# RFC 3986 "unreserved" characters are exactly what `urllib.parse.quote`
# leaves untouched when `safe=""` is passed (its own default additionally
# spares "/", which we do NOT want here — a "/" inside a primary key must
# become %2F, or it would silently be read back as a path separator when
# the URI is split into (table, key) again).
_UNRESERVED_SAFE = ""


def mint_uri(table: str, primary_key: object) -> str:
    """Mint the full RDF instance URI string from ``(table, primary_key)``.

    Pure function of its two inputs, per docs/rdf-schema-mapping.md §2 —
    never mint from a mutable property. Both components are percent-encoded
    per RFC 3986 unconditionally (existing keys are ULID/slug-shaped and
    usually need no encoding, but the spec requires the encoder to run
    every time, never conditionally).

    >>> mint_uri("Concept", "c_01H8XK")
    'https://campy.dev/id/Concept/c_01H8XK'
    """
    encoded_table = quote(str(table), safe=_UNRESERVED_SAFE)
    encoded_key = quote(str(primary_key), safe=_UNRESERVED_SAFE)
    return f"{CID_BASE}{encoded_table}/{encoded_key}"


# --- store -----------------------------------------------------------------

#: Embedding width used across the codebase (fastembed all-MiniLM-L6-v2,
#: see B355). Configurable per-instance for testing against smaller fixture
#: vectors (the shared B279 calibration fixture uses FLOAT[4]).
DEFAULT_DIM = 384


def _default_db_path() -> Path:
    """Resolve ``~/.campy/vectors.db`` without importing any graph module.

    Deliberately does not import ``campy.paths`` — this store must not
    acquire a transitive dependency on the rest of the brain package tree
    (or on Kùzu, which several of those modules import). ``~/.campy`` is
    documented in docs/rdf-schema-mapping.md §5 as this store's location;
    this mirrors that path independently and cheaply.
    """
    return Path(os.path.expanduser("~/.campy")) / "vectors.db"


class VectorStore:
    """Embedded SQLite store: sqlite-vec ANN + FTS5 lexical search.

    Contract: vectors and text go in, ``[(uri, score)]`` comes out. This
    class knows nothing about Kùzu, Oxigraph, or any node/edge schema —
    hydrating a returned URI into a graph node is strictly the caller's
    job (see the module docstring).

    Score conventions (both "higher is better", matching each other and
    matching `KuzuClient.vector_search`'s existing convention — B279):

    - Vector search returns true cosine similarity in [-1.0, 1.0]:
      ``score = 1.0 - cosine_distance``. sqlite-vec's ``vec0`` module with
      ``distance_metric=cosine`` yields ``cosine_distance`` directly (no
      inference needed, unlike Kùzu's undocumented default).
    - Lexical search returns ``-bm25(fts)``. SQLite's bm25() is a cost
      (more negative = better match); negating it gives a score that is
      "higher is better" like the vector plane, so callers can treat both
      planes uniformly.
    """

    def __init__(self, db_path: str | Path | None = None, dim: int = DEFAULT_DIM):
        self.dim = dim
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        # sqlite3 connections are not safe to share across threads without
        # this store taking care of serialization itself; this component
        # is not yet wired into any async caller (B397 does that), so a
        # plain lock around every statement is sufficient and cheap.
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vectors USING vec0("
                "uri TEXT PRIMARY KEY, "
                f"embedding FLOAT[{self.dim}] distance_metric=cosine"
                ")"
            )
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5("
                "uri UNINDEXED, text"
                ")"
            )
            self._conn.commit()

    # -- vector plane --------------------------------------------------

    def upsert_vector(self, uri: str, embedding: Sequence[float]) -> None:
        """Insert or replace the embedding for ``uri``.

        ``vec0`` virtual tables reject ``INSERT OR REPLACE`` (confirmed
        empirically — "UNIQUE constraint failed on primary key" even with
        the modifier), so upsert is delete-then-insert inside one
        transaction.
        """
        if len(embedding) != self.dim:
            raise ValueError(
                f"embedding has {len(embedding)} dims, store is configured for {self.dim}"
            )
        vec = sqlite_vec.serialize_float32(list(embedding))
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE uri = ?", (uri,))
            self._conn.execute(
                "INSERT INTO vectors(uri, embedding) VALUES (?, ?)", (uri, vec)
            )
            self._conn.commit()

    def delete_vector(self, uri: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE uri = ?", (uri,))
            self._conn.commit()

    def search_vectors(
        self,
        embedding: Sequence[float],
        k: int,
        min_score: float | None = None,
    ) -> list[tuple[str, float]]:
        """Top-k ANN search. Returns ``[(uri, cosine_similarity)]`` ordered
        best-first.

        ``min_score`` is a cosine-similarity floor (same units B279 pinned
        for Kùzu's `vector_search`): rows scoring below it are dropped.
        Translated to a ``distance <= 1 - min_score`` predicate pushed into
        the same MATCH query (confirmed empirically that sqlite-vec
        accepts an additional ``AND distance <= ?`` clause alongside
        ``embedding MATCH ? AND k = ?`` in one statement).
        """
        if len(embedding) != self.dim:
            raise ValueError(
                f"embedding has {len(embedding)} dims, store is configured for {self.dim}"
            )
        vec = sqlite_vec.serialize_float32(list(embedding))
        sql = (
            "SELECT uri, distance FROM vectors "
            "WHERE embedding MATCH ? AND k = ?"
        )
        params: list = [vec, k]
        if min_score is not None:
            max_distance = 1.0 - min_score
            sql += " AND distance <= ?"
            params.append(max_distance)
        sql += " ORDER BY distance"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        results = []
        for uri, distance in rows:
            score = max(-1.0, min(1.0, 1.0 - float(distance)))
            results.append((uri, score))
        return results

    # -- lexical plane ---------------------------------------------------

    def index_text(self, uri: str, text: str) -> None:
        """Insert or replace the indexed text for ``uri``.

        FTS5's ``uri`` column is declared UNINDEXED (not a key SQLite can
        enforce uniqueness on), so upsert is delete-then-insert, same as
        the vector plane.
        """
        with self._lock:
            self._conn.execute("DELETE FROM lexical WHERE uri = ?", (uri,))
            self._conn.execute(
                "INSERT INTO lexical(uri, text) VALUES (?, ?)", (uri, text)
            )
            self._conn.commit()

    def delete_text(self, uri: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM lexical WHERE uri = ?", (uri,))
            self._conn.commit()

    def search_text(self, query: str, k: int) -> list[tuple[str, float]]:
        """FTS5 full-text search. Returns ``[(uri, score)]`` ordered
        best-first, where ``score = -bm25(lexical)`` (higher is better,
        same convention as `search_vectors`).
        """
        sql = (
            "SELECT uri, bm25(lexical) FROM lexical "
            "WHERE lexical MATCH ? ORDER BY bm25(lexical) LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, (query, k)).fetchall()
        return [(uri, -float(bm25)) for uri, bm25 in rows]

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["VectorStore", "mint_uri", "CID_BASE", "DEFAULT_DIM"]
