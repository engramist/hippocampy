"""
mcp_engine/bundle_compiler.py — compatibility shim

Canonical location: campy/brain/thalamus/bundle_compiler.py
"""
# ruff: noqa: F401, F403
from campy.brain.thalamus.bundle_compiler import (
    BundleSection,
    ContextBundle,
    BUDGET_TIERS,
    _get_tier,
    compile_bundle,
    _stage_exact_facts,
    _stage_semantic_context,
    _stage_graph_structure,
    _stage_tabular_data,
    _stage_summaries,
)

__all__ = [
    "BundleSection",
    "ContextBundle",
    "BUDGET_TIERS",
    "_get_tier",
    "compile_bundle",
    "_stage_exact_facts",
    "_stage_semantic_context",
    "_stage_graph_structure",
    "_stage_tabular_data",
    "_stage_summaries",
]
