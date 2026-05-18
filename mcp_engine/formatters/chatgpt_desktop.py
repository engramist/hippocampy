"""
mcp_engine/formatters/chatgpt_desktop.py — ChatGPT Desktop Formatter

Natural language summary with bullet points, friendly tone.
"""

from __future__ import annotations

from mcp_engine.bundle_compiler import ContextBundle


class ChatGPTDesktopFormatter:
    """Format ContextBundle with friendly, conversational tone for ChatGPT Desktop."""

    @property
    def name(self) -> str:
        return "chatgpt_desktop"

    def format(self, bundle: ContextBundle) -> str:
        """Convert bundle to friendly conversational format."""
        lines = []
        
        lines.append(f"Here's what I found about {bundle.query}:\n")
        
        for section in bundle.sections:
            if not section.content:
                continue
            
            # Friendly section headers
            headers = {
                "exact_fact": "🎯 Key Facts:",
                "semantic": "💭 Similar Situations:",
                "graph": "🔗 Related Items:",
                "tabular": "📊 Data Summary:",
                "summary": "📝 Summary:",
            }
            
            header = headers.get(section.section_type, "📌 Other Info:")
            lines.append(header)
            
            for item in section.content:
                text = item.get("text", str(item)) if isinstance(item, dict) else item
                lines.append(f"• {text}")
            
            lines.append("")
        
        return "\n".join(lines)
