# Query Languages: SPARQL, Gremlin, Cypher

## Cross-language equivalence table

Approximate mappings — always caveat semantic differences (RDF set semantics vs LPG multi-edges, inference, named graphs, path semantics).

| Intent | SPARQL (RDF) | Cypher (LPG) | Gremlin (LPG) |
|--------|-------------|-------------|---------------|
| Match edge | `?a ex:knows ?b` | `(a)-[:KNOWS]->(b)` | `g.V(a).out('knows')` |
| Filter | `FILTER(...)` | `WHERE ...` | `has(...)`, `where(...)` |
| Optional | `OPTIONAL { ... }` | `OPTIONAL MATCH ...` | `optional(...)` / `coalesce(...)` |
| Variable-length path | `ex:knows+` (property paths) | `[:KNOWS*1..]` | `repeat(out('knows')).times(n)` |
| Insert | `INSERT DATA { ... }` | `CREATE ...` / `MERGE ...` | `addV()`, `addE()` |
| Delete | `DELETE DATA { ... }` | `DELETE` / `DETACH DELETE` | `drop()` |
| Upsert | DELETE/INSERT WHERE | `MERGE ... ON CREATE SET ... ON MATCH SET ...` | Conditional add patterns |
| Profile | Engine-specific (ARQ explain, Stardog) | `EXPLAIN` / `PROFILE` | `profile()` (overhead warning) |

---

## SPARQL

W3C standard for RDF. Latest Recommendation: SPARQL 1.1 (2013). SPARQL 1.2 in Working Draft (2026).

### Core patterns

- **Basic graph patterns:** Triple patterns where s/p/o can be variables; match subgraphs
- **OPTIONAL/UNION:** Optional patterns and disjunction
- **Property paths:** Variable-length path matching with regex-like operators
- **Aggregation:** GROUP BY, COUNT, SUM, etc.
- **Subqueries:** Nested SELECT within WHERE
- **Named graphs:** `GRAPH <name> { ... }` for dataset scoping
- **Result forms:** SELECT (bindings), CONSTRUCT (RDF graph), ASK (boolean), DESCRIBE

### CRUD examples

**Create:**
```sparql
PREFIX ex: <http://example.com/>
INSERT DATA {
  ex:alice ex:knows ex:bob .
  ex:alice ex:age 34 .
}
```

**Read:**
```sparql
PREFIX ex: <http://example.com/>
SELECT ?friend
WHERE {
  ex:alice ex:knows ?friend .
  FILTER(?friend != ex:alice)
}
```

**Variable-length (friends-of-friends):**
```sparql
PREFIX ex: <http://example.com/>
SELECT DISTINCT ?person
WHERE {
  ex:alice ex:knows+/ex:knows* ?person .
  FILTER(?person != ex:alice)
}
```

**Update:**
```sparql
PREFIX ex: <http://example.com/>
DELETE { ex:alice ex:age ?oldAge }
INSERT { ex:alice ex:age 35 }
WHERE  { ex:alice ex:age ?oldAge }
```

**Delete:**
```sparql
PREFIX ex: <http://example.com/>
DELETE DATA { ex:alice ex:knows ex:bob . }
```

**Named graph scoping:**
```sparql
PREFIX ex: <http://example.com/>
SELECT ?s ?p ?o
FROM NAMED ex:sourceGraph
WHERE { GRAPH ex:sourceGraph { ?s ?p ?o } }
```

### Performance tips

- Make early patterns selective (bind variables early, use VALUES)
- Treat property paths as potentially expensive (can explode in dense graphs)
- OPTIONAL is a major source of complexity — reduce where possible
- Profile with engine tools: ARQ explain (algebra rewriting), Stardog query plan/profiler

### Tooling

- W3C SPARQL Query/Update/Protocol specs (canonical semantics)
- Apache Jena ARQ (SPARQL processor, explain/algebra tools)
- Eclipse RDF4J (Java RDF/SPARQL framework)
- Public endpoints: Wikidata WDQS, DBpedia

---

## Gremlin / Apache TinkerPop

Traversal language + framework for provider-agnostic LPG querying. Functional, data-flow design.

### Core concepts

- **Traversal-based:** Start from vertices/edges, apply step transformations
- **Property graph:** Directed, binary, attributed multi-graph
- **GLVs (Language Variants):** Compile traversals to bytecode, submit to server
- **Provider-dependent:** Actual optimization depends on graph provider (Neptune, JanusGraph, etc.)

### CRUD examples

**Create:**
```groovy
v1 = g.addV('person').property('name','marko').next()
v2 = g.addV('person').property('name','stephen').next()
g.V(v1).addE('knows').to(v2).property('weight',0.75).iterate()
```

**Read (neighbors + filter):**
```groovy
g.V().hasLabel('person').has('name','marko').
  out('knows').
  valueMap('name','age')
```

**Update:**
```groovy
g.V().has('person','name','marko').property('age', 30).iterate()
```

**Delete:**
```groovy
g.V().outE().drop().iterate()         // edges
g.V().properties('name').drop().iterate()  // properties
g.V().drop().iterate()                // vertices
```

