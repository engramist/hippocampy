# Performance and Debugging

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

## Core rules

- Index entry points, not traversals.
- Bound variable-length traversals in production.
- Filter early and expand late.
- Treat dense nodes as a first-class risk.
- Avoid global steps in OLTP request paths.
- Store profiling baselines for the hot queries, not just the query text.

## Cypher and Neo4j

Use `EXPLAIN` first to inspect the plan without executing. Use `PROFILE` when you need real operator counts and storage hits.

Look for:

- selective starting nodes
- expected index or constraint usage
- accidental cartesian products
- unbounded variable-length patterns
- operators with explosive row counts

Default tuning moves:

- add or verify uniqueness constraints and indexes on lookup keys
- reduce fan-out before broad path expansion
- bound the path length
- split giant queries when one operator dominates the plan

## Gremlin and TinkerPop

Use `profile()` to inspect step-level cost, and remember it adds overhead.

Look for:

- `has(...)` and `where(...)` steps appearing too late
- repeated expansion without clear stopping conditions
- global barriers or expensive aggregates too early in the traversal
- provider-specific steps or fallback behavior

## Neptune-specific warning

On Amazon Neptune, many TinkerPop steps are translated into Neptune-optimized execution. Unsupported steps can force execution back into the generic TinkerPop engine for that step and the steps after it. When a traversal is unexpectedly slow on Neptune, check step conversion before rewriting the entire model.

## SPARQL and RDF stores

Use engine plan tooling early:

- Apache Jena ARQ explain output for parsed and optimized algebra
- Stardog query plans and profiler views
- engine-specific explain tools for join order, OPTIONAL behavior, and property-path cost

Look for:

- wide OPTIONAL sections
- property paths on dense subgraphs
- low-selectivity triple patterns at the start of the query
- avoidable cross-graph or named-graph scans

## Distributed graph concerns

- JanusGraph: watch partitioning and vertex-cut strategy for very large degree vertices.
- Dgraph: watch predicate-based sharding and network locality.
- TigerGraph and other MPP systems: treat analytics-oriented execution as a different operating model from single-instance OLTP graph stores.

## Good default advice

- start with a representative fixture graph, not only a toy sample
- compare profile output before and after each change
- keep high-degree hubs visible in your model review
- separate correctness debugging from performance debugging
- recommend the next profiling step explicitly in every tuning answer

## Source links

- Neo4j planning and tuning: <https://neo4j.com/docs/cypher-manual/current/planning-and-tuning/>
- Neo4j operations internals: <https://neo4j.com/docs/operations-manual/current/database-internals/>
- Apache TinkerPop reference: <https://tinkerpop.apache.org/docs/current/reference/>
- Amazon Neptune Gremlin tuning: <https://docs.aws.amazon.com/neptune/latest/userguide/gremlin-traversal-tuning.html>
- Amazon Neptune transactions: <https://docs.aws.amazon.com/neptune/latest/userguide/transactions.html>
- Apache Jena ARQ explain: <https://jena.apache.org/documentation/query/explain.html>
- Stardog query performance: <https://docs.stardog.com/operating-stardog/database-administration/managing-query-performance>
- JanusGraph partitioning: <https://docs.janusgraph.org/advanced-topics/partitioning/>
- Dgraph transactions: <https://docs.dgraph.io/design-concepts/transactions-concept/>
