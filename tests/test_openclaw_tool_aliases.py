from pathlib import Path
import re

from mcp_engine.tools import TOOL_HANDLERS

EXPECTED_ALIASES = {
    "current_truth": {"memory_search", "memory_recall", "memory_get"},
    "notify_turn": {"memory_store", "memory_ingest", "record_turn"},
    "explore_graph": {"traverse_graph", "explore_memory"},
    "complete_quest": {"finish_quest"},
    "branch_quest": {"create_subquest"},
}


def _extract_tool_definitions(source: str):
    pattern = re.compile(r'\{\s*name:\s*"([^"]+)"(.*?)\}', re.DOTALL)
    tools = []
    for name, rest in pattern.findall(source):
        call_name_match = re.search(r'callName:\s*"([^"]+)"', rest)
        call_name = call_name_match.group(1) if call_name_match else name
        tools.append({"name": name, "callName": call_name})
    return tools


def _load_tool_registry():
    source = Path("extensions/hippocampy/src/index.ts").read_text()
    tools = _extract_tool_definitions(source)
    return {tool["name"]: tool["callName"] for tool in tools}


def test_all_mcp_tools_registered():
    call_map = _load_tool_registry()
    primary_missing = set(TOOL_HANDLERS.keys()) - set(call_map.keys())
    assert not primary_missing, f"Missing tool registrations: {primary_missing}"


def test_common_aliases_resolve_to_primary():
    call_map = _load_tool_registry()
    for primary, aliases in EXPECTED_ALIASES.items():
        for alias in aliases:
            assert alias in call_map, f"Alias {alias} not registered"
            assert (
                call_map[alias] == primary
            ), f"Alias {alias} should call {primary} but calls {call_map[alias]}"


def test_aliases_are_unique():
    call_map = _load_tool_registry()
    alias_targets = {}
    for name, call_name in call_map.items():
        if name == call_name:
            continue
        if name in alias_targets and alias_targets[name] != call_name:
            raise AssertionError(f"Alias {name} maps to multiple primaries")
        alias_targets[name] = call_name
    assert len(alias_targets) == len(set(alias_targets)), "Alias collision detected"


def test_memory_search_alias_respects_current_truth():
    call_map = _load_tool_registry()
    assert (
        call_map.get("memory_search") == "current_truth"
    ), "memory_search should resolve to current_truth"
