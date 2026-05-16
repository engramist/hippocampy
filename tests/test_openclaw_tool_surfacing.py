from pathlib import Path
import re
import json

from mcp_engine.tool_schemas import TOOLS

EXPECTED_ALIAS_TOOLS = [
    "memory_recall",
    "memory_search",
    "memory_get",
    "memory_store",
    "memory_search_analogies",
    "memory_status",
    "memory_open_loops",
]

# Core tools that should be discoverable without aliases
CORE_TOOLS = [
    "notify_turn",
    "current_truth",
    "branch_quest",
    "complete_quest",
    "explore_graph",
]


def _extract_registered_tool_names(source: str) -> list[str]:
    return re.findall(r'name:\s*"([^\"]+)"', source)


def _extract_tool_definitions(source: str) -> dict[str, dict]:
    """Extract tool definitions from the toolDefinitions array."""
    # Find the toolDefinitions array
    match = re.search(r'const toolDefinitions: BrainToolDefinition\[\] = \[(.*?)\];', source, re.DOTALL)
    if not match:
        return {}

    array_content = match.group(1)
    # Extract each tool object { name: "...", ... }
    tool_objects = re.findall(r'\{\s*name:\s*"([^"]+)".*?(?=\},\s*\{|^\s*\])', array_content, re.DOTALL)
    return {name: True for name in tool_objects}


def test_openclaw_extension_registers_all_tools():
    """Verify all canonical tools are registered in the extension."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()
    registered = set(_extract_registered_tool_names(source))

    canonical_names = {tool["name"] for tool in TOOLS}
    missing = canonical_names - registered
    assert not missing, f"Missing canonical Brain tools: {sorted(missing)}"

    missing_aliases = set(EXPECTED_ALIAS_TOOLS) - registered
    assert not missing_aliases, f"Missing alias tools: {sorted(missing_aliases)}"


def test_openclaw_extension_registers_core_tools():
    """Verify all core 5+ tools are registered."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()
    registered = set(_extract_registered_tool_names(source))

    missing_core = set(CORE_TOOLS) - registered
    assert not missing_core, \
        f"Missing core Brain tools: {sorted(missing_core)}. " \
        f"These are required for basic agent operation."


def test_openclaw_extension_has_proper_descriptions():
    """Verify all registered tools have descriptions."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()

    # Check that description field exists for each tool definition
    tool_names = _extract_registered_tool_names(source)

    for tool_name in tool_names:
        pattern = rf'name:\s*"{re.escape(tool_name)}".*?description:\s*["\']'
        assert re.search(pattern, source, re.DOTALL), \
            f"Tool '{tool_name}' missing description"


def test_openclaw_extension_has_proper_parameters():
    """Verify all registered tools have parameter schemas."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()

    # Check that parameters field exists for each tool definition
    tool_names = _extract_registered_tool_names(source)

    for tool_name in tool_names:
        pattern = rf'name:\s*"{re.escape(tool_name)}".*?parameters:\s*\w+Params'
        assert re.search(pattern, source, re.DOTALL), \
            f"Tool '{tool_name}' missing parameters"


def test_openclaw_extension_register_function_exists():
    """Verify the register function exists and calls registerBrainTool."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()

    # Check for register function with api parameter
    assert re.search(r'register\s*\(\s*api:\s*any\s*\)', source), \
        "Plugin must export a register(api) function"

    # Check for tool registration calls
    assert 'registerBrainTool' in source, \
        "Plugin must call registerBrainTool() to register tools"

    # Check that tools are registered from the toolDefinitions array
    assert 'toolDefinitions.forEach(registerBrainTool)' in source, \
        "Plugin must register all tool definitions via forEach"


def test_openclaw_manifest_exists():
    """Verify the plugin manifest file exists and is valid."""
    manifest_path = Path("extensions/hippocampy/openclaw.plugin.json")
    assert manifest_path.exists(), "openclaw.plugin.json not found"

    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("id") == "hippocampy"
    assert manifest.get("kind") == "memory"
    assert manifest.get("name") == "HippoCampy"
    assert "description" in manifest


def test_package_json_name_matches_manifest():
    """Verify package.json and manifest have matching plugin IDs."""
    manifest_path = Path("extensions/hippocampy/openclaw.plugin.json")
    package_path = Path("extensions/hippocampy/package.json")

    manifest = json.loads(manifest_path.read_text())
    package = json.loads(package_path.read_text())

    manifest_id = manifest.get("id")
    package_name = package.get("name")

    assert manifest_id == package_name, \
        f"Plugin ID mismatch: manifest id='{manifest_id}' vs package name='{package_name}'"


def test_openclaw_tools_route_to_brain_daemon():
    """Verify all registered tools route to Brain daemon via callTool()."""
    source = Path("extensions/hippocampy/src/index.ts").read_text()

    # Check that brain.callTool is used in the execute handler
    assert 'brain.callTool(' in source, \
        "Tools must route to Brain daemon via brain.callTool()"

    # Check that core tools route to correct Brain daemon tools
    for core_tool in CORE_TOOLS:
        # For each core tool, verify it's either a direct call or aliases to it
        if core_tool == "notify_turn":
            assert 'callName: "notify_turn"' in source or \
                   'brain.callTool("notify_turn"' in source
        elif core_tool == "current_truth":
            assert 'callName: "current_truth"' in source or \
                   'brain.callTool("current_truth"' in source
