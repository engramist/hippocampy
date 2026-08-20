"""
mcp_engine/graph/kuzu_client.py — Kùzu Abstraction Layer

THIS IS THE ONLY FILE THAT IMPORTS KUZU.
Migration to Neo4j or another provider = rewrite this file only.
All other modules call methods here — never import kuzu directly.

Kùzu version: kuzu==0.11.3 (archived Oct 2025, pinned)
"""

from __future__ import annotations
import asyncio
import weakref
import kuzu

_INDEX_METRIC = "cosine"

# S4 fix: Lock lazy-initialized to avoid creation before an event loop exists.
#
# Keyed per-running-loop (not a single bare lock) because asyncio.Lock binds
# to whichever event loop is running on first use. A process that runs more
# than one event loop over its lifetime (e.g. pytest-asyncio's function-scoped
# loops, or any daemon restart-without-process-restart) would otherwise reuse
# a lock still attached to a closed loop from an earlier run, silently
# breaking write serialization instead of raising. Within any single loop's
# lifetime this still behaves as one shared lock across all KuzuClient
# instances, preserving the original serialization guarantee.
#
# Entries carry a weakref to their loop rather than trusting id() alone:
# CPython reuses addresses, so after a loop is garbage-collected a new loop
# can be allocated at the same id and would otherwise inherit the dead
# loop's lock — the exact stale-binding failure this table exists to
# prevent. A dead or mismatched weakref means the entry is stale and gets
# replaced.
#
# B316: keyed on (id(loop), db_path) rather than id(loop) alone. With one
# database the lock was correctly global — every write anywhere serialized
# against every other write. With N per-workspace databases (WorkspaceRouter,
# campy/brain/hippocampus/graph/router.py), a lock shared across all of them
# would serialize every write across every tenant, destroying the entire
# benefit of sharding. The db_path component of the key is the only change:
# the weakref-to-loop staleness check above is preserved exactly, per
# workspace, so a stale entry for one workspace's db_path is detected and
# replaced the same way a stale entry ever was — just scoped to that
# workspace's own lock instead of the one shared lock.
_write_locks: dict[tuple[int, str], tuple[weakref.ref, asyncio.Lock]] = {}


def _get_write_lock(db_path: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), db_path)
    entry = _write_locks.get(key)
    if entry is not None:
        loop_ref, lock = entry
        if loop_ref() is loop:
            return lock
    lock = asyncio.Lock()
    _write_locks[key] = (weakref.ref(loop), lock)
    return lock


class KuzuClient:
    """Sole interface to the Kùzu database."""

    def __init__(self, db_path: str, read_only: bool = False,
                 auto_checkpoint: bool = True, checkpoint_threshold: int = -1):
        # B337: Support manual checkpoint control and WAL threshold tuning.
        # checkpoint_threshold in bytes (-1 = Kuzu default ~262MB).
        # Common tuning values from investigation: 256KB, 1MB, 4MB, 32-64MB.
        self.db = kuzu.Database(
            db_path, read_only=read_only,
            auto_checkpoint=auto_checkpoint,
            checkpoint_threshold=checkpoint_threshold if checkpoint_threshold > 0 else -1
        )
        self.conn = kuzu.Connection(self.db)
        self.read_only = read_only
        self._fts_checked: bool | None = None
        # B316: retained so _get_write_lock() can key the write lock per
        # database, not just per event loop. See the comment above
        # _write_locks for why a single shared lock stops being correct
        # once more than one workspace database exists.
        self.db_path = db_path

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
        async with _get_write_lock(self.db_path):
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

    def drop_vector_index(self, table: str, index_name: str) -> None:
        """Drop a vector index by table and index name.

        B285 Step 0 probe (kuzu==0.11.3) confirmed this signature:
        CALL DROP_VECTOR_INDEX('<table>', '<index_name>')
        """
        self.execute(f"CALL DROP_VECTOR_INDEX('{table}', '{index_name}')")

    async def rebuild_vector_index(self, table: str, property: str, index_name: str) -> None:
        """Drop and recreate a vector index under the global write lock.

        B285 Step 0 probe findings that shape the hygiene design:
        - Rows inserted after index creation are immediately queryable.
        - Deleting a row removes it from index query results.
        - Updating an indexed embedding property is not supported by Kuzu 0.11.3.

        Crash-safety: if recreate fails after drop, schema init recreates missing
        indexes on next daemon startup via the `embedding_tables` loop in
        `campy/brain/hippocampus/schema.py`.
        """
        async with _get_write_lock(self.db_path):
            await asyncio.to_thread(self.drop_vector_index, table, index_name)
            await asyncio.to_thread(self.create_vector_index, table, property, index_name)

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

    def fts_search(self, table: str, index_name: str, query: str, limit: int,
                   cutoff: str | None = None) -> list[dict]:
        """Run a bounded full-text search against a prebuilt FTS index.

        B284: optionally bounded to node.created_at > cutoff (ISO8601
        string) and node.archived = false, applied via a WITH...WHERE
        continuation before the final LIMIT. Kuzu 0.11.3's parser rejects
        a WHERE directly after YIELD ("expected rule oC_SingleQuery") -
        confirmed empirically - so the filter goes in a WITH clause
        instead. Filtering before LIMIT (rather than fetching top-scored
        rows and filtering after) matters: with post-filtering, a `limit`
        of old-but-high-scoring rows could silently crowd out a matching
        recent row instead of surfacing it.
        """
        if cutoff is not None:
            query_text = (
                f"CALL QUERY_FTS_INDEX('{table}', '{index_name}', $query) "
                f"YIELD node, score "
                f"WITH node, score WHERE node.created_at > timestamp($cutoff) "
                f"  AND node.archived = false "
                f"RETURN node, score ORDER BY score DESC LIMIT {limit}"
            )
            params = {"query": query, "cutoff": cutoff}
        else:
            query_text = (
                f"CALL QUERY_FTS_INDEX('{table}', '{index_name}', $query) "
                f"YIELD node, score RETURN node, score LIMIT {limit}"
            )
            params = {"query": query}

        result = self.execute(query_text, params)
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

    async def checkpoint(self) -> bool:
        """Force a manual checkpoint under the write lock.
        
        B337: Decouples checkpoint cadence from transaction boundaries,
        mitigating memory spikes during write-heavy phases. Routes through
        the same per-db write lock as execute_write() to prevent races with
        in-flight writes.
        
        Returns True on success, False on error.
        """
        try:
            async with _get_write_lock(self.db_path):
                await asyncio.to_thread(self.execute, "CHECKPOINT")
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Manual checkpoint failed: %s", e)
            return False
