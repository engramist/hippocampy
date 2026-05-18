"""
mcp_engine/formatters/generic.py — Generic JSON Formatter

Default formatter that returns bundle as JSON (backwards compatible).
"""

from __future__ import annotations

import json

from mcp_engine.bundle_compiler import ContextBundle


class GenericFormatter:
    """Generic JSON formatter - returns bundle.to_dict()."""

    @property
    def name(self) -> str:
        return "generic"

    def format(self, bundle: ContextBundle) -> str:
        """Return bundle as formatted JSON."""
        return json.dumps(bundle.to_dict(), indent=2, default=str)
