---
name: campy-graph
description: Campy's graph rules for capture, retrieval, bundle assembly and answering. Load before any card that touches campy/brain/thalamus, hippocampus, temporal_lobe or Observations. Answers that a graph query can compute (count, sum, latest, list, exists, before/after) are computed by a SPARQL query anchored on the subject entity, never by Python over text or over rows pulled from the store.
---

# Campy graph skill

General graph theory is in `.agents/skills/graph-expert/` (concepts, SPARQL) and
`.agents/skills/graph-solutions/` (RDF vs property graphs, modelling, anti-patterns). This file is
only what is specific to Campy's store, verified against code and a real benchmark store.

## Why this exists

Lever B505 answered "How many pets will Andrew have?" by regex-parsing the question for a kind word
("pets"), pulling every entity `INSTANCE_OF` pet, and counting rows in Python. No subject, no
relationship: it counted every pet in the conversation (11). The right design is a query anchored on
the subject, and if the edge it needs is not captured, that is a capture gap to fix, not something to
approximate in Python. (Code: branch `claude/b505-rule-aggregation-v2`,
`campy/brain/thalamus/aggregation.py`, `parse_aggregation` ~L129-153, `len(items)` ~L259; not on main.)

## When to load

Any card that changes capture (what is written), retrieval, bundle assembly or answering. Entry
points: `campy/brain/thalamus/` (bundle_compiler, ask), `campy/brain/hippocampus/` (observations,
kinds, concept_links, attribute_properties, graph/gateway), `campy/brain/temporal_lobe/observations/`.

## Rules

1. **The graph computes.** The graph holds knowledge and the answers computable from it. Count, sum,
   latest, list, exists, before/after are SPARQL (`COUNT(DISTINCT ?x)`, `ORDER BY DESC`, `ASK`,
   property paths) anchored on the subject entity. Python never counts, filters or joins what a query
   could, and never pulls a table of edges to walk it in a loop (`BROADER*` is one path expression).
2. **Every fact hangs off its subject.** A claim is subject entity, typed relation, object entity.
   If it cannot be anchored, it is flagged unanchored, not silently kept as free text.
3. **The model proposes, rules decide** (PRINCIPLES 3). LLM output picks from closed sets of existing
   IRIs and relations, never invents IRIs, and is a candidate until a rule or an independent source
   confirms it. Cardinality advice from the extractor is a candidate (attribute_properties.py).
4. **No answer logic driven by regex over question wording** where a graph structure should carry the
   distinction. Resolving question words to existing Concepts (closed set, never creating one) is fine;
   deciding the answer from the words is not.
5. **No write-only terms.** A new predicate, edge or flag must be read by a named query, and the card
   shows that query. No run or provenance machinery dressed as knowledge.
6. **One construction, not one case** (PRINCIPLES 4). The query is parameterised by subject and
   relation; nothing names "pets" or "Andrew".
7. **The model never writes a query.** Every read is a registered NamedQuery parameterised by Concept ids the code resolved from a closed set. Published Text-to-SPARQL/Cypher results show that even frontier models with the schema in hand reverse edges and invent predicates; an ontology check plus repair loop is the minimum when a model must write one. We avoid that whole class of error by never letting it.
8. **How graph results are written out matters.** The same graph serialised differently swings model accuracy by large margins, so a section's layout is structure, not wording. Change it as a lever with a gate, not as a tidy-up. Before merging any retrieval or answering change, open one real rendered prompt on a store copy (`compile_bundle` + `ask._bundle_to_prompt`) and read what the model sees. B527 and B524's unknown-kind fix were both found this way.

## The schema, as built (verified)

Namespace `campy:` = `https://campy.dev/ns#` (graph/oxigraph_client.py:105). Instances are
`https://campy.dev/id/<Table>/<id>` (:106; note `DATA_BASE` :107 is a drifted second base). Node
columns are literals `campy:<column>`; nodes are `a campy:<Table>`. A real store has **one default
graph, no named graphs** (a `GRAPH ?g` query returned nothing). Edge properties (e.g. `gap_seconds`)
are RDF-star reifiers (`rdf:reifies`), so plain edges are plain triples and pathed ones need the reifier.

