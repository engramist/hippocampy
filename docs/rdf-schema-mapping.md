# RDF Schema Mapping Specification (B388)

**Status:** Normative. This document is the single source of truth for how Campy's
Kùzu labeled-property graph (LPG) maps onto Oxigraph RDF/RDF-star during the B384
storage re-platforming.

**Why this document exists:** Every SPARQL translation sub-batch (B391–B396) and
`oxigraph_client.py` (B389) depend on these decisions. They are one-way doors —
once data is written under a URI scheme and a reification strategy, changing them
means a full re-migration. No agent may invent a mapping not specified here. If a
case is genuinely not covered, stop and escalate rather than improvising.

**Empirically validated** against `pyoxigraph 0.5.11` — every pattern below was
executed before being specified. See §9 for the validation harness.

---

## 1. Scope of the mapping

Measured against `campy/brain/hippocampus/schema.py` at `d3ef540`:

| Surface | Count |
|---|---|
| Node tables | 57 |
| Node properties (total) | 878 |
| Relationship tables | 102 |
| Relationship tables carrying properties | **51** |
| Named queries to translate (`graph/queries/`) | 863 |
| Distinct Kùzu datatypes | 10 |

> B384's card text claims RDF-star is needed for "4 core relationship types."
> The measured number is **51**. Size all reification work against 51.

---

## 2. Namespaces and URI minting

```
@prefix campy: <https://campy.dev/ns#>     # predicates, classes
@prefix cid:   <https://campy.dev/id/>     # instances
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#>
```

**Instance URIs are deterministic and derived from the existing Kùzu primary key:**

```
cid:{TableName}/{primary_key_value}
```

Examples: `cid:Concept/c_01H8XK`, `cid:Decision/d_4471`, `cid:Session/s_88ab`.

Rules:

- The primary key value is percent-encoded per RFC 3986 for any character outside
  `unreserved`. Existing keys are ULID/slug-shaped, so encoding is usually a no-op,
  but the encoder must be applied unconditionally — never assume.
- **URI minting is a pure function of `(table, primary_key)`.** Never mint from a
  mutable property (name, title, content hash). Renaming a Concept must not change
  its URI.
- The table name is part of the URI. Two rows with the same PK in different tables
  are different resources.

**Class assertion:** every node carries `a campy:{TableName}`.

---

## 3. Node properties → triples

One predicate per property, predicate name identical to the Kùzu column name:

```turtle
cid:Concept/c_01H8XK
    a                    campy:Concept ;
    campy:concept_id     "c_01H8XK" ;
    campy:name           "GraphGateway" ;
    campy:pathway_strength "0.73"^^xsd:double ;
    campy:archived       false ;
    campy:created_at     "2026-09-04T10:00:00"^^xsd:dateTime .
```

### 3.1 Datatype mapping — normative table

| Kùzu type | RDF term | Notes |
|---|---|---|
| `STRING` | plain literal (`xsd:string`) | |
| `INT32` | `"n"^^xsd:int` | |
| `INT64` | `"n"^^xsd:long` | |
| `DOUBLE` | `"n"^^xsd:double` | **must** be explicit — see §3.2 |
| `FLOAT` | `"n"^^xsd:float` | |
| `BOOL` / `BOOLEAN` | `true` / `false` (`xsd:boolean`) | both spellings exist in schema; both map here |
| `TIMESTAMP` | `"…"^^xsd:dateTime` | ISO-8601, UTC, always with `Z` or explicit offset |
| `STRING[]` | repeated triples, same predicate | **unordered** — see §3.3 |
| `FLOAT[384]` | **not stored in RDF** | goes to sqlite-vec — see §5 |

### 3.2 Datatype fidelity trap (validated)

Turtle's bare numeric literal `0.8` parses as **`xsd:decimal`**, not `xsd:double`.
A SPARQL `FILTER(?score > "0.5"^^xsd:double)` against an `xsd:decimal` literal
will not behave as the Cypher original did.

**Rule: every numeric literal written by `oxigraph_client.py` must carry an
explicit datatype tag.** Never emit a bare number. This is a serialization-layer
invariant and must have a unit test.

### 3.3 `STRING[]` is unordered

Kùzu `STRING[]` is an ordered list. Repeated triples are an unordered set.

Audit of current usage shows these columns are tag-like (labels, aliases, tags)
where order is not semantically load-bearing, so repeated triples are correct and
far cheaper to query than `rdf:List`.

**Constraint:** if any future column needs *ordered* array semantics, it must not
use `STRING[]` — escalate for an `rdf:List` or index-predicate design. A migration
test asserts round-trip set-equality, not list-equality, for these columns.

### 3.4 NULL vs. absent — the highest-risk trap in this migration

Kùzu stores an explicit `NULL`. **RDF has no null: absence is the only encoding.**

