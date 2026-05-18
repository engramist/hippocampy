"""
mcp_engine/formatters/claude_code.py — Claude Code Formatter

Structured markdown with headers per section type, decisions with confidence,
constraint blocks, and code-relevant context.
"""

from __future__ import annotations

from mcp_engine.bundle_compiler import ContextBundle


class ClaudeCodeFormatter:
    """Format ContextBundle as structured Markdown for Claude Code."""

    @property
    def name(self) -> str:
        return "claude_code"

    def format(self, bundle: ContextBundle) -> str:
        """Convert bundle to structured markdown."""
        lines = []
        
        lines.append(f"# Context: {bundle.query}")
        lines.append("")
        
        for section in bundle.sections:
            lines.extend(self._format_section(section))
            lines.append("")
        
        lines.append("---")
        lines.append(f"_Tokens: {bundle.total_token_estimate}/{bundle.token_budget} "
                    f"{'(truncated)' if bundle.truncated else '(complete)'}_")
        
        return "\n".join(lines)

    def _format_section(self, section) -> list[str]:
        """Format a single section."""
        lines = []
        
        # Section header
        section_names = {
            "exact_fact": "## Exact Facts",
            "semantic": "## Relevant Memory",
            "graph": "## Related Concepts",
            "tabular": "## Data",
            "summary": "## Summary",
        }
        
        header = section_names.get(section.section_type, f"## {section.section_type.title()}")
        lines.append(header)
        lines.append("")
        
        if not section.content:
            lines.append("_No content_")
            return lines
        
        # Format based on section type
        if section.section_type == "exact_fact":
            for item in section.content:
                confidence = item.get("confidence", 0.5)
                lines.append(f"- **{item.get('type', 'Fact')}**: {item.get('text', '')}")
                lines.append(f"  _confidence: {confidence:.0%}_")
        
        elif section.section_type == "semantic":
            for item in section.content:
                strength = item.get("pathway_strength", 0)
                confidence = item.get("confidence", 0)
                lines.append(f"- **{item.get('type', 'Item')}**: {item.get('text', '')}")
                lines.append(f"  _strength: {strength:.0%} | confidence: {confidence:.0%}_")
        
        elif section.section_type == "graph":
            for item in section.content:
                lines.append(f"- {item.get('relationship', 'Related to')} {item.get('target', '')}")
        
        elif section.section_type == "tabular":
            for item in section.content:
                lines.append(f"| {item.get('name', '')} | {item.get('value', '')} |")
        
        else:
            # Default formatting
            for item in section.content:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('text', str(item))}")
                else:
                    lines.append(f"- {item}")
        
        return lines
