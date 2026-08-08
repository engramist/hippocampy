# tests/test_generate_extension_tools.py
"""Test the tool_schemas.TOOLS -> extension TypeBox codegen script.

B310: _schema_to_typebox() assumed schema["type"] was always a single
string. Any inputSchema property with a list "type" (multi-type JSON
Schema, e.g. {"type": ["integer", "string"]} or {"type": ["integer",
"null"]}) raised TypeError: unhashable type: 'list' from
`stype in {"integer", "number"}`. Undetected until B309 because the
script only walks tools NOT already handwritten in index.ts, and every
pre-existing multi-type field happened to already be handwritten there.
"""
from scripts.generate_extension_tools import _schema_to_typebox


def test_single_string_type_still_works():
    """Regression guard: the common case must be unaffected by the fix."""
    assert _schema_to_typebox({"type": "string"}) == "Type.String({})"


def test_multi_type_integer_or_string_does_not_raise():
    """{"type": ["integer", "string"]} - used by several real step fields -
    must produce a Union, not raise TypeError: unhashable type: 'list'."""
    result = _schema_to_typebox({"type": ["integer", "string"]})
    assert result.startswith("Type.Union([")
    assert "Type.Number(" in result
    assert "Type.String(" in result


def test_multi_type_nullable_integer_does_not_raise():
    """{"type": ["integer", "null"]} - the exact shape that crashed while
    implementing B309's entity_ref field - must map "null" to Type.Null()."""
    result = _schema_to_typebox({"type": ["integer", "null"]})
    assert result.startswith("Type.Union([")
    assert "Type.Number(" in result
    assert "Type.Null()" in result


def test_multi_type_preserves_member_constraints():
    """Per-member schema fields (e.g. description) should still reach the
    non-null member's TypeBox call, not get dropped by the union branch."""
    result = _schema_to_typebox({"type": ["integer", "null"], "description": "count"})
    assert "description" in result


def test_generator_runs_end_to_end_against_real_tool_schemas():
    """The actual crash was only reachable by running the full generator
    against the real, current TOOLS list (not just a synthetic schema) -
    this proves the fix holds for every tool actually registered today."""
    from scripts.generate_extension_tools import _render_generated_tools

    rendered = _render_generated_tools()
    assert "GENERATED_TOOL_DEFINITIONS" in rendered
