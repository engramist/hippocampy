"""
tests/test_extension_aliases.py — Audit OpenClaw tool aliases.
"""

import re
from pathlib import Path
from mcp_engine.tools import TOOL_HANDLERS

def test_openclaw_aliases_resolve_to_handlers():
    """Verify all tools registered in OpenClaw index.ts map to valid TOOL_HANDLERS."""
    index_path = Path("extensions/sidequests-brain/src/index.ts")
    if not index_path.exists():
        return # Skip if extension not present in this env

    content = index_path.read_text()
    
    # Extract toolDefinitions block
    match = re.search(r"const toolDefinitions: BrainToolDefinition\[\] = \[(.*?)\];", content, re.DOTALL)
    assert match, "Could not find toolDefinitions in index.ts"
    
    defs_text = match.group(1)
    
    # Extract each tool definition object
    tool_blocks = re.findall(r"\{.*?\}", defs_text, re.DOTALL)
    
    for block in tool_blocks:
        name_match = re.search(r'name: "(.*?)"', block)
        assert name_match, f"Could not find name in block: {block}"
        tool_name = name_match.group(1)
        
        call_name_match = re.search(r'callName: "(.*?)"', block)
        if call_name_match:
            handler_name = call_name_match.group(1)
        else:
            handler_name = tool_name
            
        assert handler_name in TOOL_HANDLERS, f"Tool '{tool_name}' maps to missing handler '{handler_name}'"

if __name__ == "__main__":
    test_openclaw_aliases_resolve_to_handlers()
