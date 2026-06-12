"""
mcp_engine/graph/kuzu_client.py — Kùzu Abstraction Layer

THIS IS THE ONLY FILE THAT IMPORTS KUZU.
Migration to Neo4j or another provider = rewrite this file only.
All other modules call methods here — never import kuzu directly.

Kùzu version: kuzu==0.11.3 (archived Oct 2025, pinned)
"""

from __future__ import annotations
import asyncio
import kuzu

_INDEX_METRIC = "cosine"

# S4 fix: Lock lazy-initialized to avoid creation before an event loop exists.
_write_lock: asyncio.Lock | None = None


def _get_write_lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


class KuzuClient:
    """Sole interface to the Kùzu database."""

    def __init__(self, db_path: str, read_only: bool = False):
        self.db = kuzu.Database(db_path, read_only=read_only)
        self.conn = kuzu.Connection(self.db)
        self.read_only = read_only
        self._fts_checked: bool | None = None

    def execute(self, query: str, params: dict = None):
        """
        Execute a Cypher query synchronously.
        For write operations, caller must hold _write_lock.
        Returns the Kùzu QueryResult object.
        """
        if params:
            return self.conn.execute(query, params)
        return self.conn.execute(query)

    async def execute_write(self, query: str, params: dict = None):
        """
        Execute a write query with the asyncio write lock held.
        Use this for all INSERT / MERGE / SET / DELETE operations.
        S3 fix: Kùzu I/O runs in a thread so it doesn't block the event loop
        while the lock is held.
        """
        async with _get_write_lock():
            return await asyncio.to_thread(self.execute, query, params)

    async def execute_read(self, query: str, params: dict = None):
        """
        Execute a read query asynchronously and return materialized rows.

        Kùzu's `get_next()` returns positional lists. Most call sites in this
        repo expect rows addressable by their projected column names, so we
        normalize each row into a dict when column metadata is available.
        """
        result = await asyncio.to_thread(self.execute, query, params)
        rows = []
        column_names = result.get_column_names() if hasattr(result, "get_column_names") else None
        while result.has_next():
            row = result.get_next()
            if isinstance(row, dict):
                rows.append(row)
            elif column_names and isinstance(row, (list, tuple)) and len(column_names) == len(row):
                rows.append({name: value for name, value in zip(column_names, row)})
            else:
                rows.append(row)
        return rows

    def create_vector_index(self, table: str, property: str, index_name: str):
        """
        Create an HNSW vector index on a node table property.
        Requires FLOAT[384] fixed-dimension type (not FLOAT[]).
        One index per node table. Called at schema init.
        """
        # Implementation note: Kùzu 0.11.3 vector index syntax
        # Kùzu 0.11.3 argument order: (table, index_name, property)
        self.execute(
            f"CALL CREATE_VECTOR_INDEX('{table}', '{index_name}', '{property}', metric := '{_INDEX_METRIC}')"
        )

    def has_fts(self) -> bool:
        """Return True when the loaded Kuzu build can execute FTS queries."""
        if self._fts_checked is not None:
            return self._fts_checked

        try:
            result = self.execute("CALL SHOW_LOADED_EXTENSIONS() RETURN *;")
            while result.has_next():
                row = result.get_next()
                if any(str(cell).lower() == "fts" for cell in row if cell is not None):
                    self._fts_checked = True
                    return True
            try:
                self.execute("LOAD fts;")
                self._fts_checked = True
            except Exception:
                self._fts_checked = False
        except Exception:
            self._fts_checked = False
        return self._fts_checked

    def create_fts_index(self, table: str, index_name: str, properties: list[str]):
        """Create a full-text index on a node table property set."""
        prop_list = ", ".join(f"'{prop}'" for prop in properties)
        self.execute(f"CALL CREATE_FTS_INDEX('{table}', '{index_name}', [{prop_list}])")

    def fts_search(self, table: str, index_name: str, query: str, limit: int) -> list[dict]:
        """Run a bounded full-text search against a prebuilt FTS index."""
        result = self.execute(
            f"CALL QUERY_FTS_INDEX('{table}', '{index_name}', $query) "
            f"YIELD node, score RETURN node, score LIMIT {limit}",
            {"query": query},
        )
        rows = []
        while result.has_next():
            row = result.get_next()
            rows.append({"node": row[0], "score": float(row[1]) if row[1] is not None else 0.0})
        return rows

    def vector_search(self, table_name: str, index_name: str,
                      query_embedding: list[float], limit: int) -> list[dict]:
        """
        Query a single HNSW index and return true cosine similarity scores.
        For multi-table search, call this per table and UNION results in Python.
        """
        # Kùzu 0.11.3 QUERY_VECTOR_INDEX signature:
        #   (table_name, index_name, query_vector, k)
        # Kùzu 0.11.3 yields (node, distance). B279 pins metric=cosine at
        # index creation, so distance = 1 - cosine_similarity.
        result = self.execute(
            f"CALL QUERY_VECTOR_INDEX('{table_name}', '{index_name}', $embedding, {limit}) "
            f"YIELD node, distance RETURN node, distance",
            {"embedding": query_embedding}
        )
        rows = []
        while result.has_next():
            row = result.get_next()
            distance = row[1]
            score = max(-1.0, min(1.0, 1.0 - float(distance)))
            rows.append({"node": row[0], "score": score})
        return rows

    def close(self):
        del self.conn
        del self.db
