"""
mcp_engine/formatters/__init__.py — compatibility shim

Canonical location: campy/brain/thalamus/formatters/__init__.py
"""
# ruff: noqa: F401, F403
from campy.brain.thalamus.formatters import (
    register,
    get_formatter,
    format_bundle,
    GenericFormatter,
    ClaudeCodeFormatter,
    ClaudeDesktopFormatter,
    CodexFormatter,
    ChatGPTDesktopFormatter,
    ArcFormatter,
)

__all__ = [
    "register",
    "get_formatter",
    "format_bundle",
    "GenericFormatter",
    "ClaudeCodeFormatter",
    "ClaudeDesktopFormatter",
    "CodexFormatter",
    "ChatGPTDesktopFormatter",
    "ArcFormatter",
]
