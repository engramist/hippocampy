"""Step 3 of the e2e plan: answer from the graph. The subject-anchored `query_hits.*` rows enter the bundle as one
`graph_facts` section, in the fact contract's fixed-shape lines (docs/fact-contract.md, section 3).

What fires, and what it shows, is decided by the graph and the question analysis, never by Python over text:
  * the SUBJECT, the object CONCEPTS and the FACT ROWS come only from the named queries `query_hits.subject`,
    `query_hits.objects` and `query_hits.facts` (exact label matches in SPARQL; anchored on the subject; each row
    carries its EVIDENCED_BY turn and date);
  * a result over `MAX_FACTS` distinct facts (`query_hits.facts_count`) is too broad: no section;
  * the SHAPE is the question analysis's closed set (count, list, latest, when, yes_no, ...). It decides only how
    the rows are presented, and which computed block (`facts_count`, `facts_latest`, `facts_exist`) heads them.

Python formats the rows; it does not count, filter or join them. Every rendered row keeps its source turn (date and
the quote). Behind `[retrieval] graph_facts` (env `CAMPY_GRAPH_FACTS`, default off, in no profile). When it is on,
the bundle compiler does not build the graph_count section (graph count is folded into these queries); the
graph_count flag itself is left in place.
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)

SECTION_TYPE = "graph_facts"
MAX_FACTS = 25          # the step-Q hit rule's MAXROWS: more distinct facts than this is too broad
_QUOTE_CHARS = 200
_SEP = " · "


def graph_facts_enabled(config: dict | None) -> bool:
    """`[retrieval] graph_facts` (default false; env `CAMPY_GRAPH_FACTS=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("graph_facts", False))


def _day(value: Any) -> str:
    return str(value)[:10] if value else ""


def _object(row: dict) -> str:
    label = str(row.get("object_text") or row.get("object_id") or "").strip()
    kinds = [k for k in str(row.get("kinds") or "").split("|") if k]
    return f"{label} ({', '.join(kinds)})" if kinds else label


def fact_line(subject: str, row: dict) -> str:
    """One fixed-shape line per fact: subject · predicate · object (kinds) · when <time phrase> · said <turn date> ·
    "<quote>". The date and the quote are the fact's source turn."""
    parts = ["[fact] " + subject, str(row.get("predicate") or "").replace("_", " "), _object(row)]
    if row.get("time_text"):
        parts.append(f"when {row['time_text']}")
    parts.append(f"said {_day(row.get('occurred_at'))}")
    quote = " ".join(str(row.get("quote") or "").split())[:_QUOTE_CHARS]
    if quote:
        parts.append(f'"{quote}"')
    return _SEP.join(p for p in parts if p)


def _rows(n: int) -> str:
    return f"{n} row" if n == 1 else f"{n} rows"


def computed_block(shape: str, subject: str, rows: list[dict], count: dict | None, latest: dict | None,
                   exists: bool | None) -> str | None:
    """The block that heads the fact lines for a computed shape, or None for a plain fact question. Each figure is
    a query's result (`facts_count`, `facts_latest`, `facts_exist`); the object list repeats the rows in order."""
    objects = "; ".join(dict.fromkeys(_object(r) for r in rows))
    if shape == "count" and count is not None:
        return f"[computed: count, {int(count.get('objects') or 0)} objects] {subject} → {objects}"
    if shape == "list":
        return f"[computed: list, {_rows(len(rows))}] {subject} → {objects}"
    if shape == "latest" and latest:
        return f"[computed: latest] {subject} → {_object(latest)} (said {_day(latest.get('occurred_at'))})"
    if shape == "yes_no" and exists is not None:
        return f"[computed: exists] {subject} → {'yes' if exists else 'not recorded'} ({_rows(len(rows))})"
    if shape == "when":
        return f"[computed: dated, {_rows(len(rows))}, oldest first] {subject}"
    return None


def render(shape: str, subject: str, rows: list[dict], count: dict | None = None, latest: dict | None = None,
           exists: bool | None = None) -> str:
    head = computed_block(shape, subject, rows, count, latest, exists)
    lines = [head] if head else []
    lines += [fact_line(subject, r) for r in rows]
    return "\n".join(lines)


async def build_graph_facts_section(db, query: str, config: dict, analysis=None):
    """The `graph_facts` BundleSection, or None (flag off, no subject or object Concept resolved, no fact, too broad,
    or any failure). The normal pipeline answers either way."""
    if not graph_facts_enabled(config):
        return None
    try:
        from campy.brain.hippocampus.graph.gateway import get_gateway
        from campy.brain.hippocampus.graph.queries.query_hits import question_terms
        from campy.brain.thalamus.bundle_compiler import BundleSection

        gw = get_gateway(db)
        pairs = question_terms(query)
        subj = await gw.run("query_hits.subject", pairs=pairs)
        if not subj:
            return None
        sid, subject = subj[0]["sid"], str(subj[0].get("label") or "")
        kids = [r["kid"] for r in await gw.run("query_hits.objects", terms=[t for t, _ in pairs], sid=sid)]
        if not kids:
            return None
        counted = await gw.run("query_hits.facts_count", sid=sid, kids=kids)
        n_facts = int((counted[0].get("facts") if counted else 0) or 0)
        if n_facts == 0 or n_facts > MAX_FACTS:
            return None
        rows = await gw.run("query_hits.facts", sid=sid, kids=kids)
        shape = getattr(analysis, "shape", None) or "open"
        latest = exists = None
        if shape == "latest":
            got = await gw.run("query_hits.facts_latest", sid=sid, kids=kids)
            latest = got[0] if got else None
        if shape == "yes_no":
            got = await gw.run("query_hits.facts_exist", sid=sid, kids=kids)
            exists = bool(got[0].get("exists")) if got else None
        text = render(shape, subject, rows, counted[0] if counted else None, latest, exists)
        return BundleSection(
            section_type=SECTION_TYPE,
            content=[{"text": text, "type": "GraphFacts", "confidence": 0.9, "pathway_strength": 0.9}],
            source_node_ids=list(dict.fromkeys(str(r["observation_id"]) for r in rows if r.get("observation_id"))),
            token_estimate=max(1, len(text) // 4),
            reads=["shape"] if analysis is not None else [],
        )
    except Exception as e:
        _logger.warning("Error in build_graph_facts_section: %s", e)
        return None
