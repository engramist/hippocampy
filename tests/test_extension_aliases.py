"""
tests/test_extension_aliases.py — Audit OpenClaw tool aliases.
"""

import re
from pathlib import Path
from mcp_engine.tools import TOOL_HANDLERS

def test_openclaw_aliases_resolve_to_handlers():
    """Verify all tools registered in OpenClaw index.ts map to valid TOOL_HANDLERS."""
    index_path = Path("extensions/hippocampy/src/index.ts")
    if not index_path.exists():
        return # Skip if extension not present in this env

    content = index_path.read_text()
    
    # Extract toolDefinitions block
    match = re.search(r"const toolDefinitions: BrainToolDefinition\[\] = \[(.*?)\];", content, re.DOTALL)
    assert match, "Could not find toolDefinitions in index.ts"
    
    defs_text = match.group(1)
    
    # Extract each tool definition block by splitting on '},\n      {' or similar
    # A more robust way: find all tool name entries and the text until the next one
    # OR just find all callName occurrences and their preceding names.
    
    # Let's try splitting by the comma after the closing brace of each tool object
    # assuming they are followed by a newline and some spaces and then a {
    tool_blocks = re.split(r"},\s*\n\s*{", defs_text)
    
    for block in tool_blocks:
        # Ensure block has braces if it's the first or last one
        if not block.strip().startswith("{"):
            block = "{" + block
        if not block.strip().endswith("}"):
            block = block + "}"
            
        name_match = re.search(r'name: "(.*?)"', block)
        if not name_match:
            continue
        tool_name = name_match.group(1)
        
        call_name_match = re.search(r'callName: "(.*?)"', block)
        if call_name_match:
            handler_name = call_name_match.group(1)
        else:
            handler_name = tool_name
            
        assert handler_name in TOOL_HANDLERS, f"Tool '{tool_name}' maps to missing handler '{handler_name}'"

if __name__ == "__main__":
    test_openclaw_aliases_resolve_to_handlers()
