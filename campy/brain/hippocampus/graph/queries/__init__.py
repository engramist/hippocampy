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
from campy.brain.hippocampus.graph.queries.arc import ARC_QUERIES
from campy.brain.hippocampus.graph.queries.backup import BACKUP_QUERIES
from campy.brain.hippocampus.graph.queries.capability import CAPABILITY_QUERIES
from campy.brain.hippocampus.graph.queries.continuity import CONTINUITY_QUERIES
from campy.brain.hippocampus.graph.queries.lessons import LESSONS_QUERIES
from campy.brain.hippocampus.graph.queries.quests import QUEST_QUERIES
from campy.brain.hippocampus.graph.queries.orchestrator import ORCHESTRATOR_QUERIES
from campy.brain.hippocampus.graph.queries.pathways import PATHWAY_QUERIES
from campy.brain.hippocampus.graph.queries.sweep import SWEEP_QUERIES
from campy.brain.hippocampus.graph.queries.retrieval import RETRIEVAL_QUERIES
from campy.brain.hippocampus.graph.queries.working_memory import WORKING_MEMORY_QUERIES
from campy.brain.hippocampus.graph.queries.capture import CAPTURE_QUERIES
from campy.brain.hippocampus.graph.queries.ingest import INGEST_QUERIES
from campy.brain.hippocampus.graph.queries.task_graph import TASK_GRAPH_QUERIES
from campy.brain.hippocampus.graph.queries.web import WEB_QUERIES
from campy.brain.hippocampus.graph.queries.basal_ganglia import BASAL_GANGLIA_QUERIES
from campy.brain.hippocampus.graph.queries.explore import EXPLORE_QUERIES
from campy.brain.hippocampus.graph.queries.thalamus import THALAMUS_QUERIES
from campy.brain.hippocampus.graph.queries.temporal_lobe import TEMPORAL_LOBE_QUERIES
from campy.brain.hippocampus.graph.queries.provenance import PROVENANCE_QUERIES
from campy.brain.hippocampus.graph.queries.cli import CLI_QUERIES

REGISTRY = QueryRegistry()
REGISTRY.register_all(LESSONS_QUERIES)
REGISTRY.register_all(BACKUP_QUERIES)
REGISTRY.register_all(CAPABILITY_QUERIES)
REGISTRY.register_all(CONTINUITY_QUERIES)
REGISTRY.register_all(ARC_QUERIES)
REGISTRY.register_all(QUEST_QUERIES)
REGISTRY.register_all(SWEEP_QUERIES)
REGISTRY.register_all(PATHWAY_QUERIES)
REGISTRY.register_all(ORCHESTRATOR_QUERIES)
REGISTRY.register_all(RETRIEVAL_QUERIES)
REGISTRY.register_all(WORKING_MEMORY_QUERIES)
REGISTRY.register_all(CAPTURE_QUERIES)
REGISTRY.register_all(INGEST_QUERIES)
REGISTRY.register_all(TASK_GRAPH_QUERIES)
REGISTRY.register_all(WEB_QUERIES)
REGISTRY.register_all(BASAL_GANGLIA_QUERIES)
REGISTRY.register_all(EXPLORE_QUERIES)
REGISTRY.register_all(THALAMUS_QUERIES)
REGISTRY.register_all(TEMPORAL_LOBE_QUERIES)
REGISTRY.register_all(PROVENANCE_QUERIES)
REGISTRY.register_all(CLI_QUERIES)

__all__ = ["REGISTRY"]
