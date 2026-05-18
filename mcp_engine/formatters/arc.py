"""
mcp_engine/formatters/arc.py — ARC Formatter

Structured JSON matching ARC agent expectations.
"""

from __future__ import annotations

import json

from mcp_engine.bundle_compiler import ContextBundle


class ArcFormatter:
    """Format ContextBundle as structured JSON for ARC agent."""

    @property
    def name(self) -> str:
        return "arc"

    def format(self, bundle: ContextBundle) -> str:
        """Convert bundle to ARC-specific JSON structure."""
        arc_context = {
            "query": bundle.query,
            "memory_state": {
                "exact_facts": [],
                "hypotheses": [],
                "world_model_items": [],
                "tabular_context": [],
            },
            "token_budget": {
                "allocated": bundle.token_budget,
                "used": bundle.total_token_estimate,
                "remaining": bundle.token_budget - bundle.total_token_estimate,
            },
            "confidence_summary": {},
        }
        
        # Map sections to ARC categories
        for section in bundle.sections:
            if section.section_type == "exact_fact":
                arc_context["memory_state"]["exact_facts"] = section.content
            elif section.section_type == "semantic":
                arc_context["memory_state"]["hypotheses"] = section.content
            elif section.section_type == "graph":
                arc_context["memory_state"]["world_model_items"] = section.content
            elif section.section_type == "tabular":
                arc_context["memory_state"]["tabular_context"] = section.content
        
        return json.dumps(arc_context, indent=2, default=str)
