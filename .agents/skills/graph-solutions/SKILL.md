---
name: graph-solutions
description: Decide when graph technology is the right fit, compare graph and relational approaches, choose between RDF and labeled property graphs, and produce concrete modeling, query, translation, migration, tuning, security, and testing guidance across Cypher, Gremlin, and SPARQL. Use when an agent needs to recommend graph solutions, explain graph tradeoffs, design knowledge graphs, dependency graphs, authorization graphs, metadata graphs, lineage or provenance graphs, identity resolution or master data graphs, recommendation systems, fraud-ring analysis, or help implement graph-based systems.
---

# Graph Solutions

Use this skill to help intermediate developers who know databases but are newer to graph systems.

## Workflow

### 1. Classify the request first

Classify the request before answering:

- decision: should this be graph or relational?
- model selection: RDF vs labeled property graph
- query writing: Cypher, Gremlin, or SPARQL
- query translation: SQL to graph, or graph language to graph language
- optimization: why is this query slow and what should change?
- migration: how should an RDF or LPG system be mapped into the other model?
- security: what least-privilege or deployment controls matter?
- testing: what CI or regression checks should be added?

If the request spans multiple categories, answer in that order: decision, then model, then implementation.

### 1a. Gather the minimum intake needed for a good recommendation

Ask for only the missing facts that materially change the answer:

- top 3 to 5 queries or user journeys
- approximate data volume and update rate
- latency or freshness expectations
- likely high-degree hubs or fan-out points
- whether interoperability, ontology, or inference matters
- whether the graph must explain decisions such as access, approval, or lineage
- source systems that would feed the graph

If this information is unavailable, make the assumption explicit and recommend a pilot rather than pretending the fit is certain.

### 2. Decide whether graph is actually the right tool

Do not force a graph answer when the workload is a poor fit.

Recommend relational first when the workload is mostly:

- set-based reporting or OLAP-style scans
- shallow one-hop joins
- heavy transactional invariants that already map cleanly to SQL and mature RDBMS tooling
- global analytics that touch most of the graph in real time

Recommend graph first when the workload is mostly:

- multi-hop traversal
- neighborhood or reachability exploration
- recommendation, fraud, topology, identity, lineage, or dependency queries
- relationship-heavy modeling where the edges carry important meaning

Read [graph-vs-relational.md](./references/graph-vs-relational.md) for the decision framework.
Read [system-improvement-playbooks.md](./references/system-improvement-playbooks.md) when the user is asking how a graph could improve an existing system, workflow, or architecture.

### 3. Choose the graph model deliberately

Choose RDF when the request needs:

- standards-based interoperability
- global identifiers and linked data
- ontology or inference-driven integration
- dataset or named-graph scoping
- statement metadata that should preserve RDF semantics

Choose labeled property graph when the request needs:

- traversal-first application behavior
- intuitive node and edge modeling with native edge properties
- operational graph APIs with direct path queries
- provider ecosystems centered on Cypher, Gremlin, or GQL-style patterns

When edge metadata is the sticking point:

- prefer native edge properties in LPG
- prefer RDF 1.2 triple terms in RDF

Read [model-selection.md](./references/model-selection.md) for modeling rules and caveats.

### 4. Choose the language and engine that match the job

Use these defaults:

- Neo4j plus Cypher for approachable LPG work, pattern matching, and plan-driven tuning
- Amazon Neptune when the environment is AWS-managed and needs Gremlin, SPARQL, or both
- Stardog when RDF, governance, and inference are central
- JanusGraph, Dgraph, TigerGraph, or ArangoDB when distribution, scale, or engine-specific constraints dominate

Balance vendor-neutral advice with concrete examples from Neo4j and Neptune. Call out when a feature is engine-specific instead of pretending it is universal.

Read [engines-and-portability.md](./references/engines-and-portability.md) before recommending a product or portability strategy.

### 5. Produce concrete guidance, not only theory

Default answer shape:

1. `fit`: say whether graph is a good fit and why.
2. `recommended model`: choose RDF, LPG, or stay relational.
3. `recommended engine`: name the engine only if the environment warrants it.
4. `starter schema`: show the first useful nodes, edges, labels, or triples.
5. `starter query or traversal`: give one concrete example.
6. `key risks`: call out path explosion, supernodes, semantic mismatch, provider quirks, or operational cost.
7. `pilot plan`: give the next validation step such as `EXPLAIN`, `PROFILE`, `profile()`, a representative benchmark, or a fixture-based regression test.

If translating across languages, say the mapping is approximate whenever semantics differ around duplicates, inference, named graphs, path semantics, or edge identity.

Read [query-patterns-and-translation.md](./references/query-patterns-and-translation.md) for examples and translation rules.

## Practical Rules

- Index entry points, not traversals.
- Bound variable-length traversals in production.
- Filter early and expand late.
- Treat dense nodes and supernodes as a first-class risk.
- Use edge properties for relationship-scoped facts; promote to a node when the relationship becomes an entity.
- Prefer stable domain identifiers over opaque internal ids when portability matters.
- Use profiling and plan tools routinely, not only after an outage.
- Separate OLTP graph workloads from full-graph analytics.

Read [performance-and-debugging.md](./references/performance-and-debugging.md) for engine-specific tuning guidance.
Read [anti-patterns.md](./references/anti-patterns.md) before recommending a graph for BI-heavy, shallow, or semantics-unclear workloads.

## Migration, Security, and Testing

- Preserve identity when mapping RDF to LPG or LPG to RDF.
- Treat migration as semantic change, not just syntax conversion.
- Recommend least-privilege access, encryption, and auditing as the baseline.
- Use deterministic fixture graphs, conformance suites, and regression checks for hot queries.

Read [migration-security-testing.md](./references/migration-security-testing.md) for mapping rules and CI guidance.

## Prompt Shapes

These are representative requests this skill should handle well:

- "Should this be graph or relational?"
- "Model this domain as RDF or LPG."
- "How could a graph improve this system?"
- "Should this approval model be a graph?"
- "Should this metadata or master data problem become a knowledge graph?"
- "Can a graph help with lineage, impact analysis, or entity resolution?"
- "Translate this SPARQL pattern to Cypher."
- "Why is my Gremlin slow on Neptune?"
- "How do I represent edge properties in RDF?"
- "What tests should I add for query regressions?"

## References

Read only what is needed for the task:

- [graph-vs-relational.md](./references/graph-vs-relational.md) for architecture fit and anti-fit
- [system-improvement-playbooks.md](./references/system-improvement-playbooks.md) for graph-enabled system patterns and workspace-flavored examples
- [model-selection.md](./references/model-selection.md) for RDF vs LPG decisions, identity, and edge metadata
- [query-patterns-and-translation.md](./references/query-patterns-and-translation.md) for query recipes and approximate language mappings
- [performance-and-debugging.md](./references/performance-and-debugging.md) for tuning rules and provider-specific debugging
- [anti-patterns.md](./references/anti-patterns.md) for recommendation guardrails and common graph mistakes
- [engines-and-portability.md](./references/engines-and-portability.md) for database and deployment tradeoffs
- [migration-security-testing.md](./references/migration-security-testing.md) for migration, access control, and CI guidance
- [source-priority.md](./references/source-priority.md) for durable official-source URLs and last-verified notes

## Output Expectations

- Prefer clear recommendations over exhaustive theory.
- Explain tradeoffs without overselling graph technology.
- Keep vendor-specific advice labeled as vendor-specific.
- Surface uncertainty when engine behavior or standard support may vary by version.
- When possible, point the user to the plan or profiling tool that will verify the answer.