**Friends-of-friends:**
```groovy
g.V().has('person','name','alice').
  out('knows').out('knows').
  dedup().values('name')
```

**Recommendation (mutual friend count):**
```groovy
g.V().has('person','name','alice').as('me').
  out('knows').out('knows').where(neq('me')).
  groupCount().by('name').
  order(local).by(values, desc).
  limit(local, 10)
```

### Performance tips

- Filter early (`has(...)` early), limit early
- Use `profile()` for step-level metrics (treat relatively due to overhead)
- On Neptune: unsupported TinkerPop steps force fallback to TinkerPop engine — major performance inflection
- Avoid global barrier steps until late in traversal
- `repeat()` without bounds can explode — always constrain

### Tooling

- Apache TinkerPop reference documentation (canonical step semantics)
- Gremlin Console and Server distributions
- "Practical Gremlin" book (air-routes dataset, hands-on patterns)
- Gremlin-users mailing list / Google Group

---

## Cypher / openCypher

Declarative pattern-matching language created by Neo4j (2011). openCypher (2015) provides open spec + TCK. Converging toward ISO GQL.

### Core concepts

- **ASCII-art patterns:** `(node)-[:REL]->(node)` visual graph patterns
- **Clause pipeline:** MATCH / WHERE / WITH / RETURN + CREATE/MERGE/SET/DELETE
- **EXPLAIN/PROFILE:** Plan inspection and execution metrics
- **Cypher 25:** Current version as of Neo4j 2025.06+; Cypher 5 frozen

### CRUD examples

**Create:**
```cypher
CREATE (alice:Person {id:'alice', name:'Alice', age:34})
CREATE (bob:Person {id:'bob', name:'Bob', age:36})
CREATE (alice)-[:KNOWS {since: 2020, weight: 0.8}]->(bob);
```

**Read:**
```cypher
MATCH (alice:Person {id:'alice'})-[:KNOWS]->(friend:Person)
RETURN friend.id, friend.name;
```

**Upsert (MERGE):**
```cypher
MERGE (alice:Person {id:'alice'})
SET alice.name = 'Alice', alice.age = 35;
```

**Delete:**
```cypher
MATCH (alice:Person {id:'alice'})-[r:KNOWS]->()
DELETE r;

MATCH (alice:Person {id:'alice'})
DETACH DELETE alice;
```

**Friends-of-friends recommendation:**
```cypher
MATCH (me:Person {id:'alice'})-[:KNOWS]->(:Person)-[:KNOWS]->(cand:Person)
WHERE cand <> me AND NOT (me)-[:KNOWS]->(cand)
RETURN cand.id, cand.name, count(*) AS mutuals
ORDER BY mutuals DESC
LIMIT 10;
```

**Hierarchical (all descendants):**
```cypher
MATCH (root:Node {id:$root})-[:PARENT_OF*1..]->(n:Node)
RETURN n;
```

**Shortest path:**
```cypher
MATCH (a:Person {id:$a}), (b:Person {id:$b})
MATCH p = shortestPath((a)-[:KNOWS*..10]->(b))
RETURN p;
```

### Performance tips

- Use `EXPLAIN` first to check plan shape; `PROFILE` only when actively tuning (uses more resources)
- Ensure selective start nodes via indexes/constraints
- Avoid accidental cartesian products
- **Always bound variable-length traversals** (`*..5` not `*`)
- Constraint creation scans existing data and requires privileges

### Tooling

- Neo4j Cypher Manual (planning/tuning, schema, versioning)
- openCypher spec + TCK (Cucumber-based correctness suite)
- Neo4j GraphAcademy Cypher Fundamentals
- APOC procedure library

---

## Full query translation example: Friends-of-friends recommendation

**SQL (relational):**
```sql
SELECT p3.id
FROM person p1
JOIN knows k1 ON k1.src = p1.id
JOIN knows k2 ON k2.src = k1.dst
JOIN person p3 ON p3.id = k2.dst
WHERE p1.id = :alice
  AND p3.id <> :alice
  AND NOT EXISTS (
    SELECT 1 FROM knows k WHERE k.src = :alice AND k.dst = p3.id
  )
GROUP BY p3.id
ORDER BY COUNT(*) DESC
LIMIT 10;
```

**Cypher:**
```cypher
MATCH (me:Person {id:$alice})-[:KNOWS]->(:Person)-[:KNOWS]->(cand:Person)
WHERE cand <> me AND NOT (me)-[:KNOWS]->(cand)
RETURN cand.id, count(*) AS mutuals
ORDER BY mutuals DESC LIMIT 10;
```

**Gremlin:**
```groovy
g.V().has('Person','id',alice).as('me')
  .out('KNOWS').out('KNOWS').as('cand')
  .where(neq('me'))
  .where(not(__.select('me').out('KNOWS').where(eq('cand'))))
  .groupCount().by('id')
  .order(local).by(values, desc)
  .limit(local, 10)
```

**SPARQL:**
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
