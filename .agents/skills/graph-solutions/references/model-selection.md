# Model Selection

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

## Choose RDF when interoperability and semantics lead

Prefer RDF when the system needs:

- globally meaningful identifiers through IRIs
- standards-based interchange across teams or tools
- named graphs or dataset scoping
- ontology-driven integration with RDFS or OWL
- formal semantics or inference as part of the design

Use RDF 1.2 triple terms when statement metadata matters and classic reification would be too heavy.

## Choose labeled property graph when traversal leads

Prefer LPG when the system needs:

- direct node and edge modeling with native edge properties
- traversal-first operational queries
- intuitive application-facing graph APIs
- Cypher or Gremlin driven developer workflows
- schema-by-convention with targeted indexes and constraints

## Identity rules

- In LPG, prefer stable business keys plus uniqueness constraints for portable identity.
- In RDF, preserve canonical IRIs and treat blank nodes carefully because their scope does not map cleanly to LPG identity.
- When converting between models, never discard the original canonical identifier if future synchronization is possible.

## Edge metadata rules

- Use LPG edge properties for relationship-scoped facts such as `since`, `weight`, `role`, or `confidence`.
- Elevate the relationship to a node when it has many attributes, its own lifecycle, or additional relationships.
- Use RDF triple terms when you need statement qualifiers but still want RDF semantics.

## Access-pattern-driven modeling

Design the graph from the hot queries backward:

1. capture the top queries and SLAs
2. sketch the graph to support those paths
3. load representative data
4. write correctness tests
5. profile the query plans or traversals
6. tune labels, relationship types, constraints, and indexes

## Dense-node and supernode discipline

- Watch degree distribution before finalizing the model.
- Avoid routing critical traversals through giant hubs when you can partition by type, time, bucket, or role.
- Materialize shortcut edges only when the shortcut is stable enough to maintain.

## Source links

- RDF 1.2 Concepts: <https://www.w3.org/TR/rdf12-concepts/>
- RDF 1.2 Semantics: <https://www.w3.org/TR/rdf12-semantics/>
- SPARQL 1.2 Query: <https://www.w3.org/TR/sparql12-query/>
- ISO GQL landing page: <https://www.iso.org/standard/76120.html>
- GQL standards site: <https://www.gqlstandards.org/>
- Apache TinkerPop reference: <https://tinkerpop.apache.org/docs/current/reference/>
- Neo4j schema guide: <https://neo4j.com/docs/getting-started/cypher/schema/>
