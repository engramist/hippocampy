# Entity Candidate Generation: Re-evaluating the spaCy Step

**Date:** 2026-09-05
**Status:** Analysis complete; recommendation pending measurement (B401)
**Related:** B387 (measured and rejected), B400 (drop torch), B401 (measurement), B279, B304/B381

---

## Why this document exists

The B387 work started from the question *"how do we remove PyTorch?"* and produced a
measured answer: an ONNX replacement agreed with spaCy at **F1 0.534**, far below the
≥95% bar. The obvious next move was to find a better NER model.

That would have been the wrong move, and the reason is worth writing down: **we were
comparing two candidate generators without first asking whether candidate generation
is where the value is.** This document records that analysis so the next person does
not re-run the same experiment.

---

## 1. What job is spaCy actually doing?

Traced through `campy/brain/temporal_lobe/loop/orchestrator.py` (Steps 1 → 3b):

| spaCy produces | What happens to it |
|---|---|
| **entity spans** | **Load-bearing.** `if not entities: return summary` — no spans means the turn writes nothing to the graph. spaCy is a hard gate on the entire Loop. |
| **labels** (`PERSON`/`ORG`/`GPE`/…) | **Discarded.** `classify_concept()` (embeddings + centroids + LLM escalation) computes `gist_class` independently. The spaCy label survives only as a weak secondary hint to `route_to_schema_org()`. |
| **dependency-parse relations** (Step 1b) | **Backstopped.** Step 3b calls `extract_semantic_relations()` via LLM for any entity pair Step 1b did not cover. |

**The job is candidate span generation.** Nothing more. The pipeline that consumes
spaCy's semantic output already distrusts it enough to recompute it.

### The cost of that job

Measured on this machine, warm (model loaded *and invoked*, which is what a running
daemon actually holds — see §5 on methodology):

| | RSS |
|---|---|
| baseline Python | 14.5 MB |
| + spaCy loaded and invoked | **541.0 MB** |
| + fastembed loaded and invoked | **818.6 MB** |
| spaCy with `torch` import blocked | **386.9 MB** |

`torch` accounts for ~154 MB of resident memory and 436 MB on disk, and is **never
used for computation** — `thinc`'s backend is `NumpyOps` and the `en_core_web_md`
pipeline is entirely CNN-based (`tok2vec`, `tagger`, `parser`, `attribute_ruler`,
`lemmatizer`, `ner`). It is an unused optional backend.

### The semantic mismatch, admitted in the source

From `step1_ner.py`'s own docstring:

> *"spaCy NER misses most software/tech terms (PostgreSQL, MySQL, React, etc.) since
> they aren't people, places, or organizations. Noun chunks catch them."*

The expensive component — statistical NER trained on newswire to find
PERSON/ORG/GPE/MISC — largely *misses* on software-engineering conversation, and a
heuristic fallback (`doc.noun_chunks`) carries the domain load. Observed live:

```
"ARC-AGI-3 requires ACTION1."  →  [('ARC-AGI-3', 'ORG'), ('ACTION1', 'ORG')]
```

The labels are wrong, known to be wrong, and thrown away. Only the spans matter.

---

## 2. The finding: recognition without linking

`campy/brain/hippocampus/schema.py` already defines a **SKOS-style lexical layer**:

```
Label                        (node type)
HAS_PREF_LABEL     FROM Concept, Decision, Constraint, Requirement, ActionItem TO Label
HAS_ALT_LABEL      (same)
HAS_HIDDEN_LABEL   (same)
```

This is a curated, continuously growing gazetteer of every entity the system has ever
committed to, complete with aliases and a hidden-label channel for terms that should
match but never display.

**Step 1 never consults it.** `step1_ner.py` contains no `db`, no `gateway`, no
`MATCH` — zero graph access. Every turn, Campy re-derives "what counts as an entity"
from generic English grammar while ignoring the domain vocabulary it has spent its
entire operational life accumulating.

### Why this is the wrong shape for a knowledge graph

Two distinct problems are usually conflated:

- **Entity recognition** — locate spans in text. Generic, commodity, model-shaped.
- **Entity linking / resolution** — does this mention denote existing node `c_123`?
  This is the expensive, valuable problem, and it is the one where *possessing a
  graph* is an actual advantage.

Campy currently spends a heavyweight generic model on the commodity half, and defers
the valuable half to downstream additive matching on embedding similarity.

