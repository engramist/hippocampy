"""
campy/brain/thalamus/formatters/claude_desktop.py — Claude Desktop Formatter

Conversational prose with inline citations.
"""

from __future__ import annotations

from campy.brain.thalamus.bundle_compiler import ContextBundle


class ClaudeDesktopFormatter:
    """Format ContextBundle as conversational prose for Claude Desktop."""

    @property
    def name(self) -> str:
        return "claude_desktop"

    def format(self, bundle: ContextBundle) -> str:
        """Convert bundle to conversational prose."""
        lines = []

        # Conversational intro
        lines.append(f"Based on your query about '{bundle.query}', here's what I found in memory:\n")

        # Flatten sections into prose
        for section in bundle.sections:
            if not section.content:
                continue

            section_intro = {
                "exact_fact": "Some key constraints and preferences:",
                "semantic": "Relevant past decisions and context:",
                "graph": "Related concepts and their relationships:",
                "tabular": "Related data:",
                "summary": "Summary of the situation:",
            }

            intro = section_intro.get(section.section_type, "Additional context:")
            lines.append(f"{intro}")

            for item in section.content:
                text = item.get("text", str(item)) if isinstance(item, dict) else item
                lines.append(f"- {text}")

            lines.append("")

        return "\n".join(lines)
