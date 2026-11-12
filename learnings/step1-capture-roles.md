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

Flag `[observations] roles` (env `CAMPY_OBSERVATION_ROLES`), default off, and not in the `principled` profile until step 1 passes. Off is byte-identical
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

Decision (6.1 of the code plan): action Concepts are excluded from the text lookups and from the vector and text indexes, so
a word never resolves to one; step 3 resolves question verbs through the same WordNet sense function and
`roles.action_concept`.

## 7. Form 1 result (killed 2026-11-11)

Form 1 (sections 3-6: three free-span fields added to the fact prompt) was re-captured on conv-26 and hit both kill lines:

| conv-26 | flag off | R111 | form 1 |
|---|---|---|---|
| Facts | 389 | 389 | 383 |
| Anchored | 34.7% | 35.0% | 47.3% |
| Shared | 21.9% | 22.1% | 34.2% |
| `did`/`plans` with `HAS_ACTION` | | | 25 of 135 |
| (quote, object_text) pairs equal to flag off | 389 of 389 (vs R111) | | 168 of 389 |

The longer prompt changed what was extracted (`did` facts fell from 119 to 82), and 5 of the 25 actions had the wrong
sense ("picnic" → `cinch.n.01`). The flag-off capture repeats R111 exactly, so the extraction itself is deterministic and
the shift came from the prompt.

**Baseline correction.** Section 5's conv-26 "today" (42.1% anchored) does not reproduce. Counted the way
`observations.role_fill` counts (live facts with a subject, the conversation selected by `SENT_IN`), conv-26 today is
**35.0% anchored and 22.1% shared**. The shared baseline matches section 5 (22.3%); the anchored one does not.

## 8. Form 2: closed choice (design, for approval)

The flag, edges and queries are the same as in form 1: `[observations] roles` / `CAMPY_OBSERVATION_ROLES`, default off,
in no profile. Form 2 writes `HAS_ACTION`, `HAS_PARTICIPANT` and `HAS_PLACE`; it reads `EVIDENCED_BY`, `MENTIONS`,
`SPOKEN_BY` and `ner_label` (all written today). The free-span fields of form 1 are removed. **The fact prompt is
untouched:** with the flag on, the extraction call is byte-for-byte the flag-off call.

### 8.1 A second, closed call after the turn's facts are written

For each turn, once its facts are written, the rule builds a closed candidate set for each of its `did`/`plans` facts
(sections 8.2-8.3). A turn with no candidate set makes no call. Otherwise one call per turn shows each event fact's
quote and its numbered options, and the model answers per fact with an option number or `0` (none):

```
Fact 1: "Last Fri I finally took my kids to a pottery workshop."
  action: 1 workshop: a brief intensive course for a small group ...   2 workshop: small workplace where handcrafts ...   0 none
  with:   1 Melanie   0 none
```

The rule accepts only an option number shown for that fact and that role. Anything else is a counted rejection and
writes nothing. The model never writes a name, a span, a synset or an id (P3).

### 8.2 Action candidates (closed: WordNet event senses with glosses)

- The head is the root lemma of the fact's `object_text`. When that root is a light verb (`go`, `get`, `take`, `make`,
  `do`, `have`, `be`, `give`, `put`, `keep`, `let`, `come`), the heads are the object's nouns instead ("go on a hike"
  → `hike`, "take my kids to a pottery workshop" → `workshop`).
- **Confirmed:** the head lemma must occur in the fact's quote (spaCy lemmas). Otherwise there is no candidate set.
- The options are the head's WordNet noun senses under `event.n.01`: direct, then through the verb's nominalisations.
  They are ordered by lemma count and capped at 6, each shown as `lemma: gloss`.
- Written: the picked synset as the action Concept, with its hypernym chain as `BROADER` and the same Concept
  rules as form 1 (no embedding, no index, out of the text lookups).
- **Measured on the flag-off store:**
  - 121 of 177 event facts (68%) get at least one sense. The median is 1 option, the mean 2.0 and the cap is 6.
  - The other 56 are mostly feelings and states ("love it", "feel alone", "be a mom") or true WordNet gaps
    ("volunteering", "biking").
  - A verb-hypernym walk recovers 15 of the 56, but almost all wrongly ("see" → `sensing`, "feel" → `decision`,
    "volunteering" → `informing`), so it is **not** in the design.

### 8.3 Partner and place candidates (closed: speakers and admitted Concepts already linked to the source turn)

- **Partner options:**
  - the conversation's speakers other than the fact's subject (from `SPOKEN_BY`);
  - every Concept the source turn `MENTIONS` with `ner_label` PERSON / ORG / NORP, other than the subject.
