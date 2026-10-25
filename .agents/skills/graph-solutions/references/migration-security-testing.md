# Migration, Security, and Testing

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

## Migration rules

Treat migration as semantic mapping, not just query rewriting.

### RDF to LPG

Default mapping:

- resource IRI -> node with preserved `iri`
- `rdf:type` -> label or labels
- predicate IRI -> relationship type or property key
- literal object -> property when it is a simple attribute
- blank node -> synthetic node with preserved scope notes
- statement metadata -> relationship properties or an intermediate statement node

Watch out for:

- multi-valued RDF predicates
- named graph or dataset scoping
- inference-dependent data that will disappear if only explicit triples are migrated
- blank-node identity and lifecycle

### LPG to RDF

Default mapping:

- node -> resource IRI or stable blank-node strategy
- label -> `rdf:type`
- edge -> predicate or a statement resource pattern
- edge properties -> triple terms or explicit statement node patterns when RDF semantics must be preserved

Watch out for:

- internal ids that are not safe as long-term identifiers
- relationship multiplicity and edge identity
- property typing and literal datatypes

## Security baseline

Recommend these controls by default:

- least-privilege roles and scoped credentials
- encryption at rest and in transit
- auditability for writes and schema changes
- network isolation for managed services
- explicit production hardening for engines that are permissive by default

Use vendor-specific security advice only when the engine is known.

## Testing and CI

Recommend this default stack:

- deterministic fixture graphs for correctness tests
- language or standards conformance suites when available
- hot-query regression tests with stored plans or profile baselines
- ephemeral local or containerized databases for CI
- migration equivalence tests on representative data slices

Good regression questions:

- did the query still return the same semantic result?
- did the plan or profile shape change materially?
- did a model change introduce a new dense-node hotspot?
- did a migration preserve identity and relationship meaning?

## Prompt bank

- "Outline a migration plan from RDF to a property graph."
- "What security controls should I add before production?"
- "What tests should I add to catch graph query regressions?"
- "How should I prove the migrated graph is semantically equivalent enough for this app?"

## Source links

- W3C RDF 1.2 Concepts: <https://www.w3.org/TR/rdf12-concepts/>
- W3C SPARQL 1.2 Query: <https://www.w3.org/TR/sparql12-query/>
- Neo4j role-based access docs: <https://neo4j.com/docs/operations-manual/current/authentication-authorization/>
- Stardog transactions: <https://docs.stardog.com/operating-stardog/database-administration/transactions>
- Stardog security overview: <https://docs.stardog.com/security/>
- Amazon Neptune docs home: <https://docs.aws.amazon.com/neptune/>
- Amazon Neptune encryption at rest: <https://docs.aws.amazon.com/neptune/latest/userguide/encrypt.html>
- W3C RDF test cases: <https://www.w3.org/TR/rdf12-test-cases/>
- openCypher resources and TCK entry point: <https://opencypher.org/resources/>
- Apache TinkerPop repository: <https://github.com/apache/tinkerpop>
