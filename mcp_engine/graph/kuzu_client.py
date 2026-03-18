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

    def create_vector_index(self, table: str, property: str, index_name: str):
        """
        Create an HNSW vector index on a node table property.
        Requires FLOAT[384] fixed-dimension type (not FLOAT[]).
        One index per node table. Called at schema init.
        """
        # Implementation note: Kùzu 0.11.3 vector index syntax
        # Kùzu 0.11.3 argument order: (table, index_name, property)
        self.execute(
            f"CALL CREATE_VECTOR_INDEX('{table}', '{index_name}', '{property}')"
        )

    def vector_search(self, index_name: str, query_embedding: list[float],
                      limit: int) -> list[dict]:
        """
        Query a single HNSW index. Returns list of (node, score) results.
        For multi-table search, call this per table and UNION results in Python.
        """
        # Implementation note (multi-table): caller builds UNION ALL in Python
        # by calling this method per table, merging + sorting by score.
        # Phase 1+ upgrade: EmbeddingNode architectural pattern for single unified index.
        result = self.execute(
            f"CALL QUERY_VECTOR_INDEX('{index_name}', {limit}, $embedding) "
            f"YIELD node, score RETURN node, score",
            {"embedding": query_embedding}
        )
        rows = []
        while result.has_next():
            row = result.get_next()
            rows.append({"node": row[0], "score": row[1]})
        return rows

    def close(self):
        del self.conn
        del self.db
