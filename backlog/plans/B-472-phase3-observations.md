# B472 Phase 3 - Observations: Design

Card: `backlog/B472.md` (Steps 3, 4 and 7). Status: **design for review**;
nothing is built. Phases 1 and 2 are merged (`8894ea4`, `490c4b8`); their
measurements (R21, R22 on engramist/hippocampy#278) are pending, and Phase 3
code should not merge before they show no regression.

## 1. Goal and non-goals

**Goal.** Turns say things about people and things. Campy should store those
statements as typed, source-grounded `Observation` nodes, so that later
phases can rank, link and render them. Examples:
- "I adopted a puppy last week";
- "my sister is a nurse";
- "Caroline went to a support group on 7 May".

Each Observation cites the verbatim span of the turn it came from.

**Phase 3 delivers:**
- the `Observation` table and its edges;
- one write API that enforces grounding;
- two producers: a deterministic pattern route and a bounded,
  quote-validated LLM route;
- a background worker that runs them;
- a diagnostic that dumps observations for a precision check.

**Not in Phase 3** (later phases of the card):
- pronoun resolution beyond the speaker, relative-time resolution,
  supersession and promotion rules (Phase 4, Steps 5 and 8);
- the bundle stage that shows observations to `ask` (Phase 5, Step 9).

Phase 3 changes no retrieval, so benchmark accuracy should not move. Its
gate is observation precision (section 9), not a benchmark score. That is
deliberate: we measure whether the observations are right before anything
reads them.

**What Phase 0 showed** (R20a, DMR, 50 stores, hippocampy `402c96c`):
- 87% of Concepts had no gist class;
- 25% of Concepts were time phrases;
- relation extraction wrote 943 ALTERNATIVE_TO and 233 CHOSEN_OVER edges
  between things like "Mustang" and "my car".

Grounded observations are the place to put what those edges were trying to
say. Section 10 also proposes stopping the noise at its source.

## 2. Where it runs: an Observation worker, not the periodic sweep

Three places could run extraction:

| Option | Problem |
|---|---|
| In the Loop, per turn | One LLM call per turn. B468 just took the Loop's LLM steps off the event loop because they froze the daemon, so per-turn LLM work is the wrong direction. A batch gives the model context too ("she" in turn 12 is the "Caroline" of turn 11). |
| In `run_sweep` (every `sweep_interval_seconds`, default 300) | Up to 5 minutes of lag. Benchmarks "settle" by waiting for `context_status.consolidation_pending == 0` (B448), which only counts the Loop queue, so a probe would race extraction. The sweep already runs several LLM steps on its own schedule. |
| **A dedicated Observation worker (recommended)** | A second background task in `brain_daemon.py`, next to `_loop_worker`, fed after each Loop run. It batches per session and its backlog counts toward `consolidation_pending`. |

**Worker contract:**
- **Input.** After `run_loop` finishes a message, the Loop worker enqueues
  `(message_id, session_id, role, speaker)` on an `observation_queue`.
  - Only user turns go in, for now. Assistant turns are capped and untrusted
    (ISSUE-024), and B471 already covers questions about the assistant's own
    words.
  - Document extracts (`ingest_document`) are out of scope for Phase 3.
- **Batching.** The worker groups queued messages by session. It flushes a
  session's batch when either:
  - it holds `llm_batch_turns` messages (default 20); or
  - no new message has arrived for that session for `idle_flush_seconds`
    (default 5).
- **Per batch:**
  1. read the messages (text, speaker, `occurred_at` / `created_at`) in
     session order;
  2. run the pattern route (section 5a);
  3. run the LLM route (section 5b), if enabled;
  4. write through the write API (section 4).
- **Settle.** `consolidation_pending` becomes Loop backlog plus observation
  backlog (queued plus in-flight messages). The B448 harness settle then
  waits for observations with no harness change.
- **Failure.** Same as B434/B472 Phase 2: unpack inside the try block, log a
  bad batch and skip it, never crash-loop.
- **Placement** (`docs/codebase-anatomy.md`):
  - the worker loop is daemon lifecycle, so `brain_daemon.py`;
  - the extraction logic decides what something is, so
    `campy/brain/temporal_lobe/observations/`;
  - the table, the write API and the queries are durable storage, so
    `campy/brain/hippocampus/observations.py` plus
    `graph/queries/observations.py`.

## 3. Data model

### 3.1 `Observation` node (new; added to `PROVENANCE_TABLES`)

| Column | Type | Notes |
|---|---|---|
| `observation_id` | STRING PK | uuid |
| `subject_text` | STRING | the subject as written ("I", "my sister", "Caroline") |
| `subject_id` | STRING | resolved Concept id; NULL if unresolved |
| `predicate` | STRING | from the controlled set (3.3) |
| `object_text` | STRING | literal value or object phrase as written |
| `object_id` | STRING | resolved Concept id, if the object is an entity; else NULL |
| `event_text` | STRING | short normalized description, for `did` |
| `time_text` | STRING | the time phrase as written ("last Saturday"); NULL if none |
| `time_start`, `time_end` | TIMESTAMP | Phase 3 sets these only for explicit absolute dates (5c); relative times wait for Phase 4 |
| `time_precision` | STRING | `day`/`week`/`month`/`year`/`unknown` |
| `speaker` | STRING | who asserted it (from the Message); not always the subject |
| `polarity` | STRING | `asserted`/`negated`/`hypothetical`/`planned` |
| `confidence` | DOUBLE | tiers as in the Loop: < 0.60 not written; 0.60-0.90 `confidence_low`; > 0.90 full |
| `confidence_low` | BOOLEAN | |
| `extraction_method` | STRING | `pattern` / `llm` (`deterministic` is reserved for Phase 4 rules) |
| `evidence_ref` | STRING | source Message id, **required** |
| `evidence_start`, `evidence_end` | INT64 | char offsets of the supporting quote in the Message's stored text, **required** |
| `evidence_text` | STRING | the quote itself, kept for audit; equals `text_raw[start:end]` |
| `text_raw` | STRING | rendered sentence for search: "Caroline - did - attended an LGBTQ support group (7 May 2023)" |
| `embedding` | FLOAT[384] | of `text_raw`; vector-indexed (B454 `_SPECS` entry) |
| `rule_version` | STRING | extractor version, e.g. `pattern-1`, `llm-1` |
| B312 provenance + supersession columns | | `source`, `source_version`, `observed_at` (= the turn's time), `superseded_by`, `superseded_at`, `supersession_reason` |
| `archived`, `flagged_for_review`, `created_at` | | as other fact tables |

The single-span pair (`evidence_start`/`evidence_end`) keeps the row flat. A
second supporting turn adds an `EVIDENCED_BY` edge (3.2) without rewriting
the node.

### 3.2 Edges (new; each must be classified in `EDGE_REIFICATION`)

| Rel | From -> To | Class | Why |
|---|---|---|---|
| `OBSERVATION_ABOUT` | Observation -> Concept | plain | subject and entity-object links; the role sits on the node (`subject_id`/`object_id`) |
| `EVIDENCED_BY` | Observation -> Message | plain | one edge per supporting turn; the first one matches `evidence_ref` |
| `DEPRECATED_BY` | Observation -> Observation | (existing table, extended `FROM`) | Phase 4 supersession; Phase 3 never writes it |

`ABOUT` is too generic a name for the RDF predicate namespace. Hence
`OBSERVATION_ABOUT`.

**Collateral each new table and edge requires** (all checked by existing
tests and scripts; none can be skipped):
- `schema.NODE_TABLES` / `REL_TABLES` DDL and `_MIGRATIONS`.
- `PROVENANCE_TABLES` gains `Observation`.
- `oxigraph_client.EDGE_REIFICATION` entries.
- `docs/rdf-schema-mapping.md` §4.2: the classification and its reason.
- `scripts/generate_migration_fixture.py` and
  `tests/test_migration_fixture_conformance.py`: the counts go from 57
  nodes / 110 rels to 58 / 112, and the fixture is regenerated. Phase 1's
  fixture lesson applies: only the new rows should change.
- `queries/vector_indexing._SPECS` for the create query.
- `scripts/check_schema_conformance.py` and the Cypher ratchet: the new
  queries go through `NamedQuery` only, never inline.
- `tests/test_b396_sparql.py` query counts.

### 3.3 Controlled predicate set (v1)

A predicate is added by review, never by the model. The validator rejects
any other value.

| Predicate | Meaning | Single-valued? (Phase 4 supersession) | Example |
|---|---|---|---|
| `did` | an event the subject took part in | no | "Caroline attended a support group" |
| `has_attribute` | a property of the subject; the attribute name goes in `object_text` as `name: value` | per attribute name (`job`, `age`, `name`...) | "my sister is a nurse" -> `job: nurse` |
| `is_a` | type or role | no | "Max is my dog" |
| `located_in` | where the subject lives or is based | yes | "I live in Denver" |
| `owns` | possession | no | "I have a golden retriever" |
| `relates_to` | a relationship to another person | per relation name | "Melanie is my friend" -> `friend: Melanie` |
| `prefers` | a like, dislike or preference; `polarity` = negated for dislikes | no | "I love hiking" |
| `plans` | an intention; future events use this, never `did` | no | "I'm going to Paris in June" |
| `changed_to` | a stated change of state | (the new value supersedes) | "I moved to Denver" -> also implies `located_in` |

Software and project facts ("we chose PostgreSQL") stay with the existing
decision family. The pattern and LLM routes skip a clause whose subject is
"we" and whose verb is a decision verb. The decision senses own those.

## 4. Write API: grounding enforced in code

`hippocampus.observations.write_observation(db, obs: ObservationDraft) ->
WriteResult` is the **only** writer. It rejects, with a counted reason
(`activity.log` + summary), any draft that fails these checks:

1. `evidence_ref` names an existing, non-archived Message.
2. `evidence_text` normalized (collapse whitespace, unify quotes) is a
   substring of the Message's `text_raw` normalized the same way. The
   offsets are recomputed from the match, never trusted from the producer.
   This is the grounding rule: **no quote, no row**.
3. `predicate` is in the v1 set. `polarity` is in its set.
4. `confidence >= 0.60`.
5. `subject_text` is non-empty and appears in the quote, or is a
   first-person word ("I", "my", "me") when the speaker is known.
6. Length caps: `evidence_text <= 400` chars, `object_text <= 200`.

**Duplicates.** A draft with the same `(subject_id or normalized
subject_text, predicate, normalized object_text, time_text)` as a live
Observation adds an `EVIDENCED_BY` edge to that row and bumps
`last_accessed_at`. It does not create a second row. A second *independent*
supporting message is the input Phase 4's promotion rule needs.

Writes go through `NamedQuery`s in `graph/queries/observations.py`.

## 5. Producers

### 5a. Pattern route (no LLM; always on when Observations are enabled)

spaCy's dependency parse (the Loop already loads `en_core_web_md`) over each
user turn. A small rule table, versioned as `pattern-1`, where each rule
yields a draft with the clause's character span as `evidence_text`:

| Pattern (subject is "I", a PERSON, or a known Concept) | Predicate |
|---|---|
| `I am / I'm (a|an) X`, `X is my Y` | `is_a` / `relates_to` |
| `I work as X`, `I'm a X at Y`, `my job is X` | `has_attribute` (`job: X`) |
| `my <relation> is <PERSON>`, `<PERSON> is my <relation>` | `relates_to` |
| `I live in GPE`, `I'm based in GPE` | `located_in` |
| `I moved to GPE` | `changed_to` (+ `located_in`) |
| `I (have|own|got|bought|adopted) X` | `owns` |
| `I (love|like|enjoy|hate|can't stand) X` | `prefers` (negated for hate) |
| `I (went|attended|visited|started|finished|ran|joined) X` | `did` |
| `I'm going to / planning to / will X` | `plans` |
| the same verbs with a PERSON subject | the same, `subject_text` = the PERSON |

- A DATE or TIME entity inside the clause becomes `time_text`.
- A negation dependency sets `polarity=negated`. A conditional ("if I") sets
  `hypothetical`.
- Pattern drafts get confidence 0.70, or 0.80 when the subject is a resolved
  Concept and the clause has no hedging word ("maybe", "might", "think").

This route is cheap and deterministic, but limited in recall. It sets the
floor.

### 5b. LLM route (bounded, quote-validated; `[observations] llm_enabled`)

One call per batch:
- `max_tokens` capped at 1024;
- the client comes from `create_llm_client_for_step(config,
  "observations")`, which falls back to the Loop's client;
- the call is run via `asyncio.to_thread`, as B468 did.

**Prompt shape:**
- Numbered turns: `[id] (speaker, date) text`, each truncated to 600 chars.
- The v1 predicate table with one example each.
- The rules:
  - only facts a speaker states about themselves or a named person;
  - no inference;
  - copy the supporting words exactly into `quote`;
  - for any opinion or question, output nothing;
  - return `[]` when there is nothing to extract.
- Output: a JSON array of `{turn_id, subject, predicate, object, time,
  polarity, quote, confidence}`.

**Validation** (before `write_observation`):
- `turn_id` must be in the batch;
- `quote` goes through the substring check against *that* turn (section 4,
  check 2);
- `predicate` must be in the set;
- unknown keys are dropped;
- anything failing is dropped and counted by reason.

The worker logs `llm_proposed`, `llm_written` and `llm_dropped{reason}` per
batch to `activity.log`. **The drop rate is the paraphrase detector.** If an
8B model paraphrases instead of quoting, it shows up as
`drop: quote_not_found`, not as bad rows.

**What the model may not do:**
- invent predicates (rejected);
- merge entities (it returns text; resolution is section 6's job);
- set supersession (it has no field for it);
- write anything directly.

### 5c. Absolute dates (deterministic)

`time_text` that parses as an explicit date sets `time_start`/`time_end` and
`time_precision`. Examples: "7 May 2023", "May 2023", "2023-05-07", "in
2019". Phase 3 needs no new dependency for this, only a small `strptime`
table.

Relative phrases ("last Saturday", "ten years ago") keep `time_text` only.
Resolving them against the turn's `occurred_at` is Phase 4's rule.

## 6. Subject resolution (minimal in Phase 3)

- **First person** ("I", "my", "me"): the turn's speaker Concept. Phase 2
  seeds it for named speakers. With no named speaker, `subject_text = "the
  user"`, unresolved but consistent.
- **A name:** `find_concept_by_exact_text`, then
  `find_concept_by_label_text` (Phase 2). No match stores
  `subject_id = NULL` with the text. Phase 3 never creates a Concept.
- **Pronouns** ("she", "they") and possessives ("my sister"): unresolved in
  Phase 3, stored with their text. Phase 4 resolves them by speaker and
  previous-turn rules. A batch gives the LLM the context to name the person,
  but the quote still has to contain the words it cites.

## 7. Config

```toml
[observations]
enabled = false          # Phase 3 ships off; benchmarks turn it on
llm_enabled = true       # only read when enabled
llm_batch_turns = 20
idle_flush_seconds = 5
max_turn_chars = 600
```

It ships **disabled**, so a user's daemon does not start making extra LLM
calls until Phase 5 gives the observations a reader. The harness needs a
way to turn it on: a `--daemon-set observations.enabled=true` option on
`run_all.py`, merged into `IsolatedDaemon.overrides` and recorded in result
provenance like the existing overrides.

## 8. Cost

Measured from R20: about 500 turns per LongMemEval `s` question, and about
50 per DMR question.

| | LLM calls | At 10-20 s per call (8B, local) |
|---|---|---|
| DMR question | about 3 | about 0.5-1 min |
| LongMemEval `s` question | about 25 | about 4-8 min |
| LoCoMo-10 conversation (about 420 turns) | about 21 | about 3-7 min |

This is added ingest time, not answer time. It is significant for LME `s`,
already the slowest run. The pattern route alone costs milliseconds.
Measurement runs can compare `llm_enabled = false` with `true` to see
whether the LLM route earns its cost.

## 9. Measurement (the Phase 3 gate, from the card)

**Diagnostic.** `campy-benchmarks/diag_observations.py <store>` dumps every
Observation with its quote and source turn, plus counts:
- per predicate, per method, resolved vs unresolved;
- the LLM drop reasons.

It also writes a CSV for labelling, with columns `correct_subject`,
`correct_predicate`, `correct_object`, `correct_time` and `grounded`.

**Run.** LoCoMo-10 (60 questions, 1 conversation) and DMR (50) with
`--turn-metadata fields --keep-store --daemon-set observations.enabled=true`,
on the Phase 3 commit. Then run the diagnostic on the stores.

**Labelling.** A random 50 observations, stratified by method, labelled by
hand. That's me plus a second pass by you or the local agent.

**Gate:**
- precision >= 0.85 on subject, predicate and object;
- grounded = 1.00 by construction (any 0 is a bug);
- LLM drop rate reported;
- accuracy and evidence recall unchanged from R22 within run-to-run range,
  since no reader changed.

If precision misses 0.85, Phase 4 does not start. The fix is in the
patterns or the prompt.

## 10. Proposal: stop two noise sources Phase 0 found (separate, small, can go first)

R20a's audit, on 50 DMR stores:

1. **1,784 of 2,047 Concepts (87%) have no gist class.**
   - The likely source is `_ensure_concept_exists` (B32). It creates a bare
     Concept for every relation endpoint that isn't an NER entity, with no
     gist, schema type or confidence gate.
   - Verify by counting Concepts created by `create_minimal_concept` on a
     kept store.
   - Fix: store the relation only when both endpoints are already Concepts
     that cleared Step 4.
2. **The Step 3b LLM writes engineering relations on chat:**
   - 943 ALTERNATIVE_TO and 233 CHOSEN_OVER edges, e.g. "Mustang" ->
     "my car".
   - Fix: gate Step 3b on a decision or comparison cue in the sentence
     ("instead of", "rather than", "over", "chose", "switched", "vs",
     "alternative", "replace"). This is the same idea as the B471 gate.

Both reduce noise that Phase 5's retrieval would otherwise traverse. I
propose filing them as **B473** and doing them before or alongside Phase 3.
They are small, measurable on the same audit, and independent of
Observations.

## 11. Delivery: four PRs, each green and mergeable alone

| PR | Content | Behaviour change |
|---|---|---|
| 3a | Schema (table, edges, migrations, classification, fixture, docs), write API with all validation, queries, tests | none (no producer) |
| 3b | Observation worker (daemon task, queue, batching, `consolidation_pending`), pattern route, config (disabled), harness `--daemon-set` | none unless enabled |
| 3c | LLM route + validation + drop metrics | none unless enabled |
| 3d | `diag_observations.py`, R23 measurement run, labelled precision in the card | none |

**Tests** (each PR's own, plus the card's acceptance list):
- **Grounding:** a draft whose quote isn't in the message is rejected, and
  so is one with an unknown predicate or a low confidence.
- **Offsets:** they are recomputed from the match.
- **Duplicates:** a duplicate adds an `EVIDENCED_BY` edge, not a row.
- **Worker:**
  - batches flush by size and by idle;
  - `consolidation_pending` counts the observation backlog;
  - a bad batch is skipped;
  - assistant turns are not queued.
- **Pattern route:** a fixture of about 40 sentences with expected drafts,
  including negation, hypotheticals, "we decided" skipped, and two people
  named Sam.
- **LLM route:** a fake model that paraphrases is dropped and counted; one
  that quotes is written; invented predicates are rejected.
- **Time:** the absolute-date table.
- **Deletion:** archiving a Message archives the Observations whose only
  evidence it was. This is the card's privacy item, needed before Phase 5
  exposes them.

## 12. Decisions needed from you

1. **Worker or sweep.** I recommend the dedicated worker (section 2).
2. **Ship disabled.** I recommend `enabled = false` until Phase 5 gives
   observations a reader.
3. **Assistant turns excluded** from evidence in Phase 3. I recommend yes;
   B471 covers that need.
4. **B473** (the two noise sources in section 10) as a separate small card.
   I recommend yes, done first.
5. **Observation table, not FactEntity** (the card's open question 5). I
   recommend a new table. `FactEntity` is for externally owned facts
   (`authority = projected`), and observations are Campy-extracted claims.
