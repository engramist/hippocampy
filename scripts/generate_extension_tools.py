#!/usr/bin/env python3
"""Generate extension tool definitions from campy tool schemas.

B293 strategy (least invasive):
- Preserve existing handwritten extension tool definitions in
  extensions/hippocampy/src/index.ts.
- Generate only schema tools that are NOT already handwritten there.

This keeps current aliases/transformParams behavior intact while making
new MCP tools schema-driven by default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from campy.brain.thalamus.tool_schemas import TOOLS


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_TS = REPO_ROOT / "extensions/hippocampy/src/index.ts"
OUT_TS = REPO_ROOT / "extensions/hippocampy/src/generated_tools.ts"


def _extract_handwritten_tool_names(index_source: str) -> set[str]:
    return set(re.findall(r'name:\s*"([^"]+)"', index_source))


def _js_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value)


def _title_from_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_"))


def _opts(schema: dict, allowed: tuple[str, ...]) -> str:
    fields = []
    for key in allowed:
        if key in schema:
            fields.append(f"{key}: {_js_value(schema[key])}")
    if not fields:
        return ""
    return ", { " + ", ".join(fields) + " }"


def _schema_to_typebox(schema: dict) -> str:
    stype = schema.get("type")

    if stype == "string":
        enum_vals = schema.get("enum")
        if enum_vals:
            literals = ", ".join(f"Type.Literal({_js_value(v)})" for v in enum_vals)
            return f"Type.Union([{literals}]{_opts(schema, ('description', 'default'))})"
        return f"Type.String({_opts(schema, ('description', 'default', 'pattern', 'minLength', 'maxLength')).strip(', ') or '{}'})"

    if stype in {"integer", "number"}:
        return f"Type.Number({_opts(schema, ('description', 'default', 'minimum', 'maximum')).strip(', ') or '{}'})"

    if stype == "boolean":
        return f"Type.Boolean({_opts(schema, ('description', 'default')).strip(', ') or '{}'})"

    if stype == "array":
        item_schema = schema.get("items") or {"type": "object", "additionalProperties": True}
        item_expr = _schema_to_typebox(item_schema)
        return f"Type.Array({item_expr}{_opts(schema, ('description', 'default', 'minItems', 'maxItems'))})"

    if stype == "object":
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if props:
            lines: list[str] = []
            for key, value in props.items():
                expr = _schema_to_typebox(value)
                if key not in required:
                    expr = f"Type.Optional({expr})"
                lines.append(f"    {key}: {expr},")
            additional = schema.get("additionalProperties")
            obj_opts: list[str] = []
            if "description" in schema:
                obj_opts.append(f"description: {_js_value(schema['description'])}")
            if additional is not None:
                obj_opts.append(f"additionalProperties: {_js_value(additional)}")
            if obj_opts:
                opts = ", { " + ", ".join(obj_opts) + " }"
            else:
                opts = ""
            return "Type.Object({\n" + "\n".join(lines) + "\n  }" + opts + ")"
        obj_opts = ["additionalProperties: true"]
        if "description" in schema:
            obj_opts.append(f"description: {_js_value(schema['description'])}")
        return "Type.Object({}, { " + ", ".join(obj_opts) + " })"

    # Fallback for unsupported schema shapes.
    return "Type.Object({}, { additionalProperties: true })"


def _render_generated_tools() -> str:
    index_source = INDEX_TS.read_text()
    handwritten_names = _extract_handwritten_tool_names(index_source)
    generated = [tool for tool in TOOLS if tool["name"] not in handwritten_names]

    entries: list[str] = []
    for tool in generated:
        params_expr = _schema_to_typebox(tool.get("inputSchema") or {"type": "object", "additionalProperties": True})
        label = f"{_title_from_name(tool['name'])} (HippoCampy)"
        entry = (
            "  {\n"
            f"    name: {_js_value(tool['name'])},\n"
            f"    label: {_js_value(label)},\n"
            f"    description: {_js_value(tool.get('description', ''))},\n"
            f"    parameters: {params_expr},\n"
            "  },"
        )
        entries.append(entry)

    body = "\n".join(entries)

    return (
        "/*\n"
        " * AUTO-GENERATED FILE. DO NOT EDIT.\n"
        " *\n"
        " * Source: campy/brain/thalamus/tool_schemas.py (TOOLS)\n"
        " * Strategy: additive generation for tools not already handwritten in\n"
        " * extensions/hippocampy/src/index.ts.\n"
        " *\n"
        " * Regenerate with:\n"
        " *   python scripts/generate_extension_tools.py\n"
        " */\n\n"
        "import { Type, type TSchema } from \"@sinclair/typebox\";\n\n"
        "export type GeneratedToolDefinition = {\n"
        "  name: string;\n"
        "  label: string;\n"
        "  description: string;\n"
        "  parameters: TSchema;\n"
        "};\n\n"
        "export const GENERATED_TOOL_DEFINITIONS: GeneratedToolDefinition[] = [\n"
        f"{body}\n"
        "];\n"
    )


def main() -> None:
    rendered = _render_generated_tools()
    OUT_TS.write_text(rendered)
    print(f"Wrote {OUT_TS.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
