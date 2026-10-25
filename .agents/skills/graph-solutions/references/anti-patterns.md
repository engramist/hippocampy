# Anti-Patterns

Source status:

- Skill distilled: 2026-03-20
- Web sources reviewed: 2026-03-20

Use this file before recommending graph aggressively. It exists to stop bad graph advice early.

## Anti-pattern 1: "The data is connected, so it should be graph"

Most enterprise data is connected. That alone is not enough. Recommend graph only when the important queries are relationship-centric and multi-hop.

## Anti-pattern 2: Unbounded traversal in production

Do not recommend open-ended path patterns for hot paths. Bound the traversal, narrow the entry point, and make the expected fan-out explicit.

## Anti-pattern 3: Using graph for BI-style scans

Do not push full-graph scans, heavy aggregations, or global analytics into a request-path OLTP graph just because the data already lives there.

## Anti-pattern 4: Modeling every attribute as a node

Do not create node explosions for simple scalar facts. Use properties for simple attributes and promote to nodes only when the relationship or fact has its own lifecycle, identity, or relationships.

## Anti-pattern 5: Reifying every relationship

Use relationship nodes or statement nodes only when they are semantically needed. Over-reification makes the graph hard to query and easy to misunderstand.

## Anti-pattern 6: Hiding business identity behind internal ids

Do not build long-lived designs around opaque internal node ids. Preserve stable domain identifiers and, for RDF, canonical IRIs.

## Anti-pattern 7: Assuming all graph languages map cleanly

Do not translate SPARQL, Cypher, and Gremlin as if they are interchangeable. Named graphs, inference, path semantics, duplicates, and edge metadata all change the meaning.

## Anti-pattern 8: Ignoring provider-specific execution

Do not give generic Gremlin advice when the user is on Neptune, or generic Cypher advice when the team depends on a product-specific dialect or operational constraint.

## Anti-pattern 9: Treating graph as a silver bullet for access control

Authorization graphs are powerful, but they still require explicit policy semantics, consistency choices, and careful write governance. Do not oversimplify them into "just traverse the graph."

## Anti-pattern 10: Skipping the pilot

Do not recommend a full replatform when one bounded, query-driven pilot could prove the value. Start with a narrow slice, representative data, and measurable success criteria.

## Guardrail questions

Ask these before recommending graph:

- what are the top queries?
- what is the expected path depth?
- where are the likely dense hubs?
- what must remain explainable?
- what existing system already does this well enough?
- what is the smallest pilot that could prove value?

## Source links

- Neo4j use cases: <https://neo4j.com/use-cases/>
- Neo4j top use cases blog: <https://neo4j.com/blog/graph-database/graph-database-use-cases/>
- Neo4j native graph framing: <https://neo4j.com/blog/cypher-and-gql/native-vs-non-native-graph-technology/>
- LDBC Graphalytics benchmark: <https://ldbcouncil.org/benchmarks/graphalytics/>
- Zanzibar paper landing page: <https://www.usenix.org/conference/atc19/presentation/pang>