| Thing | Where | Meaning |
|---|---|---|
| `Message` | schema.py:386 (+`speaker`, `occurred_at` :2021) | one turn; `role` user/assistant; `SENT_IN` Session :1470; `FOLLOWED_BY` Message :1471 |
| `Observation` | schema.py:894 | a source-grounded claim; "no quote, no row" (observations.py module docstring); evidence turns must be `user` (observations.py:60) |
| `Concept` | schema.py:158 | an entity, or a kind when `kind_scheme = 'kind'` (:183); `concept_id` is the literal key |
| `AttributeProperty` | schema.py:946 | an attribute name as a vocabulary node (B509) |
| `OBSERVATION_ABOUT` | schema.py:1478 | Observation to every Concept its text names. **Untyped**: subject and object roles are NOT on the edge |
| `EVIDENCED_BY` | schema.py:1479 | Observation to the supporting Message(s) |
| `MENTIONS` | schema.py:1484 | user Message to Concept it names (rule match, concept_links.py) |
| `INSTANCE_OF` | schema.py:1489; kinds.py:19 | entity to kind ("this thing is one of those") |
| `BROADER` | schema.py:1490; kinds.py:20 | kind to broader kind (`skos:broader`), also AttributeProperty |
| `CLOSE_MATCH` | schema.py:1491; kinds.py:21 | advisory similarity, never walked |
| `IS_A` | schema.py:1485 | legacy kind edge (B503); 0 triples in the store inspected |
| `HAS_PROPERTY` | schema.py:1494; campy_vocab.ttl:84 | Observation to its AttributeProperty, functional (at most one) |
| `DEPRECATED_BY` | schema.py:1443 | **older to newer**; supersession, with `superseded_by/at` literals |
| `HAS_ALT_LABEL` | schema.py:1499 | Concept/AttributeProperty to Label (SKOS altLabel) |

Observation fields that matter: `subject_text`, `subject_id` (literal Concept id, NULL until
resolved), `predicate`, `object_text` (free text), `object_id` (literal Concept id, usually NULL),
`polarity`, `observed_at`, `evidence_text`, `evidence_ref`, and for `has_attribute` the typed
`attr_value`, `attr_value_kind/num/unit/time/ref` (schema.py:894-940, observations.py:166-167).
`predicate` is a closed set of nine: `did, has_attribute, is_a, located_in, owns, relates_to,
prefers, plans, changed_to` (observations.py:50). Functional (single-valued) attributes are declared
in data: seed list `campy_vocab.ttl:100+` (age, occupation, employer, residence, ...), name modifiers
("favorite", "personal best"), or rule-confirmed (attribute_properties.py docstring).

Flags (brainstem/config.py, all default on after B514 unless noted): `observations.enabled` :101,
`observations.entities` (object entity + kind) :109, `owl_properties` :119, `shacl_gate` :123,
`supersede` :124 (off; B499 string rule), `retrieval.graph_linking` :29, `graph_linking_limit` :30
(0 = links written, no walk section), `skos_vocab` :37. SHACL shapes: `shapes/campy_shapes.ttl`
(ObservationShape :40); the gate is `validator.validate_observation_candidate` (observations.py:521).

## How to query

- **Application code**: `get_gateway(db)` (graph/gateway.py:2239), then `await gw.run(name, **params)` or
  `gw.run_sync(name, **params)` (:515). Reads are `NamedQuery(..., sparql=...)` registered under
  `graph/queries/*.py` (NamedQuery :184); params are bound as `VALUES`, and `campy:`, `cid:`, `prov:`,
  `rdf:`, `xsd:` prefixes are auto-prepended (oxigraph_client.py:1572, :1626). A new read becomes a
  NamedQuery; `gw.execute_raw` (:2203) is a counted escape hatch (`scripts/check_cypher_ratchet.py`).
  Good model of the shape: `_bundle_concept_walk` (gateway.py:1605) with `kinds.RELATION_PATH_UP` and
  `RELATION_PATH_NARROWER_CLOSURE` (kinds.py:72-73).
- **Inspection**: never open `~/.campy` or an in-use store. Copy the directory, then
  `pyoxigraph.Store.read_only(copy + "/brain.db")` (pattern: `scripts/graph_structure_report.py`
  `open_store`, :65). `skills/campy-graph/run_patterns.py <copy> [--subject NAME]` runs every query below.
- Observation ids join to Concepts through the **literal** `subject_id = Concept.concept_id`, not an IRI.

## Worked patterns, run on a copy of a real LoCoMo store (844 Observations, 260 Concepts)

Common head: `?c a campy:Concept ; campy:text_raw "Andrew" ; campy:concept_id ?sid .` and
liveness `FILTER NOT EXISTS {?o campy:archived true} FILTER NOT EXISTS {?o campy:DEPRECATED_BY ?newer}`.

