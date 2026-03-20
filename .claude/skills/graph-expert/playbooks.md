# Graph Playbooks: Modeling, Migration, Security, Testing

## Modeling patterns

### Access-pattern-driven design

The fastest graph applications are designed **from access patterns backward**, not from table normalization.

**Workflow:**
1. Capture top queries + SLAs
2. Sketch graph model to serve those queries
3. Load representative sample data
4. Write queries + correctness tests
5. Profile plans/traversals
6. Tune model + indexes/constraints
7. Load full data + performance regression suite
8. Deploy + monitor + iterate

### LPG modeling patterns

- **N-ary relationships:** Represent as intermediate node (e.g., `Purchase` connecting `Customer` and `Product`) when relationship has many attributes or connects >2 parties
- **Event modeling:** Events as nodes; event properties store payload; event edges connect to participants
- **Supernode mitigation:** Add "Bucket" or "Group" nodes to reduce degree if traversals are too dense
- **Edge properties:** Use for small, relationship-scoped facts (timestamp, weight, role). Elevate to node when relationship is an entity with many attributes, lifecycle, or additional relationships
- **Multiple edge types allowed:** TinkerPop defines property graph as a multi-graph — multiple edges of same type between same nodes when needed (e.g., multiple transactions)

### RDF modeling patterns

- **Use IRIs intentionally** for stable identity and cross-dataset joins
- **Schema/ontology layering** with RDFS/OWL where semantics and inference required
- **Statement metadata** using RDF 1.2 triple terms when qualifiers/provenance needed (instead of heavy reification)
- **Named graphs** for dataset scoping, provenance tracking, and access control

### Identity strategies

**LPG:** Choose internal IDs (fast but not portable) vs stable domain keys (`userId`, `accountNumber`) with uniqueness constraints/indexes.

**RDF:** Identity anchored in globally meaningful IRIs. RDF graphs are sets of triples; identity model is built into the framework.

### Cardinality and degree distribution

Graph performance depends heavily on traversal branching:
- Selective start node + bounded degree relationships → fast
- Traversals through degree-heavy hubs → cost explosion (must process many candidate edges before filtering)
- Neo4j has special relationship storage for high-degree nodes — this is a real engineering concern

---

## Migration strategies

### RDF → LPG

| RDF construct | LPG mapping | Caveats |
|---------------|-------------|---------|
| Resource IRI | Node with `iri` property | Preserve canonical IRI for future integration |
| `rdf:type` triple | Node label(s) | RDF permits multi-typing; LPG labels also allow multiple |
| Predicate IRI | Relationship type | Normalize IRI → type name safely (prefix/local-name) |
| Literal object | Node property | Multi-valued → arrays or separate nodes |
| Blank node | Synthetic node id; label `_BNode` | Blank node scope semantics differ |
| Statement metadata | Relationship properties OR intermediate node | RDF 1.2 triple terms bridge if keeping RDF semantics |

### LPG → RDF

| LPG construct | RDF mapping | Caveats |
|---------------|-------------|---------|
| Node (id, labels, props) | IRI subject + `rdf:type` + predicate triples | Need stable IRI minting strategy |
| Edge type | Predicate IRI | Directionality fits (RDF edges are directed) |
| Edge properties | RDF 1.2 triple terms or reification nodes | Triple terms exist specifically for this |

### Migration workflow

1. Inventory source model
2. Define target access patterns
3. Choose mapping rules: identity, labels/types, edge props, literals
4. Build ETL pipeline + validation suite
5. Load small sample + run equivalence tests
6. Load full data + performance tune
7. Cutover plan + dual-write/CDC if needed

### Important premise

Migration is not purely syntactic — models differ in:
- Identity handling (IRIs vs internal IDs)
- Edge identity / multi-edges
- Semantics / inference
- Graph scoping (named graphs)
- Statement metadata

---

## Security and access control

Baseline: **least privilege + encrypt + audit** with DB-specific hooks.

| Database | Security model |
|----------|---------------|
| **Neo4j** | Role-based access control; privilege management via Cypher (Operations Manual) |
| **Stardog** | Standard RBAC; users/roles/permissions management documented |
| **ArangoDB** | HTTP Basic or JWT authentication for internal APIs; on by default |
| **Neptune** | Encryption at rest via AWS KMS; IAM authentication + VPC isolation |
| **Blazegraph** | Ships without SSL/authentication by default — enable for production |

### Security checklist

1. Enable authentication (some DBs ship insecure-by-default for dev convenience)
2. Use role-based access control where available
3. Encrypt at rest and in transit
4. Isolate network access (VPC, firewall rules, bind to localhost for embedded)
5. Audit access patterns
6. Parameterize queries (avoid injection in Cypher/Gremlin/SPARQL string construction)

---

## Testing and CI

### Conformance suites

- **W3C RDF/SPARQL tests:** W3C hosts test suites; SPARQL 1.2 test suite noted
- **openCypher TCK:** Cucumber-based tests for certifying Cypher correctness
- **TinkerPop testing infrastructure:** Ensures consistent behavior across language bindings/variants

### CI patterns

1. **Ephemeral DBs via Docker** — spin up for tests, tear down after (Dgraph recommends Docker; Neo4j has official Docker images)
2. **Deterministic fixture graphs** — small, reproducible test datasets
3. **Query result assertions** — assert expected output for known inputs
4. **Property-based / randomized tests** — for traversal logic edge cases
5. **Performance regression smoke queries** — track plan changes:
   - Cypher: EXPLAIN/PROFILE snapshots
   - Gremlin: profile() summaries
   - SPARQL: plan tool output
6. **Conformance suite integration** — run relevant TCK/W3C tests for your engine

### Practice datasets

- **Neo4j Movies:** Built-in example, good for Cypher learning
- **TinkerPop Modern:** Demo graph used in TinkerPop docs
- **Air-routes:** 3,373 airports / 43,400 routes (Practical Gremlin book)
- **Wikidata:** Public knowledge graph + SPARQL endpoint
- **DBpedia:** SPARQL endpoint (Virtuoso-based)
- **LDBC SNB:** Benchmark datasets for repeatable performance testing
