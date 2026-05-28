"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.brainstem.sweep
"""

from campy.brain.brainstem.sweep import *  # noqa: F401,F403
from campy.brain.brainstem.sweep import (  # noqa: F401
    _decay_and_archive,
    _apply_valence_decay,
    _resurrect_archived,
    _hebbian_promote,
    _recompute_centroids,
    _dream_consolidation,
    _update_procedure_maturity,
    _call_llm,
    _detect_frustration_clusters,
    _synthesize_procedures,
    _audit_consistency,
    _infer_retrospective_plans,
    _detect_knowledge_gaps,
)
