"""
campy/brain/thalamus/formatters/base.py — BundleFormatter Protocol

Defines the interface for formatting ContextBundles for specific agent types.
"""

from __future__ import annotations

from typing import Protocol

from campy.brain.thalamus.bundle_compiler import ContextBundle


class BundleFormatter(Protocol):
    """Protocol for formatting ContextBundles for specific agent types."""

    def format(self, bundle: ContextBundle) -> str:
        """Convert a ContextBundle into agent-specific text."""
        ...

    @property
    def name(self) -> str:
        """Formatter identifier (matches agent_type parameter)."""
        ...
