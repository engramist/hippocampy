"""
campy/brain/thalamus/formatters/__init__.py — Formatter Registry

Central registry for all ContextBundle formatters.
"""

from __future__ import annotations

from campy.brain.thalamus.bundle_compiler import ContextBundle
from campy.brain.thalamus.formatters.arc import ArcFormatter
from campy.brain.thalamus.formatters.chatgpt_desktop import ChatGPTDesktopFormatter
from campy.brain.thalamus.formatters.claude_code import ClaudeCodeFormatter
from campy.brain.thalamus.formatters.claude_desktop import ClaudeDesktopFormatter
from campy.brain.thalamus.formatters.codex import CodexFormatter
from campy.brain.thalamus.formatters.generic import GenericFormatter


_FORMATTERS: dict[str, object] = {}


def register(formatter: object):
    """Register a formatter."""
    if hasattr(formatter, "name"):
        _FORMATTERS[formatter.name] = formatter


def get_formatter(agent_type: str):
    """Get formatter for agent type, defaulting to generic."""
    if agent_type not in _FORMATTERS:
        return _FORMATTERS.get("generic", GenericFormatter())
    return _FORMATTERS[agent_type]


def format_bundle(bundle: ContextBundle, agent_type: str = "generic") -> str:
    """Format a bundle for the given agent type."""
    formatter = get_formatter(agent_type)
    if hasattr(formatter, "format"):
        return formatter.format(bundle)
    # Fallback to JSON
    return GenericFormatter().format(bundle)


# Register all formatters
register(GenericFormatter())
register(ClaudeCodeFormatter())
register(ClaudeDesktopFormatter())
register(CodexFormatter())
register(ChatGPTDesktopFormatter())
register(ArcFormatter())

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
