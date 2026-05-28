"""
campy/brain/thalamus/formatters/codex.py — Codex Formatter

Ultra-compact, code-focused formatter.
"""

from __future__ import annotations

from campy.brain.thalamus.bundle_compiler import ContextBundle


class CodexFormatter:
    """Format ContextBundle as compact code-focused output for Codex."""

    @property
    def name(self) -> str:
        return "codex"

    def format(self, bundle: ContextBundle) -> str:
        """Convert bundle to compact format."""
        lines = []
        lines.append(f"// CONTEXT: {bundle.query}")
        lines.append("")

        for section in bundle.sections:
            if not section.content:
                continue

            section_name = section.section_type.upper()
            lines.append(f"// {section_name}")

            for item in section.content:
                text = item.get("text", str(item)) if isinstance(item, dict) else item
                # Truncate long lines
                if len(text) > 60:
                    text = text[:57] + "..."
                lines.append(f"// {text}")

            lines.append("")

        return "\n".join(lines)