**The F1 0.534 result is a symptom of this framing, not a finding about ONNX.** It
measures agreement between two candidate generators. It cannot say which is *correct*,
because neither was scored against labelled ground truth — spaCy is the incumbent, not
truth. A "better NER model" answers a question that may not matter.

---

## 3. Proposed shape: graph-first, model-last

Invert the cascade so domain knowledge runs first and models are the backstop:

1. **Gazetteer match against the `Label` layer.** Aho-Corasick over pref + alt labels.
   Deterministic, near-zero memory, and it **resolves identity in the same pass** — a
   hit returns a node id, not merely a span. Strengthens with every turn ingested.
2. **Domain lexical rules** for what spaCy provably misses and what is trivially
   regular: card IDs (`B387`), file paths, CamelCase / `snake_case` identifiers,
   backticked code, PR references. High precision, no model.
3. **LLM extraction for the residue.** Already present at Step 3b for relations;
   extend to spans when tiers 1–2 return thin results.
4. **A small NER model only if** tiers 1–3 leave a measured gap.

### Benefits beyond memory

- **Identity consistency.** `Kùzu` / `kuzu` / `KuzuDB` collapse to one node through
  alt-labels, instead of three spans reconciled later by cosine similarity.
- **Determinism.** The same string resolves the same way across turns, rather than
  depending on whether a statistical model fired.
- **Explainability.** Patent Claim 2 ("Shape-First" ontological grounding) gains a
  deterministic, inspectable basis.
- **It compounds.** The gazetteer improves as the graph grows. A frozen 2020 CoNLL
  model never does.

### Honest risks

- **Cold start.** An empty graph has no gazetteer; tiers 2–3 must carry early turns.
  Real, but self-limiting.
- **Supernode labels.** A very common label (`"test"`, `"the API"`) would match
  everywhere. `HAS_HIDDEN_LABEL` plus a stop-list exists for exactly this, but it must
  be designed, not assumed.
- **Cache semantics.** The label index is an in-memory read-through cache over the
  graph. Permitted under the no-shadow-stores rule (`CLAUDE.md`), but it must be
  explicitly read-through, never authoritative.
- **Scope.** This is a materially larger change than removing `torch`. It must not
  block that free win.

---

## 4. What to measure before building anything (B401)

Three numbers decide the design, and none require writing the system. Replay the
existing graph:

1. **What fraction of spaCy-proposed spans already exist as a `Label` in the graph?**
   High → the gazetteer alone covers most live traffic, and tier 1 is sufficient.
2. **What fraction of committed `Concept` nodes originated from NER versus the
   `noun_chunks` fallback?** The docstring implies the fallback dominates. If so, the
   statistical model is carrying almost none of the load it costs 154 MB to hold.
3. **What fraction of Step 1b relations survive filtering, versus being superseded by
   Step 3b's LLM extraction?** If low, then Step 1b — and the dependency parse, which
   is precisely what made an ONNX replacement hard — is not earning its place.

### Decision rule, stated in advance

- (1) high **and** (3) low → **delete the spaCy step**; link against the graph.
- (1) high, (3) high → keep a parser, but demote NER behind the gazetteer.
- (1) low → the gazetteer is not yet dense enough; revisit after more ingestion, and
  keep spaCy in the meantime.

Committing to the rule before seeing the numbers is deliberate — it prevents fitting
the interpretation to whatever comes back.

---

## 5. Measurement methodology (applies to all future memory claims)

The `<80 MB` target that motivated B384 was **import-time RSS only**. That number does
not describe a running daemon: `fastembed`'s model is lazily loaded, and calling
`.embed()` alone reaches ~266–277 MB.

**All future memory figures must be reported warm — after the model is actually
invoked — and must state at which stage they were taken.** Record cold-import and warm
figures separately, per component, so a future reader can tell which part of the stack
a number belongs to and re-evaluate one piece as tooling changes.

`<80 MB` warm is not achievable while ONNX embeddings run in-process. That target
should be restated against the measured 818.6 MB warm baseline rather than carried
forward.

---

## 6. Immediate consequence

None of the above changes the near-term move: **drop `torch`, keep spaCy** (B400).
It is free, carries zero accuracy risk (identical model, identical output), and
unblocks the memory work today.

What it changes is what comes *after*: the follow-up is B401's measurement, not a
hunt for a better NER model.
