# save_gate — B462 save-decision baseline

Measures how well the Loop's Step 4 gate decides what gets saved to the graph,
and as what (Decision, Constraint, Requirement, ActionItem, or nothing).

## Files

- `gold.yaml` — ~150 statements, each labeled with one category from
  `campy/data/artifact_categories.yaml` and tagged with the failure mode it
  probes (`hedged`, `casual_rule`, `no_keyword`, ...). **Author-written and
  author-labeled; review and extend it.** Real (redacted) session turns would
  be a better test set than anything written for the purpose.
- `run_baseline.py` — the harness.

## Running

```bash
# No models needed: Step 4's keyword layer only.
.venv/bin/python -m benchmarks.save_gate.run_baseline --mode signals

# Real Steps 1–4 (spaCy en_core_web_md + the embedding model, no LLM).
.venv/bin/python -m benchmarks.save_gate.run_baseline --mode full --json save_gate_full.json
```

`full` mode runs the same functions `run_loop` calls (`extract_entities`,
`classify_concept` with no LLM client, `route_to_schema_org`,
`classify_artifact`, `apply_salience_rescue`), with gist centroids
bootstrapped from `GistSeedExamples.md` (a fresh install). It does not run
Steps 5–7, so "reified" means "would be reified on an empty graph".

## Metrics (full mode)

- **reified-type accuracy** — what ends up as a confirmed artifact (confidence
  ≥ `HARD_LOCK`) vs. the gold label, counting "nothing reified" as `none`.
- **false-save rate** — gold `none` statements that get reified.
- **false-store rate** — gold `none` statements that leave any node (tentative
  or reified).
- **missed-save rate** — gold artifact statements that leave nothing.
- **reliability** — for stored items, Step 4 confidence bins vs. the fraction
  whose type is right. If confidence were a probability, accuracy would track
  mean confidence per bin.
