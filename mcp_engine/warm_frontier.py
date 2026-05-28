"""
mcp_engine/warm_frontier.py — compatibility shim (TEMPORAL-4)

Canonical module has moved to campy.brain.temporal_lobe.warm_frontier.
This shim re-exports all public names for backward compatibility.
"""

from campy.brain.temporal_lobe.warm_frontier import (  # noqa: F401
    compute_warm_frontier,
    get_warm_nodes,
    _get_artifact_neighbors,
    MAX_WARM_NODES,
    SIMILARITY_WEIGHT,
    HOPS_DECAY,
    MIN_ACTIVATION,
    NODE_PK_MAP,
)

__all__ = [
    "compute_warm_frontier",
    "get_warm_nodes",
    "_get_artifact_neighbors",
    "MAX_WARM_NODES",
    "SIMILARITY_WEIGHT",
    "HOPS_DECAY",
    "MIN_ACTIVATION",
    "NODE_PK_MAP",
]