- **Place options:** every Concept the source turn `MENTIONS` with `ner_label` GPE / LOC / FAC.
- A picked option writes `HAS_PARTICIPANT` / `HAS_PLACE` to that Concept.
- **Fallback, only when the model answers 0 or there were no options** (no model): a dependency-parse rule inside the
  quote's clause. A `with`-object whose head is under `person.n.01` / `social_group.n.01` gives `HAS_PARTICIPANT`; a
  `to`/`at`/`in` object whose head is under the form-1 place roots gives `HAS_PLACE`. Both point to a per-fact
  `ObjectPhrase`. Neither counts as shared.
- **Measured on the flag-off store:**
  - 67 of 177 event facts have an admitted entity as a partner option, in addition to the other speaker, who is an
    option on every fact.
  - **Only 1 of 177 has a place option.** Conv-26's places ("the beach", "the museum", "my mom's house") are not
    admitted entities, so place will almost always come from the phrase fallback.

### 8.4 A rejection count per rule, logged

Each rule counts every outcome by reason:
- action: `no_head`, `head_not_in_quote`, `no_event_sense`, `picked_0`, `pick_out_of_range`, `written`;
- partner and place: `no_options`, `picked_0`, `pick_out_of_range`, `written_concept`, `fallback_phrase`,
  `fallback_none`;
- per turn: `call_failed`, `unparseable`.

The counts sum in `ObservationWorkerStats.roles`, and one INFO line `[Roles] counts {...}` goes to the daemon log every
25 turns and at drain, so a capture's rejection mix can be read from its log. Form 1 kept these counts but never logged
them.

### 8.5 Lines (conv-26 re-capture), and how they were derived

The ceiling is measured on the flag-off store with the closed sets of 8.2 and 8.3. A fact counts toward it if it is
anchored today, or is an event fact with at least one sense or an admitted entity option. The other speaker alone does
not count, because it is an option on every fact.

| conv-26 | Today (R111) | Ceiling | Expected | Pass | Kill |
|---|---|---|---|---|---|
| Anchored | 35.0% | 50.9% | about 44% | **45%** | **41%** |
| Shared | 22.1% | 55.0% | about 43% | 45% (kept) | 35% (kept) |
| Wrong senses on 50 hand-checked actions | | | | 20% or fewer (kept) | |

- **Derivation of the anchored lines.** Use the shared lines, kept because their baseline reproduces, as the yardstick:
  under form 2, shared pass (45%) sits at 70% of the gain from baseline to ceiling (22.1 → 55.0), and shared kill (35%)
  at 39% of it. The same shares of the anchored gain (35.0 → 50.9) give pass 46.1% and kill 41.2%. Rounded down, that
  is **pass 45%, kill 41%**.
- **Expected:** the model picks a sense on 85% of the facts that have one, and partner Concepts are ignored. The
  physical-value object path (kept from form 1) is not counted either. So the expected values are conservative.
- **Read this before approving:** the expected values (about 44% anchored, about 43% shared) sit *between* the kill and
  pass lines. The likeliest outcome is "not killed, not passed", and the plan has no rule for that band. Proposed: treat
  it like a kill, that is, stop and bring it as a contract question, not a third form.

### 8.6 Guards

- **Facts:** flag-on (quote, object_text) pairs must equal flag-off exactly, 389 of 389, as s1off equals R111. Any
  difference stops the step before anything else is measured.
- **Replay:** conv-26's 152 questions, flag on against flag off (`principled`, walk off). A drop of more than 6 stops the
  step.

### 8.7 Added capture time

- **Estimate, not measured** (no separate run): 127 of conv-26's 419 turns hold an event fact, so at most 127 extra
  calls. Each has a short prompt (a quote plus about 2 glossed options per role) and a few output tokens per fact, so
  about 2-4 s per call locally.
- That is **4-8 minutes on the 56-minute flag-off capture (+7-15%)**. It goes in RUNS.md before the run. The run log
  will give the measured time.

### 8.8 Code (one PR, after approval)

- **`roles.py`:**
  - drop the span confirmation and the `propose` path;
  - add the candidate builders (8.2, 8.3), the closed-call prompt and its parser, the dependency-parse fallback, and the
    counted rejections (8.4).
- **`extract.py`:** remove `_ROLE_FIELDS` and `ROLES_MAX_TOKENS`, so the fact prompt is untouched with the flag on. Add
  the per-turn roles call after the turn's facts are written.
- **Reused unchanged:** the queries, edges, schema, shapes and the action-Concept rules.
- **Tests:**
  - the extraction messages with the flag on equal the flag-off golden;
  - candidate sets on hand-written turns;
  - out-of-range and unparseable answers write nothing;
  - the fallback runs only after a 0 or when there are no options;
  - the counts are logged.
- **In the same PR:** the plan row (anchored lines restated), and `e2e-status.md` (step 1: first form killed
  2026-11-11, with its numbers).