A property that is `NULL` in Kùzu produces **no triple at all**. Therefore:

```cypher
-- Cypher: matches rows where archived is FALSE. Does NOT match NULL.
WHERE n.archived = false
```

```sparql
# WRONG — silently drops every node where the property was never set
?n campy:archived false .

# CORRECT — reproduces "false or unset"
OPTIONAL { ?n campy:archived ?archived }
FILTER(!BOUND(?archived) || ?archived = false)
```

This affects `archived`, `superseded_by`, and every optional filter — including the
`archived`/`superseded_by` filters B374 added and B386 folded into the named-query
registry. **Every translated query with a filter on a nullable column must use the
`!BOUND(...) ||` form.** Translation batches must treat a bare equality filter on a
nullable column as a defect.

Writers must **not** emit a triple for a NULL value. Writing `campy:archived ""`
or a sentinel is forbidden.

---

## 4. Relationships

### 4.1 Property-free relationships (51 of 102) — plain triples

```turtle
cid:Plan/p1 campy:ENABLES cid:ActionItem/a1 .
```

Predicate name is the Kùzu rel-table name verbatim, in `campy:`.

### 4.2 Property-bearing relationships (51 of 102)

Two sub-cases. **Choosing the wrong one silently loses data.**

#### 4.2a Singleton edges → RDF-star quoted triple

An edge that can exist **at most once** per `(subject, predicate, object)` and
carries descriptive properties:

```turtle
cid:Plan/p1 campy:ENABLES cid:ActionItem/a1 .
<< cid:Plan/p1 campy:ENABLES cid:ActionItem/a1 >>
    campy:confidence  "0.8"^^xsd:double ;
    campy:inferred_by "step3b" ;
    campy:inferred_at "2026-09-04T10:00:00Z"^^xsd:dateTime .
```

Applies to: `ENABLES`, `REQUIRES`, `REPLACES`, `CONTRADICTS`, `PART_OF`,
`DEPRECATED_BY`, `TASK_BLOCKS`, `TASK_ENABLES`, and the rest of the
`confidence`/`inferred_by`/`inferred_at` family.

**Always assert the plain triple as well as the quoted annotation.** A quoted
triple alone is not asserted in the default graph, and `?s campy:ENABLES ?o` would
return nothing. Validated: writing both keeps plain traversal working.

#### 4.2b Repeating / event edges → occurrence nodes hanging off the quoted triple

An edge that can legitimately occur **many times** for the same `(s, p, o)` — the
same Session loading the same Decision across sub-turns.

**B384's proposed ":event_id discriminator inside the quoted triple" does not
work.** A quoted triple's identity *is* its three terms; adding a discriminator
term changes the triple, and then the plain traversal `?s campy:LOADED ?o` no
longer matches. Under RDF set semantics a second `LOADED` write would otherwise
overwrite the first edge's properties.

**Specified pattern (validated):**

```turtle
cid:Session/s1 campy:LOADED cid:Decision/d1 .
<< cid:Session/s1 campy:LOADED cid:Decision/d1 >> campy:occurrence
    cid:Occurrence/01J8XK0000 ,
    cid:Occurrence/01J8XK0001 .

cid:Occurrence/01J8XK0000
    campy:injected_at    "2026-09-04T10:00:00Z"^^xsd:dateTime ;
    campy:token_estimate "120"^^xsd:long ;
    campy:source         "bundle_compiler" ;
    campy:load_hits      "1"^^xsd:long .
```

Both survive: `?s campy:LOADED ?o` traverses, and every occurrence is retained.

```sparql
SELECT ?tok WHERE {
  << ?s campy:LOADED ?o >> campy:occurrence/campy:token_estimate ?tok
}
```

Occurrence URIs are **ULID-minted**, not derived — they are new identity, not a
mapping of an existing key. Use `cid:Occurrence/{ulid}`. ULIDs sort
lexicographically by time, so `ORDER BY ?occ` gives chronological order without a
separate index.

**Event edges (use 4.2b):** `LOADED`, `WARM_NODE`, `ANOMALY_DETECTED`,
`OUTCOME_SIGNAL`, `CO_OCCURS_WITH`, `UPDATES_PATHWAY`, `TRIGGERED`, `OBSERVED_IN`.

**Classification is per-table and must be recorded** in a single
`EDGE_REIFICATION: dict[str, Literal["plain","star","occurrence"]]` table in
`oxigraph_client.py`, covering all 102 rel tables exhaustively. A missing entry is
a hard error at write time, never a silent default. Any table not listed above must
be classified explicitly before its queries are translated; if the correct class is
unclear from the schema and call sites, escalate — do not guess.

---

## 5. Vectors leave the graph

