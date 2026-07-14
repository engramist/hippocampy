"""Focused checks for MCP tool schema consistency."""

from campy.brain.thalamus.tool_schemas import TOOLS
from campy.brain.thalamus.tools import TOOL_HANDLERS


def test_tool_schema_names_match_registered_handlers():
    schema_names = {tool["name"] for tool in TOOLS}
    handler_names = set(TOOL_HANDLERS)
    missing_from_schemas = sorted(handler_names - schema_names)
    missing_from_handlers = sorted(schema_names - handler_names)

    assert schema_names == handler_names, (
        "Tool surface mismatch: "
        f"missing from schemas: {missing_from_schemas}; "
        f"missing from handlers: {missing_from_handlers}"
    )


def test_memory_decision_schema_contract():
    tool = next(tool for tool in TOOLS if tool["name"] == "memory_decision")
    schema = tool["inputSchema"]

    assert schema["required"] == ["user_prompt"]
    assert "user_prompt" in schema["properties"]
    assert "session_id" in schema["properties"]
    assert "Does not retrieve memory" in tool["description"]
