# Graph Foundations: LPG vs RDF

## Labeled Property Graphs (LPG)

Graphs of **vertices and edges** where both carry **labels** and **key/value properties**. Apache TinkerPop defines this as a "directed, binary, attributed multi-graph."

- Identifiers are typically DB-internal or application-level; global identity is optional
- Edge properties are native and widely used (timestamps, weights, provenance, scores)
- Schema-optional: introduce new relationship types or labels without migrations
- Now has ISO standard: **ISO/IEC 39075:2024 (GQL)** for portability across implementations
- Semantics historically vendor-defined; GQL standardizes the language and core structures

**Best for:** Connected-data applications where direct traversal patterns, relationship properties, and intuitive schema-by-convention are key. Recommendation engines, fraud detection, network topology, identity/access graphs, operational graph applications.

## RDF (Resource Description Framework)

W3C framework built on **RDF graphs (sets of subject-predicate-object triples)** and **RDF datasets (default graph + named graphs)**.

- Identifiers are **IRIs** — globally meaningful, enabling cross-dataset joins
- Formal semantics with entailment regimes (RDF Semantics spec)
- Commonly paired with **RDFS/OWL** for schema/ontology and inference
- Statement metadata historically required reification; **RDF 1.2 triple terms** (RDF-star lineage) now make this less cumbersome
- Open world assumption common in Semantic Web practice

**Best for:** Standards-based interchange, global identifiers, ontology-driven integration, formal reasoning. Linked data, metadata integration, enterprise knowledge graph platforms. Public endpoints like Wikidata SPARQL Query Service.

## Key differences for developers

| Dimension | RDF | LPG |
|-----------|-----|-----|
| Primitive | Triple (s, p, o) in set-based graph | Node/edge instances with labels + properties |
| Identity | IRIs (globally meaningful) | DB-internal or application-level |
| Semantics | Formal entailment regimes; RDFS/OWL inference | Vendor-defined; GQL standardizing |
| Edge properties | RDF 1.2 triple terms or reification patterns | Native, first-class |
| Schema | Ontology-driven (RDFS/OWL) | Schema-optional, convention-based |
| Typical worldview | Open world (incompleteness assumed) | Closed world (what's not stored is absent) |

## Decision workflow

```
Need standards-based data interchange across orgs/tools?
  YES → RDF + SPARQL; add RDFS/OWL if inference needed
  NO → Primary workload is traversal/path queries in app code?
    YES → LPG + Gremlin/Cypher/GQL
    NO → Need formal semantics/inference/ontology alignment?
      YES → RDF
      NO → LPG
```

Additional considerations:
- RDF + statement metadata → Use RDF 1.2 triple terms or named graph patterns
- LPG + vendor portability → Prefer GQL-aligned features; avoid vendor-only extensions

## Mapping between models

### Table → Graph

| RDBMS pattern | Graph construct |
|---------------|----------------|
| One-to-many (FK) | Directed edge |
| Many-to-many join table | Edge with properties, or intermediate node if many attributes |
| Adjacency list (parent_id) | `:PARENT_OF` edge + variable-length traversal |
| Recursive CTE | Variable-length paths / property paths / repeat loops |

### RDF ↔ LPG

| RDF construct | LPG mapping |
|---------------|-------------|
| Resource IRI | Node with `iri` property |
| `rdf:type` triple | Node label(s) |
| Predicate IRI | Relationship type |
| Literal object | Node property |
| Blank node | Synthetic node id, label `_BNode` |
| Statement metadata | Relationship properties OR intermediate node |

| LPG construct | RDF mapping |
|---------------|-------------|
| Node (id, labels, props) | IRI subject + `rdf:type` + predicate triples |
| Edge type | Predicate IRI |
| Edge properties | RDF 1.2 triple terms or reification nodes |

## Storage and locality

**Native graph systems:** Relationships stored as first-class records, physically connected via pointers (index-free adjacency). Adjacent nodes reached without repeated index lookups. Query cost proportional to subgraph actually traversed, not total database size.

**Relational systems:** B-tree/hash indexes + join algorithms. Multi-hop navigation = join chains; number of joins proportional to hop count. Very effective for many workloads, but connected-data workloads scale worse.

**RDF triple stores:** Dictionary encoding (terms to IDs) + multiple triple indexes over (S,P,O) permutations (e.g., SPO, POS, OSP) for efficient triple pattern matching.
