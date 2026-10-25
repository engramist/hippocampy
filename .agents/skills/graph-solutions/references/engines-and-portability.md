# Engines and Portability

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

## Balanced defaults

- Recommend Neo4j when the team wants the smoothest Cypher-first property graph workflow.
- Recommend Amazon Neptune when the environment is AWS-managed and the system may need Gremlin, SPARQL, or both.
- Recommend Stardog when RDF, ontology, governance, and enterprise knowledge graph features dominate.
- Recommend JanusGraph, Dgraph, TigerGraph, or ArangoDB only when the workload or platform constraints clearly justify the extra specialization.

## Quick engine guide

| Engine | Best fit | Watch out for |
|---|---|---|
| Neo4j | approachable LPG work, Cypher, plan-driven tuning, operational app graphs | portability of vendor features, dense-node tuning, enterprise feature boundaries |
| Amazon Neptune | managed AWS graph workloads, mixed Gremlin and SPARQL needs, operational durability | provider-specific execution behavior, unsupported Gremlin step conversion, managed-service constraints |
| JanusGraph | distributed LPG workloads on pluggable backends | operational complexity, backend tuning, partitioning design |
| Stardog | RDF, inference, governed enterprise knowledge graphs | cluster and licensing tradeoffs, no sharding in HA design |
| Virtuoso | RDF plus SQL or multi-model integration needs | multi-model complexity, product-specific operational model |
| Blazegraph | legacy RDF environments and some SPARQL-heavy cases | maintenance expectations, deployment-specific security hardening |
| TigerGraph | large-scale native MPP graph workloads | product-specific query model and operational learning curve |
| Dgraph | distributed graph with GraphQL-facing workflows | product-specific DQL and sharding behavior |
| ArangoDB | multi-model systems that need graph plus document behavior | AQL-specific patterns, cluster behavior, broader multi-model tradeoffs |

## Portability rules

- Prefer standard SPARQL for RDF portability.
- Prefer GQL-aligned or openCypher-adjacent features when LPG portability matters.
- Avoid engine-specific query extensions unless the product choice is already fixed.
- Preserve canonical identifiers and model-level semantics during migrations.
- Label provider-specific advice clearly so it does not sound universal.

## Portability warnings

- Gremlin is provider-agnostic at the framework level, but execution characteristics can differ sharply by engine.
- openCypher is useful for shared concepts, but product-specific Cypher dialect behavior still matters.
- RDF portability improves when you stay close to W3C standards and do not depend heavily on store-specific SPARQL extensions.

## Source links

- ISO GQL landing page: <https://www.iso.org/standard/76120.html>
- GQL standards site: <https://www.gqlstandards.org/>
- Neo4j docs home: <https://neo4j.com/docs/>
- Amazon Neptune docs home: <https://docs.aws.amazon.com/neptune/>
- JanusGraph docs: <https://docs.janusgraph.org/>
- Stardog docs: <https://docs.stardog.com/>
- Virtuoso open source: <https://github.com/openlink/virtuoso-opensource>
- Blazegraph repository: <https://github.com/blazegraph/database>
- TigerGraph paper: <https://arxiv.org/abs/1901.08248>
- Dgraph docs: <https://docs.dgraph.io/>
- ArangoDB graph traversals: <https://docs.arango.ai/arangodb/stable/aql/graph-queries/traversals-explained/>
