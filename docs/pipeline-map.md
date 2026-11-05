# Pipeline map

What runs between a turn arriving and an answer leaving, stage by stage, and how far each part
follows [PRINCIPLES.md](../PRINCIPLES.md). The pipeline is judged as a whole: a part that lost a
gate while the rest of the pipeline starved it is not thereby shown to be wrong. The plan is to
assemble the principled parts into one profile (a named set of flags) and gate that profile
against main.

Status words: **principled** (follows the principles), **mixed** (partly), **legacy** (built
for the earlier developer-decision tracker; it decides things it should not), **gap** (needed,
missing).

## The shape

```
turn ──► 1 capture ──► 2 graph (facts)        ─┐
               └─────► 3 vector encoding ──────┤
                                               ▼
question ──► 4 question analysis ──► 5 retrieval: three signals ──► 6 fusion ──► 7 prompt ──► 8 answer
                                       a vector (meaning)
                                       b lexical (words)
                                       c graph (anchored on the subject)
```

The answer is triangulated. Vectors find what means something close to the question; words find
exact names and rare terms; the graph says whose fact it is, what kind of thing it is about, and
computes counts, lists, latest and before/after (P2). No one signal decides; each one checks the
others, and the turn text is always the evidence shown (P3).

## 1. Capture (per turn)

| Part | What it does | Status | Flag (default) |
|---|---|---|---|
| Turn storage | Message node: text, speaker, role, `occurred_at`, `FOLLOWED_BY`, `SENT_IN` | principled | always |
| NER and parse (step 1) | spaCy `en_core_web_md`: named entities with labels, noun phrases, dependency parse | principled as evidence | always |
| Old decision tracker (steps 2-7) | gist centroids for software work, decision/constraint/requirement/action-item gate, arbitration, pathway; also decides whether any entity of the turn is stored | **legacy**; drops most named things (conv-43: places 1/22, organisations 0/16, titles 1/9) | always; becomes a side branch (B543) |
| Entity admission (B544) | every named entity becomes a Concept with `ner_label`, `MENTIONS` from the turn, whatever steps 2-7 say | principled | `entity_admission` (off), #387 |
| Relative dates (B538) | `TimeMention` per relative expression, resolved by rule against the turn's date | principled | `turn_dates` (on) |
| Fact extractor | the model proposes subject / predicate / object / time / quote; `record_observation` writes only with a verbatim quote; links to existing Concepts only | **mixed**: subject mostly anchored; object is free text, kinds rarely typed (B540, B542) | `observations` (on) |
| Subject and object roles (B522) | typed `HAS_SUBJECT` / `HAS_OBJECT` edges on Observations | principled | parked, #372 |
| Ownership rule (B523) | first-person possession decided by rule | principled | parked, #373 |
| Kind hygiene and hierarchy (B525, B534, B535) | clean singular kind labels; WordNet and steward propose `BROADER`, a rule promotes | principled | parked, #375, #378, #379 |
| Kind cycles (B541) | refuse a `BROADER` write that closes a cycle | gap | card |
| Typed object entities | the object of a fact as an entity with a kind | **gap**: the main reason subject-anchored queries reach little (L3, B540, B542 screens) | — |

## 2. Graph (the facts)

Oxigraph is the only store (P2). Backbone (P8): `Observation -subject_id/HAS_SUBJECT-> person`,
`-OBSERVATION_ABOUT/HAS_OBJECT-> Concept -INSTANCE_OF-> kind -BROADER*-> kind`,
`-EVIDENCED_BY-> Message`; `Message -MENTIONS-> Concept`; `Message -HAS_TIME_MENTION-> TimeMention`.
State today: 84-87% of Observations carry a subject; about 6% have a typed object entity.

## 3. Vector encoding (index over graph nodes, not a store)

| Part | What | Status |
|---|---|---|
| Model | all-MiniLM-L6-v2, 384 dimensions, ONNX Runtime (B512) | principled |
| What is encoded | Message turns, Observations (claim text), Concepts and their labels, the decision tracker's records, gist centroids (legacy) | mixed: the centroids serve only the legacy gate |
| Where | `vectors.db` (sqlite-vec ANN plane + FTS5 lexical plane), keyed by graph URI | principled (index, not a store) |
| Gaps | one vector per turn (a long turn with several facts is one point); no vector for a fact's object or for a subject's facts as a set | open question, measured before changing |

## 4. Question analysis

| Part | What | Status |
|---|---|---|
| Concepts the question names | 1-3 word spans looked up in the closed Concept set (never creates one) | principled |
| Subject of the question | which person the question is about | mixed: done inside some stages, not once for all |
| Kind and shape | "how many / which / list / latest / when" and the kind asked for | gap: the set-valued router existed only in the L3 screen; B524 has its own |

## 5. Retrieval: three signals

| Signal | Part | What | Status | Flag (default) |
|---|---|---|---|---|
| a vector | conversation | turns with cosine >= 0.30 to the question | principled | on |
| a vector | observations | Observations with cosine >= 0.30 | principled | on |
| b lexical | conversation | FTS5 over turn text; a lexical-only hit needs two content words | principled | on |
| b lexical | observations | FTS5 restricted to Observation URIs | principled | on |
| c graph | observations about named Concepts | Observations `OBSERVATION_ABOUT` a Concept the question names | principled, starved by capture | on |
| c graph | concept walk (B503) | what the graph links to the question's Concepts, 1-2 hops | principled; switched off after a gate run while capture was dropping its targets | `graph_linking_limit` 0 |
| c graph | count and list (B524) | subject-anchored SPARQL computes count / list | principled | parked, #374 |
| c graph | latest and before/after | supersession (B499, B509 OWL properties) | mixed | `owl_properties` (on) |
| c graph | old semantic stage | Concept/Decision labels by similarity, used when there are no Observations | legacy | fallback |

## 6. Fusion

Reciprocal rank fusion (k = 60) inside each stage: vector and lexical for conversation turns;
vector, lexical and named-Concept for Observations. Top 6 seed turns, two neighbours each side,
cap 18 (B487). Status: **mixed**. Fusion happens per stage, not across the three signals; the graph
signal is not a vote in turn selection, so a turn the graph says is the subject's fact about the
asked-for kind ranks no higher than any other turn.

## 7. Prompt

Sections in order: exact facts, semantic (Observations, or the old stage), linked (walk, off),
conversation turns with dates inline (B538), plans, summaries. Status: principled in form (evidence
stays linked to its source turn); what reaches it is limited by stages 1-6.

## 8. Answer

The local answer model; cite or abstain (M1.3). B539: the harness counts some answers as
non-answers that the judge never sees. Status: mixed (B539 open).

## The principled profile (to be assembled)

On: entity admission (B544), roles (B522), ownership (B523), kind hygiene and hierarchy (B525,
B534, B535), count and list (B524), the concept walk with a limit, typed object entities (gap),
question analysis once per question (gap), the graph signal as a vote in fusion (gap). Demoted:
the decision tracker as a side branch that only adds records (B543); the old semantic stage.

Before the profile is gated, each part is checked offline on a store copy: the edge exists, the
query anchored on the subject returns the evidence turns, and one rendered prompt is read. Then
one gate: the profile against main, fresh ingest, unseen conversations, followed by a breakdown
of each miss by the stage where it died.
