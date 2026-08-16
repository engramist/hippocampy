"""
campy/brain/hippocampus/graph/queries/ — the B314 named-query registry.

One module per domain (`lessons.py`, and more as follow-up cards migrate
other files — `quests.py`, `retrieval.py`, ...), each exporting a tuple of
`NamedQuery` objects. This module assembles all of them into a single
`QueryRegistry`, `REGISTRY`, imported by `GraphGateway` call sites.

Registering a bad query (duplicate name, non-static Cypher, ...) raises
here, at import time — see `gateway.NamedQuery.__post_init__` /
`QueryRegistry.register`.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import QueryRegistry
from campy.brain.hippocampus.graph.queries.backup import BACKUP_QUERIES
from campy.brain.hippocampus.graph.queries.lessons import LESSONS_QUERIES

REGISTRY = QueryRegistry()
REGISTRY.register_all(LESSONS_QUERIES)
REGISTRY.register_all(BACKUP_QUERIES)

__all__ = ["REGISTRY"]
