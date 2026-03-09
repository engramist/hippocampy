"""
mcp_engine/graph/kuzu_client.py — Kùzu Abstraction Layer

THIS IS THE ONLY FILE THAT IMPORTS KUZU.
All loop steps, tools, and the daemon call methods here — never import kuzu directly.
Migration to Neo4j or another provider = rewrite this file only.

Responsibilities:
  - Own the READ_WRITE kuzu.Database connection (Brain Daemon only)
  - Provide execute() with asyncio.Lock wrapping all writes
  - Provide read-only connection factory for adapters
  - Wrap all Kùzu-specific syntax:
      - DDL: CREATE NODE TABLE, CREATE REL TABLE
      - HNSW: CREATE VECTOR INDEX, CALL QUERY_VECTOR_INDEX(...)
      - Filtered search: CALL project_graph(...)
      - MERGE with ON CREATE / ON MATCH SET
  - Multi-table vector search: UNION ALL across per-table indexes

Concurrency rules:
  - Brain Daemon: single READ_WRITE connection + asyncio.Lock on all writes
  - MCP adapters: kuzu.Database(path, read_only=True) — no write access possible
  - Background sweep: acquires write lock per table (not one giant transaction)
    to keep write-lock windows short

Kùzu version: pinned to kuzu==0.11.3 (archived Oct 2025)
Watch RyuGraph fork for migration path.

M1 scope: implement connection management + execute() + DDL helpers.
M2 scope: add vector search methods.
"""

import asyncio
# import kuzu  # uncomment when implementing

_write_lock = asyncio.Lock()


class KuzuClient:
    """Sole interface to the Kùzu database."""

    def __init__(self, db_path: str, read_only: bool = False):
        # TODO M1: open kuzu.Database(db_path, read_only=read_only)
        # TODO M1: open kuzu.Connection(db)
        self.db_path = db_path
        self.read_only = read_only

    async def execute(self, query: str, params: dict = None):
        """Execute a Cypher query. Acquires write lock for non-read-only connections."""
        # TODO M1: implement with asyncio.Lock for writes
        pass

    async def vector_search(self, query_embedding: list, limit: int = 10,
                            active_only: bool = True) -> list:
        """
        Search across all artifact node tables using UNION ALL on per-table HNSW indexes.
        Uses projected graphs to prefilter archived/confidence_low nodes when active_only=True.

        Returns list of {node_id, node_type, text_raw, pathway_strength, score} dicts.
        """
        # TODO M2: implement UNION ALL across Decision, Constraint, Requirement,
        #          ActionItem, GlobalConstraint, GlobalPreference, Message, DocumentExtract
        pass

    async def close(self):
        # TODO M1: close connection + database
        pass