`FLOAT[384]` columns (fastembed embeddings) are **not** written to Oxigraph. They
move to `sqlite-vec` at `~/.campy/vectors.db`, keyed by the node's **full instance
URI string** (`https://campy.dev/id/Concept/c_01H8XK`) so the two stores join
without a translation table.

This means vector search is **not a SPARQL string** and has no `sparql=` field on
its `NamedQuery`. It is a Python handler, exactly as the B386 `NamedQuery`
docstring already anticipates:

1. sqlite-vec ANN → top-k URIs + distances
2. Oxigraph `VALUES ?s { <uri1> <uri2> … }` hydration for node properties
3. join in Python, preserving ANN rank order

Kùzu's `QUERY_VECTOR_INDEX` and `QUERY_FTS_INDEX` call sites both take this shape.
**Full-text search** has no Oxigraph equivalent either — it becomes a SQLite FTS5
table alongside the vectors in the same `vectors.db`, same URI keying.

---

## 6. Graph partitioning: default graph only

Campy already isolates tenants **physically**, one store per workspace directory
(B316 `WorkspaceRouter`, B385 EFS sharding). That is the security boundary and it
is stronger than named graphs.

**Decision: write everything to the default graph. Do not use named graphs.**

Rationale: named graphs would add a quad dimension to all 863 queries for zero
isolation benefit over the existing per-workspace store, and `GRAPH ?g { }`
wrappers are a common source of silently-empty results. Revisit only if a single
store must ever hold multiple tenants — which B316's design explicitly rejects.

---

## 7. Query translation rules

Applies to all six SPARQL sub-batches.

1. **`NamedQuery.name`, `params`, and `mutating` do not change.** Only a `sparql=`
   string is added, or the query is reclassified as a Python handler (§5). Call
   sites must not change — B386 made this possible; keep it true.
2. **Parameter binding:** `$param` becomes a SPARQL `?param` bound via
   `VALUES`/`BIND` injected by `oxigraph_client.py`. **Never** string-interpolate a
   parameter into SPARQL text. The `NamedQuery.__post_init__` static-string
   validation must be extended to the `sparql` field.
3. **Nullable filters** use the `!BOUND(...) ||` form (§3.4). A bare equality
   filter on a nullable column is a defect.
4. **Numeric comparisons** carry explicit datatypes (§3.2).
5. **Bounded traversal:** Cypher variable-length patterns (`*1..2`) become explicit
   `UNION` of fixed-length patterns, or SPARQL property paths with a hard `LIMIT`.
   The existing ≤2-hop and fan-out ceilings from B374/B375/B383 are preserved as
   query structure, not as convention.
6. **Result shape is the contract.** A translated query must return the same column
   names and types its Cypher original returned. The existing test asserting on that
   query's caller is the acceptance check.
7. **Writes:** `CREATE`/`MERGE`/`SET` become `INSERT DATA` / `DELETE WHERE` +
   `INSERT`. **`MERGE` has no SPARQL equivalent** — it becomes
   `DELETE WHERE { ?s ?p ?o }` scoped to the affected predicates, followed by
   `INSERT DATA`. This is not atomic in the Cypher sense; it must run inside a
   single Oxigraph transaction.

---

## 8. Migration and verification

- `campy export-graph` JSONL remains the interchange format (B281). The importer
  gains an Oxigraph backend applying this specification.
- **Round-trip test is the acceptance gate:** Kùzu → JSONL → Oxigraph → JSONL must
  be set-equal on nodes, edges, and edge properties. Ordering differences on
  `STRING[]` are permitted (§3.3); nothing else is.
- The B380 patent claim suite re-runs against Oxigraph through `gateway.py`
  unchanged. Any test needing modification indicates a mapping defect, not a test
  defect — escalate rather than editing the assertion.
- `scripts/check_cypher_ratchet.py` `ALLOWLIST_FILES` must swap
  `kuzu_client.py` → `oxigraph_client.py` at cutover, and `CYPHER_LINE_RE`
  (`MATCH|CREATE|MERGE`) must be reviewed — `CREATE` is also valid SPARQL 1.1
  Update and will false-positive.

---

## 9. Validation harness

Every pattern in §4 was executed against `pyoxigraph 0.5.11` before specification:
plain traversal coexisting with RDF-star annotation, and multiple occurrence nodes
on a single quoted triple. `tests/test_rdf_mapping_spec.py` (B389) must encode
these as executable conformance tests so the spec cannot drift from the client.

---

## 10. Open items requiring escalation

These are **not** decided here and must not be guessed:

1. Exhaustive `EDGE_REIFICATION` classification for all 102 rel tables — the
   families in §4.2 are specified; the remainder need a per-table pass against
   their call sites (B389).
2. Any `STRING[]` column later found to be order-significant (§3.3).
3. Transaction granularity for multi-statement writes currently relying on Kùzu's
   single-writer lock.
