# Graph Database Engines: Comparison and Tuning

## Engine comparison table

| Database | Model | Query Languages | Scalability | ACID | Storage | License | Cloud |
|----------|-------|----------------|-------------|------|---------|---------|-------|
| **Neo4j** | LPG | Cypher 25 | Clustering; secondaries scale reads | Full ACID + WAL | Native store (block format for Enterprise) | Community GPLv3; Enterprise commercial | AuraDB (free tier exists) |
| **JanusGraph** | LPG | Gremlin (TinkerPop) | Distributed multi-machine (100B+ edges) | Transactional (backend-dependent) | Pluggable (Cassandra, HBase, etc.) + ES/Solr/Lucene | Apache 2.0 | Self-managed / partner |
| **Amazon Neptune** | RDF + LPG | SPARQL, Gremlin, openCypher | Managed; storage replicated 6 copies across 3 AZs | Strict transaction semantics | Multi-AZ durability | AWS proprietary | Fully managed |
| **Blazegraph** | RDF | SPARQL; Blueprints (legacy) | Single-machine emphasis (up to 50B edges claim) | N/A (verify per deployment) | Java-based RDF store | GPL-2.0 | Self-managed (powers Wikidata) |
| **Stardog** | RDF (knowledge graph) | SPARQL; reasoning/inference | HA cluster (3+ Stardog + 3+ ZooKeeper); strong consistency; no sharding | "Generally" ACID | RocksDB-based LSM-Tree | Free + Enterprise | Stardog Cloud |
| **Virtuoso** | RDF + SQL (multi-model) | SPARQL Protocol; SQL; inline SPARQL | Clustered options available | ACID via transaction manager | Multi-model RDBMS | Open Source GPLv2; Commercial | Commercial offerings |
| **TigerGraph** | LPG | GSQL; OpenCypher + GQL pattern matching | Native MPP (massively parallel) | ACID / strong consistency | Proprietary compressed format | Commercial; Community Edition | TigerGraph Cloud |
| **Dgraph** | Graph + GraphQL | GraphQL + DQL; HTTP/gRPC | Distributed / horizontal | Distributed ACID (snapshot isolation + Raft) | Badger backing store | Apache-2.0 (+ enterprise features) | Dgraph Cloud |
| **ArangoDB** | Multi-model (doc + graph + KV) | AQL (incl. graph traversals) | Horizontal scalability + HA | ACID | RocksDB (3.7+) | Community License (changed) | ArangoDB Cloud (AMP) |
| **Kùzu** | LPG (embedded) | Cypher subset | Single-machine embedded | Transaction support | Embedded columnar | MIT | N/A (embedded) |

## Engine-specific tuning checklists

### Cypher / Neo4j

- Use `EXPLAIN` to view plans without executing; `PROFILE` to execute with per-operator metrics
- Ensure selective start nodes via indexes/constraints
- Avoid accidental cartesian products
- Bound variable-length traversals
- Validate plan uses indexes where expected
- Schema (indexes/constraints) is optional but valuable for optimization and integrity
- Understand ACID and internal locking (Operations Manual)

### Gremlin / TinkerPop

- Profile with `profile()` for per-step costs (performance overhead caveat)
- Push filters early (`has`, `where`)
- Minimize unbounded `repeat()` expansions
- Avoid global barrier steps until late
- Optimization is provider-dependent — know your backend

### Amazon Neptune (Gremlin + SPARQL)

- Neptune converts TinkerPop steps into Neptune-optimized steps
- **Critical:** When a step lacks Neptune equivalent, that step AND subsequent steps fall back to TinkerPop engine — major performance cliff
- Follow Neptune best practices for caching and query patterns
- Use Neptune's transaction semantics documentation for concurrency

### SPARQL / RDF stores

- **Apache Jena ARQ:** Supports explaining parsed query, algebra, and optimized algebra
- **Stardog:** Query plan analysis is the main performance tool; provides tutorials for reading/improving plans
- Know your indexing model: dictionary encoding + multiple triple indexes (SPO/POS/OSP permutations)
- OPTIONAL is expensive — reduce complexity where possible

### Distributed graphs (JanusGraph, Dgraph)

- **Cross-partition traversals are expensive** — partitioning strategy is central
- **JanusGraph:** Vertex cuts distribute adjacency lists for very high-degree vertices; needed beyond vertex-centric indexing
- **Dgraph:** Predicate-based sharding minimizes network overhead for deep distributed queries
- **ArangoDB SmartGraphs:** Optimize traversal performance in clusters

### Kùzu (embedded, this project)

- Pinned `kuzu==0.11.3` (archived Oct 2025, last stable)
- All Kùzu-specific syntax in `kuzu_client.py` only — portable abstraction
- HNSW vector indexes require `FLOAT[384]` (not `FLOAT[]`)
- Projected graphs for filtered vector search (prefilter before HNSW)
- Multi-table search: `UNION ALL` across per-table index calls, sort by score, LIMIT
- Concurrency: Brain Daemon holds sole READ_WRITE connection; `asyncio.Lock` for writes
- MCP adapters open with `read_only=True` — no write contention
- Named relationships: `FROM Concept TO Concept`
- REIFIED_AS: multi-FROM/TO syntax for artifact type promotion
- Migration path: rewrite `kuzu_client.py` only; watch RyuGraph fork

## Consistency and transactions

Many production graph DBs are fully ACID — the decision is not "ACID vs non-ACID" but which data access patterns the engine optimizes for.

- **Neo4j:** Full ACID + write-ahead transaction log
- **Stardog:** "Generally" ACID with documented semantics
- **Dgraph:** Distributed ACID via snapshot isolation + Raft consensus
- **ArangoDB:** ACID (atomic, consistent, isolated, durable)
- **Neptune:** Strict transaction semantics (because SPARQL and TinkerPop don't define concurrency)

**Note:** SPARQL and Gremlin specs do not define transaction semantics for concurrent processing — vendors define and document their own.

## Indexing strategies

**Relational:** Indexing is central — most queries rely on B-trees/hash indexes for filtering, joins, uniqueness.

**Graph (LPG):** Indexing is for **entry-point lookup** (find start nodes quickly). Once at start node, traversal follows stored adjacency. Index-free adjacency principle.

**RDF triple stores:** Indexing accelerates triple pattern joins. Multi-index strategies (SPO/POS/OSP) and dictionary encodings are standard.

## Benchmarks

- **LDBC Social Network Benchmark (SNB):** Realistic social-network workloads with interactive (transactional) and BI workloads
- **LDBC Graphalytics:** Industrial-grade benchmark for graph analytics platforms (PageRank, BFS, connected components)
- Validate with benchmark-like workloads, not single queries — point comparisons are misleading
