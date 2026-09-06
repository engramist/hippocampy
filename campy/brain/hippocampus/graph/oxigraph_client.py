"""
campy/brain/hippocampus/graph/oxigraph_client.py — Oxigraph RDF-star client (B389)

THIS IS THE ONLY FILE THAT IMPORTS pyoxigraph, mirroring kuzu_client.py's own
"only file that imports kuzu" discipline. It implements
docs/rdf-schema-mapping.md (NORMATIVE — every pattern here was re-validated
against real pyoxigraph 0.5.11 before being written; see the "pyoxigraph 0.5.11
implementation notes" section below for cases where the empirically-observed
behavior required a different technique than the spec's Turtle illustrations
alone would suggest).

Both engines coexist. This module does not remove or touch `kuzu_client.py`,
`gateway.py`'s dispatch (that's B397), or anything under `graph/queries/`
(translating the 863 named queries is B391-B396). `pyoxigraph` is dual
licensed MIT OR Apache-2.0 (confirmed via `pip show pyoxigraph` on the
installed 0.5.11 wheel: "License: MIT OR Apache-2.0" — both compatible with
this project's Apache-2.0 license, same check B390 did for sqlite-vec).

Vectors (`FLOAT[384]`) are never written here — spec §5 sends them to
`vector_store.VectorStore`, keyed by the same instance URI this module mints.
`mint_uri()` is imported from `vector_store.py` (B390) and reused verbatim,
never reimplemented, so the two stores always agree on identity.

=== pyoxigraph 0.5.11 implementation notes (empirically discovered, B389) ===

1. **Quoted-triple-as-SUBJECT cannot be constructed via the Python `Quad()` /
   `Triple()`-as-subject API in this build**, despite the docstring's type
   hints listing `Triple` as a valid subject type. `Quad(NamedNode, ...,
   Triple, ...)` (Triple as OBJECT) works; `Quad(Triple, ...)` (Triple as
   SUBJECT) raises `TypeError` from the underlying PyO3 enum extraction.
   `Store.quads_for_pattern()`'s subject parameter has the exact same
   restriction, despite its docstring too. This matches RDF 1.2's restriction
   of "triple terms" to object position.

2. **The legacy RDF-star `<< s p o >> pred obj` annotation syntax still
   parses fine in SPARQL query/update TEXT** (both `Store.query()` and
   `Store.update()`), but pyoxigraph 0.5.11 desugars it as RDF 1.2 sugar:
   *every* occurrence of `<< s p o >> pred obj` in an `INSERT DATA` mints a
   **fresh blank-node reifier** (`_:bN rdf:reifies <<( s p o )>> . _:bN
   pred obj .`) — confirmed by dumping the raw store after two separate
   `INSERT DATA` calls annotating the same triple with different
   `confidence` values: **both values persisted as two independent blank
   nodes**, not one overwritten value. This means the `<<...>>` syntax by
   itself gives exactly the "occurrence" family's accumulate-forever
   behavior, for EVERY quoted-triple write, star or occurrence alike.

3. **`DELETE DATA` / `DELETE WHERE` reject a quoted-triple pattern as a quad
   subject outright** ("expected GRAPH" parser error), for both a ground
   pattern (`DELETE DATA { << s p o >> pred obj }`) and a variable pattern
   (`DELETE WHERE { << s p o >> ?p ?o }`). There is no SPARQL-text way to
   remove an existing annotation once (2) has minted its blank node.

4. **The fix for `star`'s "at most one edge" semantics**: use the *native*
   `Store.quads_for_pattern()` / `Store.remove()` Python API instead of
   SPARQL DELETE. A `BlankNode` (unlike a `Triple`) IS an accepted subject
   for both calls. So a `star` re-write:
     a. queries for existing reifier blank nodes via the OBJECT-position
        triple term, which IS supported:
        `quads_for_pattern(None, rdf:reifies, Triple(s, p, o), DefaultGraph())`
     b. for each reifier blank node found, fetches and `store.remove()`s
        every quad with that blank node as subject (both its `rdf:reifies`
        pointer and its annotation properties)
     c. only then runs one `INSERT DATA` asserting the plain triple (a
        no-op if already present, per RDF set semantics) plus a fresh
        `<< s p o >> pred1 v1 ; pred2 v2 .` annotation block.
   Verified end-to-end: writing confidence=0.8 then confidence=0.95 for the
   same (s,p,o) leaves exactly one reifier with confidence=0.95, and plain
   traversal (`?s campy:ENABLES ?o`) still matches throughout.

5. **`occurrence` needs no such cleanup** — every write is a pure additive
   `INSERT DATA`, exactly per spec §4.2b: the base triple (idempotent), a
   fresh `<< s p o >> campy:occurrence <cid:Occurrence/{ulid}>` annotation
   (its own fresh blank-node reifier, deliberately never reused), and the
   occurrence node's own properties as ordinary ground triples (not
   quoted — the occurrence node is a real, dereferenceable URI, not a
   blank node). `SELECT ?tok WHERE { << ?s campy:LOADED ?o >>
   campy:occurrence/campy:token_estimate ?tok }` returns one row per
   occurrence, and `?s campy:LOADED ?o` (plain) keeps matching.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal as TypingLiteral

import pyoxigraph as ox

from campy.brain.hippocampus.graph.vector_store import mint_uri  # noqa: F401 (re-exported)
from campy.brain.hippocampus.schema import NODE_TABLES, REL_TABLES

# ---------------------------------------------------------------------------
# §2 — namespaces (docs/rdf-schema-mapping.md)
# ---------------------------------------------------------------------------

CAMPY_NS = "https://campy.dev/ns#"      # predicates, classes
CID_BASE = "https://campy.dev/id/"      # instances (same base as vector_store.CID_BASE)
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

_XSD_INTEGER = XSD + "integer"
_XSD_DOUBLE = XSD + "double"
_XSD_FLOAT = XSD + "float"
_XSD_BOOLEAN = XSD + "boolean"
_XSD_DATETIME = XSD + "dateTime"

RDF_REIFIES = ox.NamedNode(RDF_NS + "reifies")
OCCURRENCE_PRED = ox.NamedNode(CAMPY_NS + "occurrence")


def campy_pred(name: str) -> ox.NamedNode:
    """`campy:{name}` as a `NamedNode` — predicates and class names alike."""
    return ox.NamedNode(CAMPY_NS + name)


# ---------------------------------------------------------------------------
# §2 — ULID minting for occurrence nodes (spec: "ULID-minted, not derived —
# they are new identity, not a mapping of an existing key").
#
# No ULID library is a dependency of this project (checked: not in
# pyproject.toml, not installed). Rather than add one for a 30-line
# algorithm, this is a plain implementation of the public ULID spec
# (48-bit millisecond timestamp + 80 bits of randomness, Crockford Base32,
# 26 chars, lexicographically time-sortable) — no external dependency added.
# ---------------------------------------------------------------------------

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_ulid() -> str:
    """Generate a 26-character Crockford-Base32 ULID (48-bit ms timestamp +
    80 random bits). Lexicographic sort order matches chronological order.
    Not monotonic within the same millisecond (spec does not require it —
    "ORDER BY ?occ gives chronological order without a separate index" only
    needs coarse ordering, not a strict same-millisecond tiebreak)."""
    ms = int(time.time() * 1000)
    raw = ms.to_bytes(6, "big") + os.urandom(10)
    value = int.from_bytes(raw, "big")
    chars = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD_ALPHABET[rem])
    return "".join(reversed(chars))


def mint_occurrence_uri() -> str:
    """Mint a fresh `cid:Occurrence/{ulid}` instance URI."""
    return f"{CID_BASE}Occurrence/{generate_ulid()}"


# ---------------------------------------------------------------------------
# §3.1 — node schema introspection: parse `schema.NODE_TABLES`' DDL text into
# {table: {column: kuzu_type}} and {table: primary_key_column}, so every
# property write goes through the *single source of truth* for Kùzu column
# types instead of requiring each caller to redeclare them. This also keeps
# node-table coverage automatically exhaustive as schema.py evolves — the
# only thing that requires updating here is EDGE_REIFICATION (rel side),
# never NODE_COLUMNS (node side is parsed live from schema.py).
# ---------------------------------------------------------------------------

_COLUMN_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z0-9_\[\]]+)$")
_PK_LINE_RE = re.compile(r"PRIMARY\s+KEY\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", re.IGNORECASE)


def _parse_node_schema() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    columns: dict[str, dict[str, str]] = {}
    primary_keys: dict[str, str] = {}
    for table, ddl in NODE_TABLES.items():
        cols: dict[str, str] = {}
        pk: str | None = None
        for part in ddl.split(","):
            part = part.strip()
            if not part:
                continue
            pk_match = _PK_LINE_RE.search(part)
            if pk_match:
                pk = pk_match.group(1)
                continue
            col_match = _COLUMN_LINE_RE.match(part)
            if col_match:
                cols[col_match.group(1)] = col_match.group(2)
        if pk is None:
            raise ValueError(
                f"NODE_TABLES[{table!r}] DDL has no PRIMARY KEY — cannot mint a URI "
                f"for this table (see docs/rdf-schema-mapping.md §2)"
            )
        columns[table] = cols
        primary_keys[table] = pk
    return columns, primary_keys


NODE_COLUMNS, NODE_PRIMARY_KEYS = _parse_node_schema()


# ---------------------------------------------------------------------------
# §4.2 — EDGE_REIFICATION: the core deliverable.
#
# Exhaustive per docs/rdf-schema-mapping.md §4.2, covering every rel table
# schema.py's `REL_TABLES` currently declares — see the module docstring's
# reconciliation note above `_UNCLASSIFIED_ESCALATED` for why this is 110
# tables, not the spec's snapshot count of 102 (schema.py has grown 8 more
# rel tables since the spec's commit d3ef540, and one, CONTRADICTS, has two
# colliding DDL statements — see below).
#
# "plain"      — no properties (Kùzu DDL has zero non-FROM/TO columns).
#                Nothing to lose: repeated identical plain triples are
#                idempotent under RDF set semantics, so no call-site
#                analysis is needed for these — the schema itself proves it
#                safe. 52 tables.
# "star"       — at most one edge per (s,p,o), carrying properties.
#                Confirmed (not guessed) via actual call sites: every
#                writer for these tables uses Cypher `MERGE ... SET`
#                (upsert/overwrite-in-place semantics), never a bare
#                `CREATE`. Star's RDF-star quoted-triple + native
#                remove-old-reifier-then-insert dance (see module
#                docstring point 4) replicates this MERGE+SET overwrite
#                behavior exactly — not a data-loss regression relative to
#                today's Kùzu behavior, because Kùzu itself already
#                discards the prior property values on every MERGE+SET.
#                28 tables — includes ANOMALY_DETECTED, CO_OCCURS_WITH, and
#                OUTCOME_SIGNAL, reclassified here per spec §4.2c (2026-09-05):
#                the governing rule is "class follows the observed write
#                call site, never the name" — all three write via MERGE+SET
#                (CO_OCCURS_WITH via ON CREATE/ON MATCH SET, an accumulator
#                over a single merged edge), so all three are star despite
#                an earlier spec draft naming them "occurrence" by shape.
# "occurrence" — can legitimately repeat for the same (s,p,o). Confirmed
#                via call sites using a bare `CREATE` (no MERGE, no
#                existence check) for every write, so multiple edges with
#                distinct properties already coexist under today's Kùzu
#                behavior. 15 tables.
#
# Every classification below cites its evidence in an inline comment:
# either the call site (file:line) or "spec §4.2c" for the tables the spec
# names directly. A table with NO entry here is a hard error at write time
# (see `classify_edge()` below) — this is deliberate for the 15 tables in
# `UNCLASSIFIED_ESCALATED_TABLES` (spec §4.2d: no writer anywhere in the
# repo), documented there with the reason each could not be confidently
# classified. Do not add a table here without equally solid evidence; when
# in doubt, escalate instead (see that dict).
# ---------------------------------------------------------------------------

EdgeReification = TypingLiteral["plain", "star", "occurrence"]

EDGE_REIFICATION: dict[str, EdgeReification] = {
    # -- plain (52): property-free per schema.py REL_TABLES DDL -------------
    "ACTS_ON": "plain",
    "ANCHORED_ON_ENTITY": "plain",
    "ANCHORED_ON_GOAL": "plain",
    "ANCHORED_TO": "plain",
    "APPLIES_TO": "plain",
    "APPLIES_TO_ARCHETYPE": "plain",
    "ARC_EVENT_FROM_ARTIFACT": "plain",
    "ARC_RUN_HAS_ARTIFACT": "plain",
    "ARC_RUN_HAS_TASK": "plain",
    "ARC_RUN_HAS_WORLD_MODEL_STEP": "plain",
    "ARC_RUN_HAS_WORLD_MODEL_SUMMARY": "plain",
    "ARC_TASK_HAS_EVENT": "plain",
    "ARC_WORLD_MODEL_FROM_ARTIFACT": "plain",
    "ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT": "plain",
    "BELONGS_TO": "plain",
    "CONTAINS_LESSON": "plain",
    "CREATED_IN": "plain",
    "DATASET_BELONGS_TO_QUEST": "plain",
    "DATASET_DERIVED_FROM": "plain",
    "DEPENDS_ON": "plain",
    # DEPRECATED_BY: spec §4.2a's illustrative list names this table as a
    # member of the confidence/inferred_by/inferred_at STAR family, but the
    # LIVE schema.py DDL (`"CREATE REL TABLE IF NOT EXISTS DEPRECATED_BY ("
    # + ", ".join(f"FROM {t} TO {t}" for t in PROVENANCE_TABLES) + ")"`) has
    # carried ZERO properties since B326 retired the old SUPERSEDES table
    # and repointed mark_superseded() at DEPRECATED_BY. This is schema drift
    # since the spec's commit, not a misreading: applying the spec's own
    # top-level rule ("plain — no properties") to the table AS IT EXISTS
    # TODAY is not a guess, it is the definitionally safe answer (there is
    # no property to lose either way). Flagged for the spec's next revision.
    "DEPRECATED_BY": "plain",
    "DERIVED_FROM": "plain",
    "DISAPPEARED": "plain",
    "DOCUMENTS": "plain",
    "ESTABLISHED": "plain",
    "ESTABLISHED_IN": "plain",
    "GENERALIZES": "plain",
    # HAS_ALT_LABEL / HAS_PREF_LABEL / HAS_HIDDEN_LABEL: schema.py's DDL
    # carries no properties, even though two call sites (temporal_lobe.py,
    # quests.py) attempt `CREATE (c)-[:HAS_ALT_LABEL {created_at: ...}]->(l)`
    # — a column Kùzu's own schema does not declare. That call-site bug is
    # a separate, pre-existing latent defect (flagged in the B389 report,
    # not this card's to fix); the schema DDL is the source of truth for
    # what CAN be written, and it has no properties for these three.
    "HAS_ALT_LABEL": "plain",
    "HAS_HIDDEN_LABEL": "plain",
    "HAS_PREF_LABEL": "plain",
    "HYPOTHESIZED_IN": "plain",
    "IDENTIFIED_GAP_IN": "plain",
    "IN_WORKSPACE": "plain",
    "LEARNED": "plain",
    "NEXT_STEP": "plain",
    "PLANNED_IN": "plain",
    "PRODUCED_HYPOTHESIS": "plain",
    "PRODUCED_LESSON": "plain",
    "PRODUCED_PLAN_LESSON": "plain",
    "REIFIED_AS": "plain",
    "RELATED_TO": "plain",
    "ROUTES_TO": "plain",
    "SAME_COLOR_AS": "plain",
    "SENT_IN": "plain",
    "STEP_OF": "plain",
    "TARGETS": "plain",
    "TASK_OF": "plain",
    "TRANSITION_OF": "plain",
    # TRIGGERED / UPDATES_PATHWAY: spec §4.2b's illustrative occurrence-
    # family list names both, but schema.py's live DDL carries zero
    # properties for either ("FROM Message TO MergeEvent" /
    # "FROM MergeEvent TO Concept", no columns), and both call sites
    # (pathways.py:62, pathways.py:51) use `MERGE` (singleton), not
    # `CREATE`. Same schema-drift-since-spec situation as DEPRECATED_BY
    # above: "plain" is the definitionally safe answer for a property-free
    # table regardless of which family the spec's older snapshot assigned
    # it to. Flagged for the spec's next revision.
    "TRIGGERED": "plain",
    "UPDATES_PATHWAY": "plain",
    "USED": "plain",
    "WORKING_ON": "plain",

    # -- star (25): MERGE ... SET singleton-overwrite confirmed at the call
    #    site (file:line evidence) -------------------------------------
    # confidence/inferred_by/inferred_at family, spec §4.2a-named:
    "ENABLES": "star",       # queries/quests.py:714 MERGE, queries/sweep.py:1283 MERGE
    "REQUIRES": "star",      # queries/quests.py:702 MERGE, queries/sweep.py:1267 MERGE
    "REPLACES": "star",      # queries/quests.py:726 MERGE, queries/sweep.py:1299 MERGE
    # CONTRADICTS: schema.py's REL_TABLES has TWO colliding DDL statements
    # for this name (Concept->Concept confidence/inferred_by/inferred_at,
    # and a second, unreachable Concept->Hypothesis weight-only definition
    # under `IF NOT EXISTS` — Kùzu only ever creates the first). Classified
    # against the live, exercised path: queries/quests.py:738 MERGE,
    # queries/sweep.py:1315 MERGE. The second (Hypothesis) shape has zero
    # write call sites anywhere in the repo (grepped) — dead DDL. Flagged
    # as a schema.py bug (duplicate CREATE REL TABLE) in the B389 report,
    # not fixed here (out of scope).
    "CONTRADICTS": "star",
    "PART_OF": "star",       # queries/quests.py:750 MERGE, queries/sweep.py:1331 MERGE
    "TASK_BLOCKS": "star",   # queries/task_graph.py:262 MERGE ... SET (generic _RELS loop)
    "TASK_ENABLES": "star",  # queries/task_graph.py:262 MERGE ... SET (generic _RELS loop)
    # "the rest of the confidence/inferred_by/inferred_at family" (spec's
    # own phrase, same shape, same MERGE-only call sites):
    "ALTERNATIVE_TO": "star",  # queries/quests.py:798 MERGE, queries/sweep.py:1395 MERGE
    "CHOSEN_OVER": "star",     # queries/quests.py:762 MERGE, queries/sweep.py:1347 MERGE
    "EXTENDS": "star",         # queries/quests.py:786 MERGE, queries/sweep.py:1379 MERGE
    "IMPLEMENTS": "star",      # queries/quests.py:774 MERGE, queries/sweep.py:1363 MERGE
    # Not named by spec §4.2a but same evidence class (MERGE...SET, singleton
    # per (s,p,o) at every call site found):
    "APPLIED_PROCEDURE": "star",                  # queries/quests.py:456 MERGE
    "ARC_FAILURE_RECOVERED_BY": "star",           # queries/arc.py:923 MERGE
    "ARC_MECHANIC_CAUSES_EFFECT_PATTERN": "star", # queries/arc.py:856 MERGE
    "ARC_MECHANIC_FAILS_AS": "star",              # queries/arc.py:901 MERGE
    "ARC_MECHANIC_HAS_ACTION_PATTERN": "star",    # queries/arc.py:829 MERGE
    "ARC_MECHANIC_REQUIRES": "star",              # queries/arc.py:879 MERGE
    "DECISION_CHAIN": "star",       # queries/pathways.py:149 MERGE...ON CREATE/ON MATCH SET
    "DISTILLED_FROM": "star",       # queries/basal_ganglia.py:64,149,158,167 all MERGE
    "ENTITY_HYPOTHESIS": "star",    # queries/arc.py:342 MERGE
    "ENTITY_RULE": "star",          # queries/arc.py:497 MERGE
    "FOLLOWED_BY": "star",          # queries/capture.py:84 MERGE
    "GENERALIZES_LESSON": "star",   # queries/sweep.py:378 MERGE
    "MOVED_BY": "star",             # queries/arc.py:190 MERGE
    "SOLVED_BY": "star",            # schema.py upsert_agent_worker_and_link(): MERGE...ON CREATE/ON MATCH SET
    # Spec §4.2c-resolved (2026-09-05): named/shaped like "occurrence" family
    # in an earlier spec draft, but their sole confirmed write call site is a
    # MERGE + SET singleton overwrite (or MERGE...ON CREATE/ON MATCH SET
    # accumulator), the same shape as every other "star" table above. Per
    # §4.2c, class follows the observed write call site, never the name —
    # resolved architect decision, not a guess. Was in
    # UNCLASSIFIED_ESCALATED_TABLES prior to this resolution.
    "ANOMALY_DETECTED": "star",  # queries/orchestrator.py: MERGE (n)-[r:ANOMALY_DETECTED]->(gc) SET r.type=..., r.confidence=..., r.detected_at=...
    "CO_OCCURS_WITH": "star",    # queries/pathways.py 'unwind_co_occurs_with': MERGE (a)-[r:CO_OCCURS_WITH]->(b) ON CREATE SET r.count=1, r.strength=$strength ON MATCH SET r.count=r.count+1, r.strength=(r.strength+$strength)/2.0 — singleton carrying an accumulator, not an event history
    "OUTCOME_SIGNAL": "star",    # queries/quests.py 'link_plan_step_outcome_signal': MERGE (ps)-[o:OUTCOME_SIGNAL]->(c) SET o.valence=..., o.plan_id=..., o.observed_at=...

    # -- occurrence (15): bare CREATE (no MERGE, no existence check) at
    #    every write call site, so multiple edges already coexist today --
    "LOADED": "occurrence",     # queries/working_memory.py:116 CREATE — spec §4.2b named
    "WARM_NODE": "occurrence",  # queries/temporal_lobe.py:120 CREATE — spec §4.2b named
    "DISTINCT_FROM": "occurrence",     # queries/quests.py:630 CREATE, no dedup guard
    "REROUTED_FROM": "occurrence",     # queries/quests.py:384 CREATE, explicitly "audit edge"
    "DESCRIBED_BY_DATASET": "occurrence",  # queries/ingest.py:128 CREATE, fresh concept_id per call today but no DB-level guard against relinking an existing concept
    # FACT_* (10 tables): facts.py's ingest_facts() docstring is explicit —
    # "Re-ingesting at a different source_version supersedes the prior live
    # edge ... and creates a new live edge" — the OLD (now-superseded) edge
    # is NOT deleted, it is marked superseded and a NEW edge is created
    # alongside it. Multiple edges for the same (s,p,o) genuinely coexist
    # by design (supersession chain, capability.py's generic per-predicate
    # create_edge_<predicate> query, looped over all 10 FACT_PREDICATE_TABLES
    # entries). Classifying these "star" would silently discard the
    # superseded edge's properties (version, confidence, evidence_ref,
    # superseded_at) on the very next re-ingest — exactly the data-loss
    # trap this card exists to prevent.
    "FACT_APPROVED_BY": "occurrence",
    "FACT_CONSTRAINED_BY": "occurrence",
    "FACT_DEPLOYED_ON": "occurrence",
    "FACT_IMPLEMENTS": "occurrence",
    "FACT_INVOKES": "occurrence",
    "FACT_PRODUCED": "occurrence",
    "FACT_READS": "occurrence",
    "FACT_REQUIRES": "occurrence",
    "FACT_REUSES": "occurrence",
    "FACT_WRITES": "occurrence",
}


# ---------------------------------------------------------------------------
# Escalated: property-bearing rel tables this card could NOT confidently
# classify. Deliberately excluded from EDGE_REIFICATION so a write attempt
# raises (see `classify_edge()`) rather than silently defaulting. Per spec
# §4.2d, every remaining entry's reason is the same shape: no write call
# site exists anywhere in the repo (schema declared ahead of any
# implementation — a known pattern in this codebase; see e.g. the
# ANCHORED_TO comment in schema.py itself). There is no evidence to
# classify these from; whoever writes the first writer makes the call with
# that call site in front of them — a raise here is the correct outcome,
# not a defect. (The three tables previously escalated for a *conflicting*
# reason — spec text vs. observed MERGE+SET call sites — were resolved by
# spec §4.2c and moved into EDGE_REIFICATION as "star"; see that dict.)
# ---------------------------------------------------------------------------

UNCLASSIFIED_ESCALATED_TABLES: dict[str, str] = {
    # --- spec §4.2d: no write call site exists anywhere in the repo
    # (grepped campy/, web/, benchmarks/, tests/ for the literal table name
    # outside schema.py's own DDL) — schema declared ahead of any
    # implementation. Cannot determine star-vs-occurrence from callers that
    # don't exist yet, and per §4.2d this must NOT be guessed: classify only
    # when the first writer is implemented, with its call site in hand.
    "ADJACENT_TO": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "BLOCKS": "no write call site anywhere in the repo for the GridEntity->GridEntity BLOCKS table (distinct from TASK_BLOCKS, which IS classified above)",
    "CAUSES_CHANGE_IN": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "CONFIRMS": "no write call site anywhere in the repo (Concept->Hypothesis, B88 hypothesis engine; never wired to a writer)",
    "CONTAINS_ENTITY": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "CORRELATES_WITH": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "CO_MOVES_WITH": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "DERIVED_FROM_FACT": "only OPTIONAL MATCH reads found (queries/arc.py); no writer anywhere in the repo",
    "EXECUTED_AS": "no write call site anywhere in the repo (Plan->ChunkExecution, B66/B69 active planning; never wired to a writer)",
    "INFERRED_FROM": "only an OPTIONAL MATCH read found (queries/arc.py:328); no writer anywhere in the repo",
    "OBSERVED_IN": "no write call site anywhere in the repo, despite being spec-named occurrence-family (B168 ARC exploration graph, never wired to a writer)",
    "REQUIRES_ENTITY": "only MATCH reads found (queries/arc.py:240,251); no writer anywhere in the repo",
    "RESPONDS_TO": "no write call site anywhere in the repo (B168 ARC exploration graph, never wired to a writer)",
    "STRUCTURALLY_SIMILAR": "no write call site anywhere in the repo (schema-only; B168 ARC exploration graph, never wired to a writer)",
    "SUPPORTS_HYPOTHESIS": "no write call site anywhere in the repo (B88 hypothesis engine; never wired to a writer)",
}


def classify_edge(table: str) -> EdgeReification:
    """Look up `table`'s reification class. Raises `ValueError` — never a
    silent default — for any table missing from `EDGE_REIFICATION`,
    including every table in `UNCLASSIFIED_ESCALATED_TABLES` (whose reason
    is included in the error message)."""
    cls = EDGE_REIFICATION.get(table)
    if cls is not None:
        return cls
    reason = UNCLASSIFIED_ESCALATED_TABLES.get(table)
    if reason is not None:
        raise ValueError(
            f"rel table {table!r} is deliberately unclassified in EDGE_REIFICATION "
            f"(escalated, not guessed): {reason}. Resolve this in "
            f"docs/rdf-schema-mapping.md and oxigraph_client.py before writing it."
        )
    raise ValueError(
        f"rel table {table!r} has no EDGE_REIFICATION entry and is not in "
        f"UNCLASSIFIED_ESCALATED_TABLES either — this is a table schema.py "
        f"gained after B389 shipped. Classify it (plain/star/occurrence) "
        f"per docs/rdf-schema-mapping.md §4.2 before writing it; never guess."
    )


# ---------------------------------------------------------------------------
# §3.1 — datatype mapping (normative table). Every numeric literal carries
# an explicit XSD datatype tag — never a bare Turtle number (§3.2: bare
# `0.8` parses as xsd:decimal, not xsd:double). This module never emits
# Turtle text for a literal; every literal is built through `ox.Literal(...,
# datatype=...)` and serialized via `str()`, which always includes the
# datatype IRI explicitly (confirmed empirically: `str(Literal("0.8",
# datatype=NamedNode(XSD+"double")))` prints `"0.8"^^<...#double>`).
# ---------------------------------------------------------------------------


def _format_datetime(value: Any) -> str:
    """ISO-8601, UTC, always with an explicit offset (§3.1's TIMESTAMP row)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def literal_for(kuzu_type: str, value: Any) -> ox.Literal | list[ox.Literal]:
    """Map one Kùzu-typed value to its RDF literal term(s), per spec §3.1.

    Returns a `list[Literal]` for `STRING[]` (§3.3 — repeated triples,
    unordered); a single `Literal` for every other type. Caller must have
    already skipped `None` (§3.4) and must never call this for `FLOAT[384]`
    (§5 — raises here as a defensive backstop, but `write_node()` skips it
    before ever reaching this function).

    **Deviation from spec §3.1's literal table, empirically forced (B389):**
    the spec's table maps `INT32 -> xsd:int` and `INT64 -> xsd:long`. Real
    pyoxigraph 0.5.11 does not preserve either tag: writing a `Literal` with
    an explicit `xsd:int`, `xsd:long`, `xsd:short`, `xsd:byte`, or any other
    XSD-integer-derived datatype and reading it back — even via the
    non-SPARQL `Store.quads_for_pattern()`/raw `list(store)` iteration, so
    this is a storage-layer behavior, not a SPARQL-results quirk —
    canonicalizes it to `xsd:integer` every time. Only `xsd:decimal` (a
    sibling of `xsd:integer` in the XSD hierarchy, not a subtype) and the
    floating types (`xsd:double`, `xsd:float`) are preserved exactly as
    written. Writing `xsd:int`/`xsd:long` here would therefore be a false
    promise — the very "silent type mismatch" this migration exists to
    prevent, just introduced by this module instead of by careless Turtle
    authoring. Both `INT32` and `INT64` are written as `xsd:integer`
    instead, matching what pyoxigraph actually persists. Flagged for the
    spec's next revision; see the B389 report for the full probe transcript.
    """
    if kuzu_type == "STRING":
        return ox.Literal(str(value))
    if kuzu_type == "STRING[]":
        return [ox.Literal(str(item)) for item in value]
    if kuzu_type in ("INT32", "INT64"):
        return ox.Literal(str(int(value)), datatype=ox.NamedNode(_XSD_INTEGER))
    if kuzu_type == "DOUBLE":
        return ox.Literal(repr(float(value)), datatype=ox.NamedNode(_XSD_DOUBLE))
    if kuzu_type == "FLOAT":
        return ox.Literal(repr(float(value)), datatype=ox.NamedNode(_XSD_FLOAT))
    if kuzu_type in ("BOOL", "BOOLEAN"):
        return ox.Literal("true" if value else "false", datatype=ox.NamedNode(_XSD_BOOLEAN))
    if kuzu_type == "TIMESTAMP":
        return ox.Literal(_format_datetime(value), datatype=ox.NamedNode(_XSD_DATETIME))
    if kuzu_type == "FLOAT[384]":
        raise ValueError(
            "FLOAT[384] embeddings are never written to RDF (spec §5) — "
            "use campy.brain.hippocampus.graph.vector_store.VectorStore instead"
        )
    raise ValueError(f"unsupported Kùzu type for RDF serialization: {kuzu_type!r}")


# ---------------------------------------------------------------------------
# §4.1/§4.2 — rel schema introspection (property types for star/occurrence
# annotations), parsed the same way as NODE_COLUMNS above. Kùzu's
# `IF NOT EXISTS` means only the FIRST `CREATE REL TABLE` for a given name
# is ever live (CONTRADICTS has a second, dead, colliding definition — see
# the EDGE_REIFICATION comment above) — this parser keeps the first
# definition it sees per name, matching that real Kùzu behavior exactly.
# ---------------------------------------------------------------------------

_REL_HEADER_RE = re.compile(
    r"CREATE REL TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*)\)\s*$", re.S
)


def _parse_rel_schema() -> dict[str, dict[str, str]]:
    props: dict[str, dict[str, str]] = {}
    for ddl in REL_TABLES:
        match = _REL_HEADER_RE.match(ddl)
        if not match:
            continue
        name, body = match.group(1), match.group(2)
        if name in props:
            continue  # first CREATE wins, matches Kùzu's IF NOT EXISTS
        cols: dict[str, str] = {}
        for part in body.split(","):
            part = part.strip()
            if not part or part.startswith("FROM "):
                continue
            col_match = _COLUMN_LINE_RE.match(part)
            if col_match:
                cols[col_match.group(1)] = col_match.group(2)
        props[name] = cols
    return props


REL_COLUMNS: dict[str, dict[str, str]] = _parse_rel_schema()


# ---------------------------------------------------------------------------
# §4.2e — RDF-star annotation delete cascade (B403)
#
# Cypher's `DETACH DELETE n` removes a node and every edge incident to it in
# one step. Its SPARQL translation (see `provenance.drop_projected_*`)
# removes the node's property triples and its plain incoming/outgoing edge
# triples — but an RDF-star ANNOTATION is not a triple about the node, it is
# a triple about a *reifier* that points at the edge triple, so no pattern
# over `?n` reaches it. Without the cascade below those annotations, and the
# occurrence nodes hanging off them, survive their edge forever.
#
# Cascade semantics per `EDGE_REIFICATION` class:
#
#   plain       nothing to cascade — a `plain` edge is one triple, already
#               removed by the `?s ?p2 ?n` / `?n ?p ?o` patterns.
#   star        one reifier per (s,p,o) (`write_edge` enforces this via
#               `_remove_existing_reifiers`). Remove the reifier's
#               `rdf:reifies` quad AND every annotation property quad on it.
#   occurrence  N reifiers per (s,p,o), each carrying
#               `campy:occurrence <cid:Occurrence/{ulid}>`. Remove each
#               reifier as above AND the occurrence node's own property
#               triples. The occurrence URI is minted fresh per write
#               (`mint_occurrence_uri()`), is never reused, and is referenced
#               only from its one reifier — so once the reifier goes, the
#               occurrence node is unreachable garbage, not shared state.
#               Leaving it behind is the larger half of the leak: an
#               occurrence edge accumulates a node per write.
#
# WHY AN ORPHAN SWEEP RATHER THAN A PER-QUERY TARGETED DELETE:
#
# The sweep's soundness rests on one invariant the spec states and
# `write_edge()` enforces (§4.2a: "Always assert the plain triple as well as
# the quoted annotation"): **every annotation this system writes has its base
# triple asserted**. So `?r rdf:reifies <<( ?s ?p ?o )>>` with
# `FILTER NOT EXISTS { ?s ?p ?o }` matches orphans and nothing else. That
# makes one static statement correct for all 29 `drop_projected_*` queries —
# no per-query node selector to duplicate, mis-copy, or drift — and it also
# collects annotations orphaned by any *other* delete path, including query
# batches B392-B396 have not translated yet.
#
# Measured cost (real pyoxigraph 0.5.11, 20 000 star annotations / 120 000
# quads): ~22 ms, flat whether it finds 0 orphans or 100. It is O(reifiers)
# with a point lookup per reifier, and it runs on projection refresh, not in
# any read path.
#
# ORDERING IS LOAD-BEARING: the cascade must run AFTER the statement that
# deletes the node, because "orphaned" is defined by the base triple already
# being gone. `with_annotation_cascade()` appends, never prepends.
#
# pyoxigraph 0.5.11 notes (empirically verified, extending the module
# docstring's points 1-5):
#
#   6. A triple term in OBJECT position IS matchable from SPARQL text using
#      the RDF 1.2 `<<( ?s ?p ?o )>>` syntax, with variables in all three
#      positions, in both `query()` and `update()` — this is what makes a
#      SPARQL-text cascade possible at all despite docstring point 3
#      (quoted triple as a DELETE quad SUBJECT is still rejected; we never
#      need one, because the reifier is an ordinary blank node subject).
#      The legacy `<< ?s ?p ?o >>` spelling parses in a WHERE clause but
#      matches nothing — it desugars to annotation syntax, not a term
#      pattern. Use `<<( ... )>>`.
#   7. `Store.update()` accepts several `;`-separated statements in one
#      request and applies them in order, with a single leading `PREFIX`
#      prologue applying to all of them.
# ---------------------------------------------------------------------------

ANNOTATION_CASCADE_SPARQL = """
DELETE {
    ?cascade_reifier ?cascade_reifier_p ?cascade_reifier_o .
    ?cascade_occurrence ?cascade_occurrence_p ?cascade_occurrence_o .
}
WHERE {
    ?cascade_reifier <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies>
        <<( ?cascade_s ?cascade_p ?cascade_o )>> .
    FILTER NOT EXISTS { ?cascade_s ?cascade_p ?cascade_o }
    ?cascade_reifier ?cascade_reifier_p ?cascade_reifier_o .
    OPTIONAL {
        ?cascade_reifier <https://campy.dev/ns#occurrence> ?cascade_occurrence .
        ?cascade_occurrence ?cascade_occurrence_p ?cascade_occurrence_o .
    }
}
"""
"""One complete SPARQL Update statement that deletes every orphaned RDF-star
annotation and the occurrence nodes hanging off it.

Deliberately written with absolute IRIs, not `campy:`/`rdf:` prefixed names,
so it is self-contained: it stays valid appended to a `NamedQuery.sparql`
string whether or not that string's own prologue is present (the 198
provenance strings currently carry no `PREFIX` line — B397's executor
supplies it). Do not "tidy" these into prefixed names.
"""

_CASCADE_MARKER = "?cascade_reifier"


def with_annotation_cascade(sparql: str) -> str:
    """Append `ANNOTATION_CASCADE_SPARQL` to a node-deleting SPARQL Update.

    This is the single definition of the cascade for every `DETACH DELETE`
    translation — call it instead of pasting the pattern into another query
    (`provenance.py` has 29 such queries). The result is one Update request of
    two `;`-separated statements: the caller's node/edge delete first, then the
    cascade, which is what makes the "orphaned" test meaningful (see the
    section comment above on ordering).

    Raises `ValueError` if `sparql` already carries the cascade — applying it
    twice is a copy/paste mistake, never intentional.
    """
    if not isinstance(sparql, str) or not sparql.strip():
        raise ValueError("with_annotation_cascade() needs a non-empty SPARQL Update string")
    if _CASCADE_MARKER in sparql:
        raise ValueError(
            "with_annotation_cascade() applied to a string that already contains "
            "the cascade — apply it exactly once, at the NamedQuery definition."
        )
    return sparql.rstrip() + "\n            ;\n" + ANNOTATION_CASCADE_SPARQL


# ---------------------------------------------------------------------------
# Node / edge writers
# ---------------------------------------------------------------------------


def _iri_text(uri: str) -> str:
    """`<uri>` term text, via pyoxigraph's own NamedNode serializer (so any
    character requiring escaping is handled the same way pyoxigraph itself
    would need it, not by ad hoc string formatting)."""
    return str(ox.NamedNode(uri))


def _node_property_lines(uri: str, table: str, properties: dict[str, Any]) -> list[str]:
    cols = NODE_COLUMNS.get(table)
    if cols is None:
        raise ValueError(f"unknown node table {table!r} — not in schema.NODE_TABLES")
    subj = _iri_text(uri)
    lines: list[str] = []
    for key, value in properties.items():
        if key not in cols:
            raise ValueError(
                f"{table}.{key} is not a declared column in schema.NODE_TABLES[{table!r}]"
            )
        kuzu_type = cols[key]
        if value is None:
            continue  # §3.4 — NULL emits no triple, never a sentinel
        if kuzu_type == "FLOAT[384]":
            continue  # §5 — vectors never go to RDF
        pred = f"<{CAMPY_NS}{key}>"
        literal = literal_for(kuzu_type, value)
        if isinstance(literal, list):
            for lit in literal:
                lines.append(f"{subj} {pred} {str(lit)} .")
        else:
            lines.append(f"{subj} {pred} {str(literal)} .")
    return lines


def _edge_property_lines(quoted_prefix: str, table: str, properties: dict[str, Any]) -> list[str]:
    """Build ` << s p o >> pred val ; pred2 val2 .` annotation lines from a
    property dict, using the rel table's own column types (REL_COLUMNS)."""
    cols = REL_COLUMNS.get(table, {})
    parts: list[str] = []
    for key, value in (properties or {}).items():
        if key not in cols:
            raise ValueError(
                f"{table}.{key} is not a declared column in schema.REL_TABLES[{table!r}]"
            )
        if value is None:
            continue  # §3.4
        kuzu_type = cols[key]
        pred = f"<{CAMPY_NS}{key}>"
        literal = literal_for(kuzu_type, value)
        if isinstance(literal, list):
            for lit in literal:
                parts.append(f"{pred} {str(lit)}")
        else:
            parts.append(f"{pred} {str(literal)}")
    if not parts:
        return []
    return [f"{quoted_prefix} " + " ; ".join(parts) + " ."]


class OxigraphClient:
    """RDF-star client mirroring `KuzuClient`'s async surface
    (`execute_read`, `execute_write`) plus this card's node/edge writers.

    Both engines coexist (see module docstring) — this class is not wired
    into `GraphGateway` (B397's job); `execute_read`/`execute_write` exist
    so that future wiring doesn't require call sites to change, per the
    card's requirement.
    """

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        self.read_only = read_only
        self.db_path = str(db_path) if db_path is not None else None
        if db_path is None or str(db_path) == ":memory:":
            self.store = ox.Store()
        else:
            Path(db_path).mkdir(parents=True, exist_ok=True, mode=0o700)
            self.store = ox.Store(str(db_path))
        self._lock = asyncio.Lock()

    # -- node writes ------------------------------------------------------

    def write_node(self, table: str, properties: dict[str, Any]) -> str:
        """Assert `a campy:{table}` plus one triple per non-NULL property
        (§3), returning the minted instance URI. Synchronous — see
        `execute_write` for the async/lock-guarded wrapper other callers
        should use once B397 wires this client into the gateway."""
        pk_col = NODE_PRIMARY_KEYS.get(table)
        if pk_col is None:
            raise ValueError(f"unknown node table {table!r} — not in schema.NODE_TABLES")
        if properties.get(pk_col) is None:
            raise ValueError(f"{table} write is missing its primary key column {pk_col!r}")
        uri = mint_uri(table, properties[pk_col])
        subj = _iri_text(uri)
        lines = [f"{subj} a <{CAMPY_NS}{table}> ."]
        lines.extend(_node_property_lines(uri, table, properties))
        self.store.update("INSERT DATA {\n" + "\n".join(lines) + "\n}")
        return uri

    # -- edge writes --------------------------------------------------------

    def write_edge(
        self,
        table: str,
        subject_uri: str,
        object_uri: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Write one `table`-typed edge from `subject_uri` to `object_uri`,
        dispatching on `classify_edge(table)`. Raises for any table not in
        `EDGE_REIFICATION` (see `classify_edge`) — never a silent default.
        """
        reification = classify_edge(table)
        pred = f"<{CAMPY_NS}{table}>"
        subj, obj = _iri_text(subject_uri), _iri_text(object_uri)
        plain_triple = f"{subj} {pred} {obj} ."
        quoted_prefix = f"<< {subj} {pred} {obj} >>"

        if reification == "plain":
            if properties:
                raise ValueError(
                    f"{table} is classified 'plain' (no properties) but properties "
                    f"were passed: {sorted(properties)}"
                )
            self.store.update("INSERT DATA {\n" + plain_triple + "\n}")
            return

        if reification == "star":
            self._remove_existing_reifiers(subject_uri, table, object_uri)
            lines = [plain_triple]
            lines.extend(_edge_property_lines(quoted_prefix, table, properties or {}))
            self.store.update("INSERT DATA {\n" + "\n".join(lines) + "\n}")
            return

        if reification == "occurrence":
            occ_uri = mint_occurrence_uri()
            occ_subj = _iri_text(occ_uri)
            lines = [
                plain_triple,
                f"{quoted_prefix} <{CAMPY_NS}occurrence> {occ_subj} .",
            ]
            # Occurrence nodes are not a NODE_TABLES entry (they're new
            # identity per spec §4.2b, not derived from any Kùzu node
            # table). Their properties are typed by the OWNING rel table's
            # own column declarations instead (spec §4.2b's example reuses
            # the edge's own property names — token_estimate, source, etc.
            # — as the occurrence node's properties).
            cols = REL_COLUMNS.get(table, {})
            for key, value in (properties or {}).items():
                if value is None:
                    continue
                if key not in cols:
                    raise ValueError(
                        f"{table}.{key} is not a declared column in schema.REL_TABLES[{table!r}]"
                    )
                literal = literal_for(cols[key], value)
                pred_iri = f"<{CAMPY_NS}{key}>"
                if isinstance(literal, list):
                    for lit in literal:
                        lines.append(f"{occ_subj} {pred_iri} {str(lit)} .")
                else:
                    lines.append(f"{occ_subj} {pred_iri} {str(literal)} .")
            self.store.update("INSERT DATA {\n" + "\n".join(lines) + "\n}")
            return

        raise AssertionError(f"unreachable reification value: {reification!r}")  # pragma: no cover

    def _remove_existing_reifiers(self, subject_uri: str, table: str, object_uri: str) -> None:
        """`star`'s upsert step (module docstring point 4): find every
        blank-node reifier currently pointing (via `rdf:reifies`) at this
        exact (s,p,o) triple, and remove each one's quads entirely, via the
        native `Store.quads_for_pattern()`/`Store.remove()` API — NOT SPARQL
        DELETE, which this pyoxigraph build rejects for a quoted-triple
        pattern (see module docstring points 1 and 3)."""
        s = ox.NamedNode(subject_uri)
        p = ox.NamedNode(f"{CAMPY_NS}{table}")
        o = ox.NamedNode(object_uri)
        base_triple = ox.Triple(s, p, o)  # OK as an OBJECT term (point 1)
        reifiers = [
            quad.subject
            for quad in self.store.quads_for_pattern(None, RDF_REIFIES, base_triple, ox.DefaultGraph())
        ]
        for reifier in reifiers:
            for quad in list(self.store.quads_for_pattern(reifier, None, None, ox.DefaultGraph())):
                self.store.remove(quad)

    # -- annotation cascade (§4.2e) -----------------------------------------

    def cascade_orphaned_annotations(self) -> int:
        """Run `ANNOTATION_CASCADE_SPARQL` against this store and return the
        number of quads it removed.

        The `drop_projected_*` queries carry the cascade in their own SPARQL
        text (via `with_annotation_cascade()`), so this method is not on that
        path. It exists for delete paths that do not go through a
        `NamedQuery` — ad-hoc repair, an importer that removed edges
        directly, or a maintenance sweep after a query batch that has not been
        translated yet. Safe to run at any time: with no orphans present it is
        a no-op (measured ~22 ms against a 120 000-quad store).
        """
        before = len(self.store)
        self.store.update(ANNOTATION_CASCADE_SPARQL)
        return before - len(self.store)

    # -- generic read/write, mirroring KuzuClient's async surface -----------

    def execute(self, sparql: str, params: dict[str, Any] | None = None):
        """Synchronous SPARQL execution. `params`, if given, are bound via
        pyoxigraph's native `substitutions=` (RDF-dev SEP-0007) for SELECT/
        ASK/CONSTRUCT queries — never string-interpolated (spec §7.2). SPARQL
        Update text (`INSERT DATA`/`DELETE DATA`/...) has no substitutions
        mechanism in this pyoxigraph version; use `write_node`/`write_edge`
        for parameterized writes, which build their ground terms through
        `ox.Literal`/`ox.NamedNode`'s own escaping, never via raw string
        interpolation of a caller-supplied value into SPARQL text.

        **Empirically discovered pyoxigraph 0.5.11 constraint (B389):** a
        substituted variable must also appear in the query's SELECT
        projection — `substitutions={Variable("s"): ...}` against
        `SELECT ?name WHERE { ?s campy:name ?name }` (where `?s` is bound
        only in the WHERE clause, not projected) raises `RuntimeError: The
        SPARQL query does not contains variable ?s in its SELECT
        projection`. Callers binding a param that is not itself part of the
        desired result columns must still project it (e.g. `SELECT ?s
        ?name WHERE {...}`) for the substitution to be accepted.
        """
        stripped = sparql.lstrip().upper()
        if stripped.startswith(("INSERT", "DELETE", "WITH", "CLEAR", "DROP", "CREATE", "LOAD", "MOVE", "COPY", "ADD")):
            if params:
                raise ValueError(
                    "OxigraphClient.execute(): SPARQL Update text does not support "
                    "parameter substitution in this pyoxigraph version — build ground "
                    "terms via write_node()/write_edge() instead of passing params here"
                )
            self.store.update(sparql)
            return None
        substitutions = None
        if params:
            substitutions = {ox.Variable(name): _term_for_param(value) for name, value in params.items()}
        return self.store.query(sparql, substitutions=substitutions)

    async def execute_write(self, sparql: str, params: dict[str, Any] | None = None):
        async with self._lock:
            return await asyncio.to_thread(self.execute, sparql, params)

    def _execute_and_collect(self, sparql: str, params: dict[str, Any] | None = None):
        """Run `execute()` and fully materialize its result into plain
        Python data, in the SAME thread the query ran in.

        This is not a style choice: pyoxigraph's `QuerySolutions` (SELECT)
        and `QueryTriples` (CONSTRUCT/DESCRIBE) result iterators are PyO3
        `unsendable` types, bound to the OS thread that created them.
        Returning the raw iterator out of an `asyncio.to_thread()` worker
        and iterating it from the event-loop thread does not raise a
        catchable Python exception — it panics the underlying Rust
        extension and hard-aborts the whole process (confirmed empirically:
        `thread '<unnamed>' panicked ... PyQuerySolutions is unsendable,
        but sent to another thread`, `Fatal Python error: Aborted`). So the
        query AND its full consumption into plain dict/bool/Triple values
        must happen inside the same `to_thread()` call — see
        `execute_read()` below, which does no iteration itself, only calls
        this method via `to_thread`.
        """
        result = self.execute(sparql, params)
        if result is None:
            return []
        if isinstance(result, ox.QueryBoolean):
            return bool(result)
        if isinstance(result, ox.QuerySolutions):
            # `.variables` lives on the QuerySolutions iterator itself, not
            # on each QuerySolution row (a QuerySolution supports only
            # __getitem__/__iter__/__len__ over its bound terms). Keys are
            # the bare variable name (`var.value`, e.g. "o"), matching
            # KuzuClient's column-name convention — not `str(var)`, which
            # would render the SPARQL-syntax form ("?o").
            variables = result.variables
            return [
                {var.value: solution[var] for var in variables}
                for solution in result
            ]
        # CONSTRUCT/DESCRIBE -> QueryTriples of Triple terms
        return list(result)

    async def execute_read(self, sparql: str, params: dict[str, Any] | None = None):
        return await asyncio.to_thread(self._execute_and_collect, sparql, params)

    def close(self) -> None:
        del self.store


def _term_for_param(value: Any) -> ox.NamedNode | ox.Literal:
    """Infer an RDF term for a `SELECT`-query substitution from a plain
    Python value (no per-query schema to consult, unlike node/edge writes —
    see `execute()`'s docstring). A string already shaped like one of this
    module's own IRIs is bound as a `NamedNode`; everything else is a typed
    `Literal` via the same §3.1 rules `literal_for()` uses for known Kùzu
    scalar types (arrays are not valid query substitutions, so `STRING[]` is
    not handled here)."""
    if isinstance(value, ox.NamedNode | ox.BlankNode | ox.Literal):
        return value
    if isinstance(value, str) and (value.startswith(CID_BASE) or value.startswith(CAMPY_NS)):
        return ox.NamedNode(value)
    if isinstance(value, bool):
        return ox.Literal("true" if value else "false", datatype=ox.NamedNode(_XSD_BOOLEAN))
    if isinstance(value, int):
        return ox.Literal(str(value), datatype=ox.NamedNode(_XSD_INTEGER))
    if isinstance(value, float):
        return ox.Literal(repr(value), datatype=ox.NamedNode(_XSD_DOUBLE))
    if isinstance(value, datetime):
        return ox.Literal(_format_datetime(value), datatype=ox.NamedNode(_XSD_DATETIME))
    return ox.Literal(str(value))


__all__ = [
    "OxigraphClient",
    "ANNOTATION_CASCADE_SPARQL",
    "with_annotation_cascade",
    "EDGE_REIFICATION",
    "UNCLASSIFIED_ESCALATED_TABLES",
    "classify_edge",
    "literal_for",
    "generate_ulid",
    "mint_occurrence_uri",
    "mint_uri",
    "CAMPY_NS",
    "CID_BASE",
    "XSD",
    "NODE_COLUMNS",
    "NODE_PRIMARY_KEYS",
    "REL_COLUMNS",
]
