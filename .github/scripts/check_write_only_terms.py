#!/usr/bin/env python3
"""
Write-only graph term ratchet (B518).

A graph term nothing reads is cost with no benefit: it is written on every
capture and never used to answer anything (PRINCIPLES.md, Principle 2; the
"Design-review checklist" in skills/campy-graph/SKILL.md asks "is every new
predicate read by something?"). This check makes that question mechanical.

Terms (declared in campy/brain/hippocampus/schema.py, so the code writes them):
  edge:NAME      every relationship table in REL_TABLES
  prop:NAME      every node column in NODE_TABLES and every extra column on a
                 relationship table (the store keeps them all as campy:NAME)

A term is READ when `campy:NAME` appears in a SPARQL read site:
  1. the sparql of a non-mutating NamedQuery (campy/brain/hippocampus/graph/queries/)
  2. the WHERE part of a mutating NamedQuery (INSERT/DELETE ... WHERE reads too)
  3. any *.rq file
  4. a string literal elsewhere under campy/ that contains SELECT, ASK or CONSTRUCT
     (excluding schema.py itself, which only declares)
Not counted: Cypher text, and dynamic names built at run time (`campy:{table}`).
A term read only that way shows up in the baseline; that is a known limit.

Ratchet (same shape as scripts/check_cypher_ratchet.py): terms already write-only
live in .github/scripts/write_only_terms_baseline.txt, one per line. CI fails when
  - a term is write-only and not in the baseline (new dead term: add a reader, or
    do not add the term), or
  - a baselined term is now read (remove it from the baseline).

Usage:
    python .github/scripts/check_write_only_terms.py            # check
    python .github/scripts/check_write_only_terms.py --update   # rewrite the baseline
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "write_only_terms_baseline.txt"

_TERM_RE = re.compile(r"campy:([A-Za-z_][A-Za-z0-9_]*)")
_READ_KW_RE = re.compile(r"\b(SELECT|ASK|CONSTRUCT)\b")
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_REL_NAME_RE = re.compile(r"CREATE REL TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*)\)\s*$", re.DOTALL)


def _split_top_level(text):
    """Split on commas not nested in brackets (FLOAT[384], STRUCT(...))."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _column_names(body):
    names = set()
    for item in _split_top_level(body):
        if item.startswith(("PRIMARY KEY", "FROM ", "REL_TYPE")):
            continue
        names.add(item.split()[0])
    return names


def declared_terms(node_tables, rel_tables):
    """Return the set of 'edge:X' / 'prop:X' terms the schema declares."""
    terms = set()
    for body in node_tables.values():
        terms |= {f"prop:{c}" for c in _column_names(body)}
    for ddl in rel_tables:
        m = _REL_NAME_RE.search(ddl.strip())
        if not m:
            continue
        terms.add(f"edge:{m.group(1)}")
        terms |= {f"prop:{c}" for c in _column_names(m.group(2))}
    return terms


def _names(text):
    return set(_TERM_RE.findall(text))


def read_names_from_queries(queries):
    """Names read by NamedQuery sparql (rules 1 and 2)."""
    out = set()
    for q in queries:
        sparql = getattr(q, "sparql", None)
        if not sparql:
            continue
        if not getattr(q, "mutating", False):
            out |= _names(sparql)
        else:
            m = _WHERE_RE.search(sparql)
            if m:
                out |= _names(sparql[m.end():])
    return out


def read_names_from_files(root):
    """Names read by .rq files and by SPARQL read strings in python (rules 3 and 4)."""
    out = set()
    campy_dir = root / "campy"
    for rq in campy_dir.rglob("*.rq"):
        out |= _names(rq.read_text(encoding="utf-8", errors="ignore"))
    skip = {"campy/brain/hippocampus/schema.py"}
    for py in campy_dir.rglob("*.py"):
        rel = py.relative_to(root).as_posix()
        if rel in skip or "/queries/" in rel:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _READ_KW_RE.search(node.value):
                    out |= _names(node.value)
    return out


def collect_queries():
    """Import the query modules and return every NamedQuery they define."""
    import importlib
    import pkgutil

    from campy.brain.hippocampus.graph import queries as pkg
    from campy.brain.hippocampus.graph.gateway import NamedQuery

    found = []

    def visit(value):
        if isinstance(value, NamedQuery):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            for v in value:
                visit(v)

    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        for value in vars(mod).values():
            visit(value)
    return found


def write_only_terms(declared, read_names):
    """Declared terms whose bare name is never read."""
    return {t for t in declared if t.split(":", 1)[1] not in read_names}


def compare(write_only, baseline):
    """Return (new_terms, now_read_terms), both sorted."""
    return sorted(write_only - baseline), sorted(baseline - write_only)


def load_baseline(path=BASELINE_PATH):
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def write_baseline(terms, path=BASELINE_PATH):
    header = ("# Graph terms declared in schema.py that no SPARQL read site uses (B518).\n"
              "# Ratchet: do not add lines; remove a line once something reads the term.\n"
              "# Regenerate: python .github/scripts/check_write_only_terms.py --update\n")
    path.write_text(header + "".join(f"{t}\n" for t in sorted(terms)), encoding="utf-8")


def current_write_only(root=REPO_ROOT):
    sys.path.insert(0, str(root))
    from campy.brain.hippocampus.schema import NODE_TABLES, REL_TABLES

    read = read_names_from_queries(collect_queries()) | read_names_from_files(root)
    return write_only_terms(declared_terms(NODE_TABLES, REL_TABLES), read)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the baseline (deliberate, reviewable)")
    args = ap.parse_args(argv)

    wo = current_write_only()
    if args.update:
        write_baseline(wo)
        print(f"Baseline updated: {len(wo)} write-only terms")
        return 0

    new, now_read = compare(wo, load_baseline())
    ok = True
    if new:
        ok = False
        print("FAIL: new write-only graph terms (declared in schema.py, read by no SPARQL query):")
        for t in new:
            print(f"  {t}")
        print("Add a query that reads each one, or do not add the term. "
              "See skills/campy-graph/SKILL.md, Design-review checklist item 6.")
    if now_read:
        ok = False
        print("FAIL: baselined terms are now read; remove them from "
              ".github/scripts/write_only_terms_baseline.txt (or run --update):")
        for t in now_read:
            print(f"  {t}")
    if ok:
        print(f"Write-only terms OK ({len(wo)} baselined).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
