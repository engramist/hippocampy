# Step 1 design: capture writes the roles

Plan step 1 (`learnings/e2e-improvement-plan.md`), target `docs/fact-contract.md` section 1. Design only, for approval
before code. Store read: a copy of the R111 store (principled, 2,325 live Observations).

## 1. What the 50 unlinked facts say

Sample: 50 Observations drawn at random (seed 20261110) from the 1,822 that have no `HAS_OBJECT` edge to a Concept.
Each was read with its quote and its whole source turn. Working file: `~/campy-lead/scratch/step1/sample50.txt`.

| Why it has no object entity | n | Examples (sample #) | What fixes it |
|---|---|---|---|
| **A. An event whose content is the verb.** The object slot holds the verb phrase ("go on a hike", "tell"); the turn names a thing, person or place that belongs in a role | 16 | #7 "told Anna the story of my life" (with Anna); #15 "visited my mom's house" (place); #36 "collaborate with musicians" (with); #48 "exploring some parks" (place); #20 "made this grilled dish" (object) | action + object / with / place roles |
| **A'. The same, with no other role in the turn** | 7 | #18 "went on a hike"; #10 "taking a walk"; #13 "get back on the road" (also wrong subject) | action role only |
| **C. The object is a common noun, not a name** | 4 | #3 "kids' books"; #24 "this job"; #19 "mentor a transgender teen"; #2 "cute photos" | object role to a nameless entity (the B546 `ObjectPhrase`), which today gets an edge only for some predicates |
| **E. A feeling, opinion or evaluation** | 18 | #12 "I'm really passionate"; #33 "courage"; #39 "Nature can be really helpful"; #30 "a dream come true" | nothing to anchor: these are `text` by nature (contract decision 2) |
| **G. Not a fact** (pleasantry) or garbled | 5 | #31 "Take care!"; #41 "stay in touch"; #14 subject "my love of engineering" | not a role problem; counted, not fixed here |

Reading of the table:

- **46% (23 of 50) lack the action role.** For 16 of them the turn also names the object, partner or place, and the
  extractor has nowhere to put it, because the form has one `object` slot and it is filled with the verb phrase.
- **8% (4 of 50) are common-noun objects.** An object entity today must be a name that B544 admitted; "books" or
  "job" can only be an `ObjectPhrase`, and `has_attribute` / `is_a` never get one.
- **36% (18 of 50) are text by nature.** Mostly `has_attribute` and `is_a` holding a feeling. No capture change
  should give them an object; the contract keeps them as text with their turn.
- The extractor also splits one event into clauses and sometimes keeps the minor one: #27 keeps "chatting with my
  friends" from a turn whose event is "a road trip with my friends"; #47 keeps "raise some funds" from "set up a 5K
  charity run". The role form lets one fact hold action, partner and place, which is the event.
- One reader, 50 facts: each share is about ±14 points at 95%.

**Relation types.** The 9 predicates are enough for the facts that are facts. The misuse is `has_attribute` and
`is_a` carrying feelings (class E), which is a text fact, not a missing predicate. No predicate is added (contract
decision 1 stands).

## 2. Root causes, in the store

1. The extraction form has no slot for action, partner or place (`extract.py` `PROMPT_TEMPLATE`): every role lands in
   `object_text`.
2. An object entity must be an admitted name (B546 rule: "the rule creates no entity"); common nouns get a per-fact
   `ObjectPhrase`, and only 64 of 498 phrases have a kind.
3. Nothing distinguishes a text fact from an anchored one, so the measure cannot tell a capture gap from a feeling.

## 3. The design

Flag `[observations] roles` (env `CAMPY_OBSERVATION_ROLES`), on under `principled`, default off. Off is byte-identical
to today.

### 3.1 What the model proposes (closed form)

Three more output fields per fact, appended to the B504 entity form (a structural change: new slots, not rewording):

- `"action"`: for `did` / `plans` only, the verb or activity noun exactly as written ("hike", "visited", "pottery
  class"), or null
- `"with"`: who the subject did it with, each exactly as written ("Anna", "my friends"), a list or null
- `"place"`: where, exactly as written ("my mom's house", "the park"), or null

The existing `object` field keeps its meaning, so `object_text` and the rendered prompt line do not change in this
step (layout is a step-3 lever).

### 3.2 The rule that confirms (no model)

Each proposed span is a candidate. A rule keeps it only if all hold:

| Role | Rule | Written |
|---|---|---|
| any | the span occurs verbatim in the turn, inside the clause of the fact's quote (`typed_objects.locate_quote` + `evidence_entities.clause_owner`, both existing) | nothing if it fails; counted |
| action | the span's head lemma (spaCy) has a WordNet noun sense under `act.n.02` or `event.n.01`, through the word itself or the verb's nominalisations. The sense is the most frequent such sense (WordNet lemma counts; ties by sense order). Measured on R111: 998 of 1,104 `did`/`plans` facts (90%) have at least one sense | `Observation -HAS_ACTION-> Concept` where the Concept is the synset: `kind_scheme "action"`, `concept_id "wn:hike.n.01"`, `text_raw` its first lemma. Its hypernym chain up to `act.n.02` is written as `BROADER` with `link_source "wordnet"` (the B534 reifier). Ids come from WordNet, so no id is invented |
| with | the span is a speaker of the conversation or a B544-admitted PERSON / ORG / NORP Concept, or else a common noun phrase whose head is a person or group noun in WordNet (`person.n.01`, `social_group.n.01`) | `Observation -HAS_PARTICIPANT-> Concept`, or `-> ObjectPhrase` (the nameless-entity node B546 already has, one per fact) |
| place | the span is an admitted GPE / LOC / FAC Concept, or a noun phrase whose head is under `location.n.01` or `structure.n.01` in WordNet | `Observation -HAS_PLACE-> Concept`, or `-> ObjectPhrase` |
| object | unchanged B546 path, extended to `has_attribute` / `is_a` only when the value is a common noun under `physical_entity.n.01` (books, photos; not "courage") | `HAS_OBJECT` as today |

**Action kinds are the one place a Concept is created from an outside source.** That is contract decision 3; the
closed set is WordNet's noun synsets under `act`/`event`, and the model never names the sense. Where WordNet has no
sense ("volunteer", "chat", "blog"), no edge is written and the fact's action stays text.

Why the rule picks the sense, not the model: a second model call per turn would add about an hour to each capture
pass. If the rule's sense is wrong on more than 20% of a hand-checked sample of 50 actions after re-capture, the
fallback is that the model chooses among at most five glossed senses and the rule still checks the choice. That is
a separate decision, brought back to you.

### 3.3 Text and unanchored are read, not stored

No new flag literal. A NamedQuery classifies each fact by its edges: `anchored` (an object, action, partner or place
edge, or a typed attribute value), `unanchored` (no `HAS_SUBJECT`), `text` (the rest). A stored flag would be a
second copy of what the edges already say.

## 4. The edges and the queries that read them

| Edge | Written by | Read by (NamedQuery, step 3 unless noted) |
|---|---|---|
| `HAS_ACTION` Observation to action Concept | 3.2 action rule | `facts.by_action_kind`: what did X do, lists and counts of a kind of activity |
| `BROADER` action to action (wordnet) | 3.2 action rule | the same query's `BROADER*` path |
| `HAS_PARTICIPANT` Observation to Concept / ObjectPhrase | 3.2 with rule | `facts.with_participant`: who did X ... with; what did X and Y do |
| `HAS_PLACE` Observation to Concept / ObjectPhrase | 3.2 place rule | `facts.at_place`: where; `LOCATED_IN` is added in step 2 |
| all four | | `observations.role_fill`: the step-1 measure (now) |

The read for "what did X do, of kind K", anchored on the subject:

```sparql
SELECT ?o ?action ?quote ?msg ?when WHERE {
  ?o a campy:Observation ; campy:HAS_SUBJECT ?s ; campy:HAS_ACTION ?a ;
     campy:evidence_text ?quote ; campy:EVIDENCED_BY ?m .
  ?a campy:BROADER* ?k ; campy:text_raw ?action .
  ?m campy:message_id ?msg ; campy:occurred_at ?when .
  FILTER NOT EXISTS { ?o campy:archived true } FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?newer }
} ORDER BY ?when            # VALUES ?s, ?k bound by the caller from closed-set lookups
```

The measure (`observations.role_fill`), per fact:

```sparql
SELECT ?o (IF(EXISTS {?o campy:HAS_SUBJECT ?x}, IF(EXISTS {
      { ?o campy:HAS_OBJECT ?y } UNION { ?o campy:HAS_ACTION ?y } UNION { ?o campy:HAS_PARTICIPANT ?y }
      UNION { ?o campy:HAS_PLACE ?y } UNION { ?o campy:attr_value_kind ?k FILTER(?k != "text") } },
      "anchored", "text"), "unanchored") AS ?standing)
WHERE { ?o a campy:Observation FILTER NOT EXISTS { ?o campy:archived true } }
```

## 5. The measure, reset

The plan's 60% was "facts linked to an object entity" (21.6% today). After the read, that measure is the wrong one:
it counts only named objects, while a hike or "my mom's house" is a role filled by an action kind or a nameless
entity, which the queries read just as well. Proposed measure: **share of facts `anchored`** by the query above, on
one re-captured conversation (conv-26, the smallest; about 1.5 hours of GPU).

| Number | Today (R111) | Expected after step 1 | From |
|---|---|---|---|
| Anchored (object, action, partner, place or typed value) | 43.1% (1,003 of 2,325); conv-26 42.1% | about 69% (range 58-80%) | 503 Concept-linked + 30 of 50 sampled unlinked facts that gain or already hold a role |
| `did` / `plans` with an action kind | 0% | about 85% | 90% have a WordNet sense; some spans will fail the clause rule |
| Ceiling | | about 80% | class E (36% of the unlinked) is text by nature |

A second number guards against anchoring by per-fact nodes alone. **Shared:** the share of facts with at least one
role edge (`HAS_OBJECT`, `HAS_ACTION`, `HAS_PARTICIPANT`, `HAS_PLACE`) to a Concept, including action kinds; an edge to
an `ObjectPhrase` does not count, because no other fact can share that node and no query can join through it.

| Number | Today (R111) | Expected after step 1 | From |
|---|---|---|---|
| Shared | 21.6% (503 of 2,325); conv-26 22.3% (87 of 390) | about 50% | upper bound 57.8% (conv-26 56.2%): today's 503 plus every `did`/`plans` fact whose object root has a WordNet act/event sense; less the spans the clause rule drops |

All gated on re-captured conv-26:

- **Passes** when all three hold:
  1. anchored is 60% or more;
  2. shared is 45% or more;
  3. of 50 actions checked by hand, 20% or fewer have the wrong WordNet sense.
- **Killed:** anchored under 50% or shared under 35%. Then stop and rethink the extraction form, as the plan says.
- **Sense accuracy is part of the pass.** More than 20% wrong means step 1 has not passed, and the fallback
  (the model picks among at most five glossed senses, and a rule checks the pick) goes back to you for a decision.
- **Side-effect guard (stops the step, not a pass line):**
  - Report conv-26's fact count and its `object_text` agreement against conv-26's facts in the R111 store, and
    against a flag-off re-capture of conv-26 made the same way (the capture's own run-to-run noise).
  - Replay conv-26's 152 questions on the flag-on store and on the flag-off store, `principled` with the walk off.
    A drop of more than 6 questions stops the step.
- **Also reported, not gated:** the old 21.6% measure, and the share in each class of section 1 on 50 re-captured
  facts. The score is not expected to move in step 1: nothing reads the new edges until step 3, and `object_text` is
  unchanged.

## 6. Code, after approval

One PR, one flag:

- `temporal_lobe/observations/extract.py`: the three fields under the flag; the existing `object` field unchanged.
- `temporal_lobe/observations/roles.py` (new): the 3.2 rules, writing through NamedQueries only.
- `temporal_lobe/lexicon/wordnet.py`: the action sense and its hypernym chain.
- `hippocampus/schema.py`, `graph/oxigraph_client.py`: `HAS_ACTION`, `HAS_PARTICIPANT`, `HAS_PLACE` (plain edges).
- `graph/queries/roles.py`: the writes, `observations.role_fill`, and the three reads in section 4, each tested on a
  store copy.
- `shapes/campy_shapes.ttl`: `HAS_ACTION` and `HAS_PLACE` at most one per Observation.
- Tests: rules on hand-written turns (including the 50 sampled ones), the role-fill query on a small store, flag off is
  byte-identical.

Risk to watch: action Concepts enter the concept index, so a question word like "hike" will resolve to the action
kind. Nothing reads that in step 1; step 3 relies on it.
