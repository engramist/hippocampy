# Query Patterns and Translation

Source status:

- Skill distilled: 2026-03-20
- Source reports last verified: 2026-03-18

## Translation rules

Treat translation as approximate, not exact. Call out semantic mismatches when they matter:

- RDF set semantics vs LPG multi-edge behavior
- inference or entailment vs explicit stored facts
- named graph scoping vs single-graph assumptions
- path semantics and duplicate handling
- edge identity and statement metadata

## Mental mapping

| Intent | SPARQL | Cypher | Gremlin |
|---|---|---|---|
| Match an edge | `?a ex:knows ?b` | `(a)-[:KNOWS]->(b)` | `g.V(a).out('knows')` |
| Filter | `FILTER(...)` | `WHERE ...` | `has(...)`, `where(...)` |
| Optional pattern | `OPTIONAL { ... }` | `OPTIONAL MATCH ...` | `optional(...)` or provider-specific fallback patterns |
| Variable-length path | property path like `ex:knows+` | `[:KNOWS*1..n]` | `repeat(out('knows')).times(n)` |
| Insert | `INSERT DATA` or update forms | `CREATE` or `MERGE` | `addV()`, `addE()` |
| Delete | `DELETE DATA` or update forms | `DELETE` or `DETACH DELETE` | `drop()` |
| Profiling | engine-specific plan tools | `EXPLAIN`, `PROFILE` | `profile()` |

## Common query shapes

### Friends of friends

Use this shape for recommendation-style reasoning.

Cypher:

```cypher
MATCH (me:Person {id:$alice})-[:KNOWS]->(:Person)-[:KNOWS]->(cand:Person)
WHERE cand <> me AND NOT (me)-[:KNOWS]->(cand)
RETURN cand.id, count(*) AS mutuals
ORDER BY mutuals DESC
LIMIT 10
```

Gremlin:

```groovy
g.V().has('Person','id',alice).as('me').
  out('KNOWS').out('KNOWS').as('cand').
  where(neq('me')).
  where(not(__.select('me').out('KNOWS').where(eq('cand')))).
  groupCount().by('id').
  order(local).by(values, desc).
  limit(local, 10)
```

SPARQL:

```sparql
PREFIX ex: <http://example.com/>
SELECT ?cand (COUNT(*) AS ?mutuals)
WHERE {
  ex:alice ex:knows ?x .
  ?x ex:knows ?cand .
  FILTER(?cand != ex:alice)
  FILTER NOT EXISTS { ex:alice ex:knows ?cand }
}
GROUP BY ?cand
ORDER BY DESC(?mutuals)
LIMIT 10
```

### Hierarchical descendants

Cypher:

```cypher
MATCH (root:Node {id:$root})-[:PARENT_OF*1..]->(n:Node)
RETURN n
```

Gremlin:

```groovy
g.V().has('Node','id',root).
  repeat(out('PARENT_OF')).
  emit().
  dedup()
```

SPARQL:

```sparql
PREFIX ex: <http://example.com/>
SELECT ?n WHERE { ex:root ex:parentOf+ ?n }
```

### Edge metadata in RDF

When a user asks for RDF edge properties, do not force old-school reification first. Explain that RDF 1.2 triple terms are the modern fit when the goal is "statements about statements" while preserving RDF semantics.

## Translation guidance

- SQL recursive CTEs often become Cypher variable-length paths, Gremlin `repeat(...)`, or SPARQL property paths.
- `rdf:type` usually maps to labels in LPG translations.
- Predicate IRIs often map to relationship types, but keep the original IRI somewhere if round-trip interoperability matters.
- Single-valued LPG properties may need special handling when RDF predicates are multi-valued.
- Shortest path is not standardized in core SPARQL the way reachability is; say that plainly.

## Prompt bank

Use these as reference tasks when shaping answers:

- "Translate this SPARQL triple pattern into Cypher."
- "Write the Gremlin traversal for friends of friends."
- "Show the Cypher query and tell me how to profile it."
- "Explain the SPARQL version of this recursive SQL query."
- "How do I carry RDF edge qualifiers into a property graph?"

## Source links

- SPARQL 1.2 Query: <https://www.w3.org/TR/sparql12-query/>
- SPARQL 1.2 Update: <https://www.w3.org/TR/sparql12-update/>
- Apache TinkerPop reference: <https://tinkerpop.apache.org/docs/current/reference/>
- Neo4j Cypher manual: <https://neo4j.com/docs/cypher-manual/current/>
- openCypher resources: <https://opencypher.org/resources/>
