#!/usr/bin/env python3
"""
scripts/check_schema_conformance.py — B406 Schema Conformance Guard.

Detects Cypher queries that reference node or relationship properties that do
not exist in the schema defined in `campy/brain/hippocampus/schema.py`.

In Kùzu:
- Non-existent property reads return NULL silently.
- Non-existent property writes raise a BinderException at runtime.

This guard derives authoritative properties directly from `schema.py`
(NODE_TABLES, REL_TABLES, and SCHEMA_MIGRATIONS, including comprehension-generated
columns), scopes variable bindings within each NamedQuery (and UNION branch),
and validates all property references.

A ratchet baseline is recorded in `scripts/schema_conformance_baseline.json`.
Any increase in violations or any newly introduced violation fails CI.

Usage:
    python3 scripts/check_schema_conformance.py            # Check against baseline (CI)
    python3 scripts/check_schema_conformance.py --update    # Update baseline
    python3 scripts/check_schema_conformance.py --verbose   # Show detailed breakdown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Add repo root to sys.path so script can be run standalone
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from campy.brain.hippocampus.graph.queries import REGISTRY  # noqa: E402
from campy.brain.hippocampus.schema import get_all_table_properties  # noqa: E402

BASELINE_PATH = Path(__file__).resolve().parent / "schema_conformance_baseline.json"


@dataclass(frozen=True)
class Violation:
    query: str
    table: str
    property: str
    kind: str  # "dot_property", "inline_node", "inline_rel"
    detail: str


def clean_cypher(cypher: str) -> str:
    """Strip comments and string literals from Cypher text."""
    # Block comments
    c = re.sub(r"/\*.*?\*/", "", cypher, flags=re.DOTALL)
    # Line comments
    c = re.sub(r"//[^\n]*", "", c)
    # String literals with escapes
    c = re.sub(r'"(?:\\.|[^"\\])*"', '""', c)
    c = re.sub(r"'(?:\\.|[^'\\])*'", "''", c)
    return c


def scan_query_violations(
    query_name: str,
    cypher: str,
    schema_props: dict[str, set[str]],
) -> list[Violation]:
    """Scan a single Cypher query for references to undeclared properties."""
    violations: list[Violation] = []

    # Queries containing UNION / UNION ALL have independent variable scopes per branch
    branches = re.split(r"\bUNION\s+(?:ALL\s+)?", cypher, flags=re.IGNORECASE)

    for branch in branches:
        cleaned = clean_cypher(branch)
        var_to_tables: dict[str, set[str]] = {}

        # 1. Match node patterns: (var:Label)
        for m in re.finditer(r"\(\s*([a-zA-Z0-9_]+)\s*:\s*([a-zA-Z0-9_]+)", cleaned):
            var, label = m.group(1), m.group(2)
            if label in schema_props:
                var_to_tables.setdefault(var, set()).add(label)

        # 2. Match rel patterns: -[var:RelType]- or -[var:R1|R2]-
        for m in re.finditer(r"-\[\s*([a-zA-Z0-9_]+)\s*:\s*([a-zA-Z0-9_|*.]+)", cleaned):
            var, rels = m.group(1), m.group(2).split("|")
            for r in rels:
                # Strip variable-length path modifiers like *1..5
                r_name = r.split("*")[0].strip()
                if r_name in schema_props:
                    var_to_tables.setdefault(var, set()).add(r_name)

        # 3. Check inline rel pattern property maps: -[:RelType { ... }]- or -[var:RelType { ... }]-
        for m in re.finditer(r"-\[\s*(?:[a-zA-Z0-9_]*\s*:\s*)?([a-zA-Z0-9_]+)\s*\{([^}]*)\}", cleaned):
            rel_type, props_str = m.group(1), m.group(2)
            if rel_type in schema_props:
                for pm in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:", props_str):
                    prop = pm.group(1)
                    if prop not in schema_props[rel_type]:
                        violations.append(
                            Violation(
                                query=query_name,
                                table=rel_type,
                                property=prop,
                                kind="inline_rel",
                                detail=f"inline rel {rel_type}.{prop}",
                            )
                        )

        # 4. Check inline node pattern property maps: (:Label { ... }) or (var:Label { ... })
        for m in re.finditer(r"\(\s*(?:[a-zA-Z0-9_]*\s*:\s*)?([a-zA-Z0-9_]+)\s*\{([^}]*)\}", cleaned):
            label, props_str = m.group(1), m.group(2)
            if label in schema_props:
                for pm in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:", props_str):
                    prop = pm.group(1)
                    if prop not in schema_props[label]:
                        violations.append(
                            Violation(
                                query=query_name,
                                table=label,
                                property=prop,
                                kind="inline_node",
                                detail=f"inline node {label}.{prop}",
                            )
                        )

        # 5. Check dot property accesses: var.prop
        for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", cleaned):
            var, prop = m.group(1), m.group(2)
            if var in var_to_tables:
                tables = var_to_tables[var]
                # Valid if property exists on ANY of candidate tables
                valid = any(prop in schema_props[t] for t in tables)
                if not valid:
                    table_str = "|".join(sorted(tables))
                    violations.append(
                        Violation(
                            query=query_name,
                            table=table_str,
                            property=prop,
                            kind="dot_property",
                            detail=f"{var}.{prop} on {table_str}",
                        )
                    )

    return violations


def scan_all_violations(schema_props: dict[str, set[str]]) -> list[Violation]:
    """Scan all registered NamedQueries for schema violations.

    Returns deduplicated violations keyed by (query, table, property).
    """
    seen: set[tuple[str, str, str]] = set()
    unique_violations: list[Violation] = []

    for named_query in sorted(REGISTRY, key=lambda q: q.name):
        query_violations = scan_query_violations(named_query.name, named_query.cypher, schema_props)
        for v in query_violations:
            key = (v.query, v.table, v.property)
            if key not in seen:
                seen.add(key)
                unique_violations.append(v)

    return unique_violations


def load_baseline(path: Path = BASELINE_PATH) -> dict:
    """Load checked-in baseline from json."""
    if not path.exists():
        return {"total_violations": 0, "violations": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(violations: list[Violation], path: Path = BASELINE_PATH) -> None:
    """Write current violations list to baseline json."""
    data = {
        "total_violations": len(violations),
        "violations": [asdict(v) for v in violations],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update scripts/schema_conformance_baseline.json to match current codebase",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print all individual violations",
    )
    args = parser.parse_args(argv)

    schema_props = get_all_table_properties()
    current_violations = scan_all_violations(schema_props)

    if args.update:
        write_baseline(current_violations)
        print(f"Updated schema conformance baseline: {len(current_violations)} violations recorded.")
        return 0

    baseline = load_baseline()
    baseline_list = baseline.get("violations", [])
    baseline_keys = {(v["query"], v["table"], v["property"]) for v in baseline_list}
    current_keys = {(v.query, v.table, v.property): v for v in current_violations}

    new_violations = [v for k, v in current_keys.items() if k not in baseline_keys]
    fixed_violations = [k for k in baseline_keys if k not in current_keys]

    if args.verbose or new_violations:
        print(f"\n--- Schema Conformance Report ({len(current_violations)} violations) ---")
        for v in current_violations:
            marker = " [NEW]" if (v.query, v.table, v.property) not in baseline_keys else ""
            print(f"  {v.query}: {v.detail}{marker}")
        print("------------------------------------------------------------------\n")

    ok = True

    if new_violations:
        ok = False
        print(f"FAIL: {len(new_violations)} new schema violation(s) detected:")
        for v in new_violations:
            print(f"  + {v.query}: {v.detail}")
        print("\nFix the property references above to match campy/brain/hippocampus/schema.py.")

    if len(current_violations) > len(baseline_list):
        ok = False
        print(
            f"FAIL: Violation count increased: {len(baseline_list)} -> {len(current_violations)} "
            f"(+{len(current_violations) - len(baseline_list)})"
        )
    elif len(current_violations) < len(baseline_list):
        print(
            f"Violation count decreased: {len(baseline_list)} -> {len(current_violations)} "
            f"(-{len(baseline_list) - len(current_violations)})."
        )
        if fixed_violations:
            print(f"Fixed {len(fixed_violations)} violation(s):")
            for qname, table, prop in fixed_violations[:10]:
                print(f"  - {qname}: {table}.{prop}")
            if len(fixed_violations) > 10:
                print(f"    ... and {len(fixed_violations) - 10} more")
        print("Run 'python3 scripts/check_schema_conformance.py --update' to lower the baseline.")
    else:
        print(f"Violation count unchanged: {len(current_violations)}")

    if not ok:
        return 1

    print("Schema conformance ratchet OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