| # | Pattern (core clause) | Result | Verdict |
|---|---|---|---|
| 1 | count per subject: `SELECT (COUNT(DISTINCT ?obj)) ... ?o campy:subject_id ?sid ; campy:predicate "owns" ; campy:object_text ?obj` | Andrew 2 (`dog`, `pup`); Audrey 8 | Runs, **not trustworthy**: objects are free text, so "dog" and "pup" may be one animal. Needs `object_id`. |
| 2 | list objects with the source turn: add `campy:evidence_text ?quote ; campy:EVIDENCED_BY ?m . ?m campy:message_id ?msg ; campy:occurred_at ?when` | Andrew: 2 rows, each with quote + message id + date | Works. The row-to-turn link is complete (pattern 5: 9 of 9 for Audrey). |
| 3 | latest value via functional property: `... campy:HAS_PROPERTY ?p ; campy:attr_value ?val ; campy:observed_at ?at . ?p campy:text_raw "occupation" ORDER BY DESC(?at) LIMIT 1` | Jon: `temp job` (the older `lost` carries `DEPRECATED_BY`) | Works for seed-functional attributes. Only 2 supersessions in the store. |
| 3b | typed count as an attribute: same with `"number of pets"` | Audrey: `four` (3 rows, newest first) | Works where the speaker states a number. Andrew's `number of pets` value is `Toby`, a name: extractor error, no rule rejects it. |
| 4a | kind closure, NO subject: `?k campy:BROADER* ?root . ?x campy:INSTANCE_OF ?k` (root `pet`) | 8, for every subject | This is the B505 shape. Correct only as "pets in the store". |
| 4b | kind closure with subject: `?o campy:subject_id ?sid ; campy:OBSERVATION_ABOUT ?x . ?x campy:INSTANCE_OF ?k` | 5 for Andrew AND 5 for Audrey | **Useless as an answer**: `OBSERVATION_ABOUT` is untyped and concepts are shared across speakers. This is the missing edge. |
| 6 | abstain: `ASK {... HAS_PROPERTY ... "residence" ...}` | false | The correct answer is "not recorded". An empty result or `false` is the answer. |

Reading the table: what works today are the **attribute** edges (HAS_PROPERTY + typed value) and the
**evidence** edges. What returns nothing useful is **entity-to-entity ownership**: `owns` has no
`object_id` in most cases (only 68 of 844 Observations have one; 711 of 844, 84%, have `subject_id`), so
"how many things does X own" cannot be a trustworthy query until capture resolves the object to a
Concept and, for a kind question, links it `INSTANCE_OF` a kind. The B505 count was wrong because that
edge is absent, and no amount of Python recovers it.

## Anti-patterns in this repo (real code)

1. **Kind without subject, counted in Python** — B505 above. A question word picks a kind; rows are counted.
2. **Walk and join in Python what the graph has as edges** — `gateway.py:1798` `_successor_statements`:
   pulls every `REPLACES` edge into a dict (:1824), computes the transitive head set with a hand-written
   loop (`heads`, :1886), and decides which statements "mention" an entity by span-matching text
   (`mentions`, :1864) although `MENTIONS` edges exist (schema.py:1484). `REPLACES*` and a `MENTIONS`
   join are one query.
3. **Counting capitalised words to decide "multi-entity"** — `thalamus/memory_decision.py:327`
   `_is_multi_entity` counts non-initial capitalised tokens and quoted spans. The entities a question
   names are knowable by lookup against Concepts, which `bundle_compiler._question_concept_ids`
   (:718) already does (closed-set lookup, never creates a Concept).
4. **Wording regex gating a stage** — `bundle_compiler.py:1006` `_ASSISTANT_WORDS` (B471). Acceptable
   as a router that picks which stage runs; it must never become the answer. Thalamus has ~20
   `re.*` call sites (its reads already go through named queries), so check each new regex against rule 4.

Not anti-patterns: label and span matching that resolves question words to existing Concepts
(`find_existing_concept`, temporal_lobe/observations/extract.py:293), and rule-based vocabulary
consolidation (kinds.py `plan_kind`, attribute_properties.py).

## Design-review checklist (any retrieval, answering or capture PR)

1. Which edge does this answer depend on? Name subject, relation, object.
2. Which query reads it? Paste the SPARQL (a registered NamedQuery), parameterised by subject.
3. Show the query and its result on a real store copy (`run_patterns.py` style). Include the case where
   it returns nothing, and say what the system answers then (abstain, not approximate).
4. If the edge does not exist, this PR is a **capture PR first**: it writes the edge, with the
   model proposing from a closed set and a rule confirming. Do not ship the answering layer on top.
5. Does every answer row link to its source turn (`EVIDENCED_BY` to Message)?
6. Is every new predicate read by something? Is any logic fitted to one question or dataset?
7. Does a regex over question text decide the answer, or only route to a stage?
8. State the PRINCIPLES.md target and the gate result on the published metric (Principle 1).
