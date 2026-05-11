"""Focused checks for MCP tool schema consistency."""

from mcp_engine.tool_schemas import TOOLS
from mcp_engine.tools import TOOL_HANDLERS


def test_tool_schema_names_match_registered_handlers():
    schema_names = {tool["name"] for tool in TOOLS}

    assert schema_names == set(TOOL_HANDLERS)


def test_memory_decision_schema_contract():
    tool = next(tool for tool in TOOLS if tool["name"] == "memory_decision")
    schema = tool["inputSchema"]

    assert schema["required"] == ["user_prompt"]
    assert "user_prompt" in schema["properties"]
    assert "session_id" in schema["properties"]
    assert "Does not retrieve memory" in tool["description"]
