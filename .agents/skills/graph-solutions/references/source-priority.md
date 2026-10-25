# Source Priority

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

Use these sources in order when answering graph questions.

## P0: standards and official product docs

- RDF 1.2 Concepts: <https://www.w3.org/TR/rdf12-concepts/>
- RDF 1.2 Semantics: <https://www.w3.org/TR/rdf12-semantics/>
- SPARQL 1.2 Query: <https://www.w3.org/TR/sparql12-query/>
- SPARQL 1.1 Query Recommendation: <https://www.w3.org/TR/2013/REC-sparql11-query-20130321/>
- SPARQL 1.2 Update: <https://www.w3.org/TR/sparql12-update/>
- SPARQL 1.1 Update: <https://www.w3.org/TR/sparql11-update/>
- ISO GQL landing page: <https://www.iso.org/standard/76120.html>
- GQL standards site: <https://www.gqlstandards.org/>
- Apache TinkerPop reference: <https://tinkerpop.apache.org/docs/current/reference/>
- Neo4j Cypher manual: <https://neo4j.com/docs/cypher-manual/current/>
- Neo4j planning and tuning: <https://neo4j.com/docs/cypher-manual/current/planning-and-tuning/>
- Neo4j schema guide: <https://neo4j.com/docs/getting-started/cypher/schema/>
- Neo4j operations internals: <https://neo4j.com/docs/operations-manual/current/database-internals/>
- Amazon Neptune Gremlin tuning: <https://docs.aws.amazon.com/neptune/latest/userguide/gremlin-traversal-tuning.html>
- Amazon Neptune transactions: <https://docs.aws.amazon.com/neptune/latest/userguide/transactions.html>
- Stardog query performance: <https://docs.stardog.com/operating-stardog/database-administration/managing-query-performance>
- Stardog transactions: <https://docs.stardog.com/operating-stardog/database-administration/transactions>
- Apache Jena ARQ explain: <https://jena.apache.org/documentation/query/explain.html>
- JanusGraph partitioning: <https://docs.janusgraph.org/advanced-topics/partitioning/>
- Dgraph transactions: <https://docs.dgraph.io/design-concepts/transactions-concept/>
- Dgraph minimizing network calls: <https://docs.dgraph.io/design-concepts/minimizing-network-calls/>
- ArangoDB transactions: <https://docs.arango.ai/arangodb/stable/develop/transactions/>
- ArangoDB graph traversals: <https://docs.arango.ai/arangodb/stable/aql/graph-queries/traversals-explained/>

## P1: strong official or high-quality training material

- Graph Databases, 2nd edition PDF: <https://go.neo4j.com/rs/710-RRC-335/images/Graph_Databases_2e_Neo4j.pdf>
- Graph Databases for Beginners PDF: <https://neo4j.com/wp-content/themes/neo4jweb/assets/images/Graph_Databases_for_Beginners.pdf>
- openCypher resources: <https://opencypher.org/resources/>
- LDBC Social Network Benchmark: <https://ldbcouncil.org/benchmarks/snb/>
- LDBC Graphalytics: <https://ldbcouncil.org/benchmarks/graphalytics/>
- TigerGraph system paper: <https://arxiv.org/abs/1901.08248>
- PostgreSQL recursive query docs: <https://www.postgresql.org/docs/current/queries-with.html>

## P2: use-case and architecture pattern references

- Neo4j use cases: <https://neo4j.com/use-cases/>
- Neo4j fraud detection use case: <https://neo4j.com/use-cases/fraud-detection/>
- Neo4j recommendation tutorial: <https://neo4j.com/docs/getting-started/appendix/tutorials/guide-build-a-recommendation-engine/>
- Neo4j IAM and MDM discussion: <https://neo4j.com/blog/graph-database/neo4j-as-an-embedded-database-the-key-use-cases-of-graph-databases/>
- W3C PROV overview: <https://www.w3.org/TR/prov-overview/>
- Zanzibar paper landing page: <https://www.usenix.org/conference/atc19/presentation/pang>

## Use policy

- Prefer P0 when giving definitions, semantics, syntax, standards status, or product-specific operational behavior.
- Use P1 for pedagogy, benchmark context, and broad modeling guidance.
- Use P2 for system-improvement patterns, architecture playbooks, provenance thinking, and authorization or identity examples.
- If a question depends on a provider quirk, prefer that provider's official docs over generalized graph advice.
- If certainty is low, say so and recommend the next verification step such as a query plan, profile, or conformance test.
