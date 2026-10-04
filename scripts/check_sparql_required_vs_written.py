#!/usr/bin/env python3
"""
scripts/check_sparql_required_vs_written.py — B427 batch-4 static check.

Flags SPARQL SELECT queries that chain a node property as a REQUIRED
(non-OPTIONAL) triple pattern when no write query anywhere in the registry
ever asserts that property as a ground triple. That specific mismatch is the
strongest, zero-false-positive signal for the "required-vs-optional property
divergence" bug class documented in backlog/B427.md batch 3c/4: a property
that is read as required but has NO writer at all can never match, so the
read silently drops every row for that node type, forever (the
`arc.get_goal_evidence`/`VictoryCondition.condition_type` bug this script
would have caught: the column exists in schema.py's DDL but is never once
the target of an INSERT triple in any registered query).

This is deliberately narrower than a full write-vs-read nullability audit
(most write queries route every non-PK property through the same
UNDEF-on-None VALUES injection, so "sometimes written, sometimes not" is
structurally true almost everywhere and would flag too much to be useful as
an automated gate — that broader judgment call needs a human cross-checking
real call-site behavior, per the manual audit in B427's card). This script
only flags the unambiguous case: a property with ZERO writers anywhere.

KNOWN FALSE-POSITIVE CLASSES (confirmed while building this — read every
finding before treating it as a bug, this is a report to triage, not a CI
gate):
  1. Node types created via `OxigraphClient.write_node()`/`write_edge()`
     directly from Python rather than through a NamedQuery's `sparql=`
     INSERT block (e.g. GlobalConstraint, AgentWorker) — this script only
     scans `REGISTRY`'s SPARQL text, so it can't see those writers at all.
  2. Mutating NamedQueries with `cypher=` but no `sparql=`, dispatched
     through gateway.py's `_handle_oxigraph_handler()` name-matched
     special-case Python code instead of generic SPARQL (e.g.
     `arc.link_mechanic_action_pattern` -> `write_edge(...)` directly) —
     same blind spot as #1, one level less obvious.
Both classes were manually verified real writers exist; treat any finding
whose type isn't built through a plain `INSERT { ?s a campy:Type ; ... }`
NamedQuery as needing that same manual check before acting on it.

Usage:
    python3 scripts/check_sparql_required_vs_written.py            # report
    python3 scripts/check_sparql_required_vs_written.py --verbose  # + which query(ies) require it
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from campy.brain.hippocampus.graph.queries import REGISTRY  # noqa: E402


def _find_where_body(sparql: str) -> str | None:
    m = re.search(r"\bWHERE\s*\{", sparql, re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    depth = 1
    j = start
    n = len(sparql)
    while j < n and depth > 0:
        if sparql[j] == "{":
            depth += 1
        elif sparql[j] == "}":
            depth -= 1
        j += 1
    return sparql[start : j - 1]


def _strip_optional_blocks(where_body: str) -> str:
    out: list[str] = []
    i, n = 0, len(where_body)
    while i < n:
        m = re.match(r"OPTIONAL\s*\{", where_body[i:])
        if m:
            start = i + m.end()
            depth = 1
            j = start
            while j < n and depth > 0:
                if where_body[j] == "{":
                    depth += 1
                elif where_body[j] == "}":
                    depth -= 1
                j += 1
            i = j
            continue
        out.append(where_body[i])
        i += 1
    return "".join(out)


_TYPE_PAT = re.compile(r"(\?\w+)\s+a\s+campy:(\w+)\b")
_PRED_PAT = re.compile(r"campy:(\w+)")


def build_written_props() -> set[str]:
    """Every predicate ever asserted as a ground triple in some INSERT/INSERT
    DATA block, across the WHOLE registry (deliberately not scoped per node
    type -- attributing an INSERT block's predicates back to "the type this
    query writes" is unreliable for edge-linking queries, whose INSERT block
    is often just `?a campy:EDGE ?b` with the type check living only in
    WHERE, and for RDF-star provenance-cascade annotations. Written via a
    param (UNDEF-capable) or a literal constant both count -- this only cares
    whether a writer exists AT ALL, anywhere, not its null-handling or which
    node type it's attached to."""
    written: set[str] = set()
    for q in REGISTRY:
        if not q.mutating or not q.sparql:
            continue
        for ins_m in re.finditer(r"\bINSERT\s*\{(.*?)\}\s*(?:WHERE|;|$)", q.sparql, re.DOTALL | re.IGNORECASE):
            block = ins_m.group(1)
            types_here = set(re.findall(r"\ba\s+campy:(\w+)\b", block))
            written.update(set(_PRED_PAT.findall(block)) - types_here)
    return written


def find_required_props() -> dict[tuple[str, str], list[str]]:
    """For every non-mutating SELECT query, collect {(type, prop): [query names]}
    for every property chained as a REQUIRED (non-OPTIONAL) triple off a
    subject whose type is known in the same WHERE clause."""
    required: dict[tuple[str, str], list[str]] = {}
    for q in REGISTRY:
        if q.mutating or not q.sparql or "SELECT" not in q.sparql.upper():
            continue
        body = _find_where_body(q.sparql)
        if body is None:
            continue
        subj_type = dict(_TYPE_PAT.findall(body))
        required_only = _strip_optional_blocks(body)
        for cm in re.finditer(
            r"(\?\w+)\s+((?:(?:a|campy:\w+)\s+\S+\s*;\s*)+(?:a|campy:\w+)\s+\S+)\s*\.",
            required_only,
            re.DOTALL,
        ):
            subj, chain = cm.group(1), cm.group(2)
            t = subj_type.get(subj)
            if not t:
                continue
            preds = [p for p in re.findall(r"(?:^|;)\s*(a|campy:\w+)", chain) if p != "a"]
            for p in preds:
                prop = p.split(":", 1)[1]
                required.setdefault((t, prop), []).append(q.name)
    return required


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="List the offending query name(s) per finding")
    args = parser.parse_args(argv)

    written = build_written_props()
    required = find_required_props()

    findings: list[tuple[str, str, list[str]]] = []
    for (t, prop), qnames in sorted(required.items()):
        if prop not in written:
            findings.append((t, prop, sorted(set(qnames))))

    if not findings:
        print("check_sparql_required_vs_written: OK — no required-but-never-written properties found.")
        return 0

    print(f"FAIL: {len(findings)} propert(y/ies) are required (non-OPTIONAL) in a read query but "
          f"never written as a ground triple by any registered mutating query:\n")
    for t, prop, qnames in findings:
        print(f"  {t}.{prop}")
        if args.verbose:
            for qn in qnames:
                print(f"      required by: {qn}")
    print(
        "\nEach of these properties can NEVER match, so the read query(ies) above drop every row "
        "for that node type, unconditionally. Either wrap the property in OPTIONAL { ... } (if it's "
        "genuinely allowed to be unset) or add a writer for it (if it's supposed to always be set)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
