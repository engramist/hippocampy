"""
mcp_engine/tool_schemas.py — Compatibility shim.

The canonical module has moved to campy.brain.thalamus.tool_schemas.
This shim re-exports all public names so existing importers continue to work
without modification.
"""

from campy.brain.thalamus.tool_schemas import TOOLS  # noqa: F401

__all__ = ["TOOLS"]
