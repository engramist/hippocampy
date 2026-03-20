# B-Model-Eval — Benchmark Small LLMs for Low-Resource Hardware

## Overview

The Brain currently requires `llama3.1:8b` (~5GB RAM). Target deployment includes an older Windows machine with 8-16GB RAM and no dedicated GPU. This model may not load at all on that hardware.

The Brain uses the LLM for exactly 3 tasks — all structured JSON classification, not open-ended generation:
1. **Step 2 System 2** — gist class disambiguation (`{"class": "...", "confidence": N}`)
2. **Step 3b** — relation extraction with type context (`{"head": "...", "relation_type": "...", "tail": "...", "confidence": N}`)
3. **Step 6** — contradiction arbitration (`{"classification": "additive|contradiction|uncertain", "rationale": "...", "referenced_index": N}`)

**Goal:** Find the smallest model that reliably produces valid JSON for these 3 tasks. Create a benchmark script, run it against candidate models, and update `sidequests.toml` with the recommended default.

## Candidate Models

| Model | Params | Q4 Size | RAM Needed | Ollama Name |
|-------|--------|---------|------------|-------------|
| **Qwen2.5 3B** | 3.1B | ~1.9GB | ~3-4GB | `qwen2.5:3b` |
| **Llama 3.2 3B** | 3.2B | ~2.0GB | ~3-4GB | `llama3.2:3b` |
| **Qwen2.5 1.5B** | 1.5B | ~1.0GB | ~2-3GB | `qwen2.5:1.5b` |
| **Phi-3.5 Mini** | 3.8B | ~2.3GB | ~4-5GB | `phi3.5` |
| llama3.1:8b (baseline) | 8B | ~4.7GB | ~6-8GB | `llama3.1:8b` |

## Files to Read First

| File | Why |
|------|-----|
| `mcp_engine/loop/step2_gist.py` | Exact Step 2 System 2 prompt and expected JSON schema |
| `mcp_engine/loop/step3b_relations.py` | Exact Step 3b prompt and expected JSON schema |
| `mcp_engine/loop/step6_arbitration.py` | Exact Step 6 prompt and expected JSON schema |
| `mcp_engine/llm/provider.py` | LLM client interface — how we call Ollama |
| `InvertorsDocs/GistSeedExamples.md` | Source of test sentences for Step 2 benchmarks |

## Implementation

### Phase 1: Create benchmark script

**File: `benchmarks/model_eval.py`** (NEW)

This is a standalone script, not a test. It calls Ollama directly via the OpenAI-compatible API.

```python
"""
B-Model-Eval — Benchmark small LLMs for SideQuests Brain.

Usage:
    python benchmarks/model_eval.py                    # run all models
    python benchmarks/model_eval.py qwen2.5:3b         # run one model
    python benchmarks/model_eval.py --pull              # pull all models first

Requires: Ollama running locally (http://localhost:11434)
"""

import json
import time
import sys
import argparse
from openai import OpenAI

OLLAMA_BASE = "http://localhost:11434/v1"
MODELS = ["qwen2.5:3b", "llama3.2:3b", "qwen2.5:1.5b", "phi3.5", "llama3.1:8b"]

# -----------------------------------------------------------------------
# Test cases — derived from actual pipeline prompts
# -----------------------------------------------------------------------

# Step 2: gist classification
# Each tuple: (concept_text, expected_class)
STEP2_CASES = [
    # Dev domain
    ("We must never store API keys in source code", "Restriction"),
    ("We plan to add the Codex adapter in milestone 8", "PlannedEvent"),
    ("We're using Kùzu as the embedded graph database", "PhysicalThing"),
    ("The noise floor is set at 60% confidence", "Magnitude"),
    ("A MainQuest is a high-level project goal", "Category"),
    ("DJ is the lead developer", "Agent"),
    ("The schema was initialized at M1", "Event"),
    # Wellness domain
    ("Clients must complete an intake form before coaching", "Restriction"),
    ("I'm launching a 6-week wellness reset in April", "PlannedEvent"),
    ("We use Mindbody to manage coaching bookings", "PhysicalThing"),
    ("Client retention improved from 60% to 78%", "Magnitude"),
    ("Group coaching is a lower-cost tier", "Category"),
    ("My nutrition coach handles meal planning", "Agent"),
    ("Three clients completed the 12-week program", "Event"),
    # Consumer life domain
    ("Rent must be paid by the first of every month", "Restriction"),
    ("The car needs an oil change on Friday morning", "PlannedEvent"),
    ("The spare house keys are in the ceramic bowl by the door", "PhysicalThing"),
    ("The round-trip flight cost exactly four hundred dollars", "Magnitude"),
    ("A deductible is the amount you pay before insurance kicks in", "Category"),
    ("The mechanic recommended replacing the brake pads", "Agent"),
    ("The power went out for three hours during the storm", "Event"),
    # Marketing domain
    ("Ad spend must never exceed the approved monthly budget", "Restriction"),
    ("We're launching the Black Friday campaign on Meta", "PlannedEvent"),
    ("Google Analytics 4 tracks website conversion events", "PhysicalThing"),
    ("Our Meta ad cost per lead dropped to $6.50", "Magnitude"),
    ("A lookalike audience targets users similar to your customers", "Category"),
    ("Meta's ad review team approves campaigns within 24 hours", "Agent"),
    ("Google Analytics detected a 40% traffic spike", "Event"),
]

GIST_DESCRIPTIONS = {
    "Restriction":   "rules, limits, constraints, requirements, policies — things that govern behavior",
    "PlannedEvent":  "intended future actions, scheduled work, next steps, goals to accomplish",
    "PhysicalThing": "tangible objects, software artifacts, systems, files, tools, infrastructure",
    "Magnitude":     "numbers, measures, quantities, thresholds, percentages, durations, sizes",
    "Category":      "labels, types, classifications, definitions, taxonomies, roles",
    "Agent":         "people, teams, organizations, systems, or processes acting with intent",
    "Event":         "things that happened, are happening, or were triggered — occurrences",
}

# Step 3b: relation extraction
# Each tuple: (entities_with_types, sentence, expected_relation_type_or_null)
STEP3B_CASES = [
    (
        [{"text": "Kùzu", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
         {"text": "ChromaDB", "gist_class": "PhysicalThing", "schema_org_type": "Product"}],
        "We chose Kùzu over ChromaDB for the embedded database.",
        "CHOSEN_OVER"
    ),
    (
        [{"text": "FastAPI", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
         {"text": "REST API", "gist_class": "PhysicalThing", "schema_org_type": "Product"}],
        "FastAPI implements the REST API for the control panel.",
        "IMPLEMENTS"
    ),
    (
        [{"text": "Stripe", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
         {"text": "Square", "gist_class": "PhysicalThing", "schema_org_type": "Product"}],
        "We could use either Stripe or Square for payment processing.",
        "ALTERNATIVE_TO"
    ),
    (
        [{"text": "Mindbody", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
         {"text": "Zoom", "gist_class": "PhysicalThing", "schema_org_type": "Product"}],
        "We use Mindbody for bookings and Zoom for video sessions.",
        None  # no clear semantic relation — co-occurrence only
    ),
    (
        [{"text": "Google Analytics 4", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
         {"text": "Universal Analytics", "gist_class": "PhysicalThing", "schema_org_type": "Product"}],
        "Google Analytics 4 replaces Universal Analytics completely.",
        "CHOSEN_OVER"  # or REPLACES — but Step 3b only has CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO
    ),
]

# Step 6: contradiction arbitration
# Each tuple: (new_concept, existing_candidates, sentence, expected_classification)
STEP6_CASES = [
    (
        {"text": "We decided to use PostgreSQL", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
        [{"text_raw": "We decided to use PostgreSQL for the database", "similarity": 0.91, "pathway_strength": 0.8, "concept_id": "c1"}],
        "We decided to use PostgreSQL as our primary database.",
        "additive"
    ),
    (
        {"text": "We're switching to MySQL", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
        [{"text_raw": "We decided to use PostgreSQL for the database", "similarity": 0.82, "pathway_strength": 0.8, "concept_id": "c1"}],
        "We're switching to MySQL instead of PostgreSQL.",
        "contradiction"
    ),
    (
        {"text": "Client sessions should be 60 minutes", "gist_class": "Restriction", "schema_org_type": "Demand"},
        [{"text_raw": "Coaching sessions are 45 minutes each", "similarity": 0.78, "pathway_strength": 0.7, "concept_id": "c2"}],
        "Going forward, client sessions should be 60 minutes instead of 45.",
        "contradiction"
    ),
    (
        {"text": "The monthly ad budget is $2000", "gist_class": "Magnitude", "schema_org_type": "QuantitativeValue"},
        [{"text_raw": "We spend about $2000 per month on ads", "similarity": 0.89, "pathway_strength": 0.6, "concept_id": "c3"}],
        "The monthly ad budget is $2000 across all campaigns.",
        "additive"
    ),
    (
        {"text": "The new office is downtown", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
        [{"text_raw": "Our office is in the suburbs near the mall", "similarity": 0.76, "pathway_strength": 0.5, "concept_id": "c4"}],
        "We moved — the new office is downtown now.",
        "contradiction"
    ),
]


# -----------------------------------------------------------------------
# Prompt builders — match the exact production prompts
# -----------------------------------------------------------------------

def build_step2_prompt(concept_text):
    """Exact prompt from step2_gist.py:_classify_with_llm()"""
    class_list = "\n".join(
        f"- {name}: {desc}" for name, desc in GIST_DESCRIPTIONS.items()
    )
    return (
        f'Classify this concept into exactly one gist ontology class.\n\n'
        f'Concept: "{concept_text}"\n\n'
        f'Classes:\n{class_list}\n\n'
        f'Respond with JSON only, no explanation:\n'
        f'{{"class": "<class_name>", "confidence": <0.0-1.0>}}'
    )


def build_step3b_prompt(entities, sentence):
    """Exact prompt from step3b_relations.py:extract_semantic_relations()"""
    entity_lines = "\n".join(
        f"  Entity {i+1}: {e['text']} "
        f"(gist:{e.get('gist_class', '?')} / schema:{e.get('schema_org_type', '?')})"
        for i, e in enumerate(entities[:4])
    )
    relation_list = "CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO"
    return (
        f"Given these typed entities and the sentence they appear in, "
        f"identify if there is a semantic relationship between any two of them.\n\n"
        f"Entities:\n{entity_lines}\n\n"
        f"Sentence: \"{sentence}\"\n\n"
        f"If a relationship exists, choose from: {relation_list}\n"
        f"If no clear relationship exists, return null.\n\n"
        f"Respond with JSON only:\n"
        f'{{"head": "<entity text>", "relation_type": "<TYPE>", '
        f'"tail": "<entity text>", "confidence": <0.0-1.0>}}\n'
        f"or: null"
    )


def build_step6_prompt(new_concept, candidates, sentence):
    """Exact prompt from step6_arbitration.py:arbitrate()"""
    top = candidates[:3]
    candidate_lines = "\n".join(
        f"  [{i+1}] \"{c['text_raw']}\" "
        f"(similarity: {c['similarity']:.2f}, strength: {c['pathway_strength']:.2f})"
        for i, c in enumerate(top)
    )
    return (
        f"A new concept arrived in a conversation. Determine if it adds to, "
        f"contradicts, or is ambiguously related to existing knowledge.\n\n"
        f"New concept: \"{new_concept.get('text', '')}\" "
        f"(type: {new_concept.get('gist_class', '?')} / "
        f"{new_concept.get('schema_org_type', '?')})\n\n"
        f"Context sentence: \"{sentence}\"\n\n"
        f"Existing similar concepts:\n{candidate_lines}\n\n"
        f"Choose exactly one classification:\n"
        f"  additive      — the new concept reinforces or restates an existing one\n"
        f"  contradiction — the new concept directly conflicts with an existing one\n"
        f"  uncertain     — not enough evidence to decide\n\n"
        f"Respond with JSON only:\n"
        f'{{\"classification\": \"<additive|contradiction|uncertain>\", '
        f'\"rationale\": \"<one sentence>\", '
        f'\"referenced_index\": <1-{len(top)} or null>}}'
    )


# -----------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------

import re


def call_model(client, model, prompt, use_json_mode=True):
    """Call Ollama via OpenAI-compatible API. Returns (parsed_result, latency_ms, raw_text)."""
    start = time.time()
    try:
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content.strip()
        latency = (time.time() - start) * 1000

        # Parse JSON — try raw first, then extract from markdown fences
        raw_clean = raw.strip().strip("```json").strip("```").strip()
        if raw_clean.lower() == "null":
            return None, latency, raw

        # Try to extract first JSON object
        match = re.search(r'\{[^}]+\}', raw_clean, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return result, latency, raw
        return None, latency, raw

    except Exception as e:
        latency = (time.time() - start) * 1000
        return None, latency, str(e)


def run_step2_eval(client, model):
    """Evaluate Step 2 (gist classification). Returns (correct, total, avg_latency_ms, json_failures)."""
    correct = 0
    total = len(STEP2_CASES)
    latencies = []
    json_failures = 0
    gist_classes = list(GIST_DESCRIPTIONS.keys())

    for concept, expected in STEP2_CASES:
        prompt = build_step2_prompt(concept)
        result, lat, raw = call_model(client, model, prompt)
        latencies.append(lat)

        if result is None:
            json_failures += 1
            continue

        predicted = result.get("class", "")
        if predicted not in gist_classes:
            json_failures += 1
            continue

        if predicted == expected:
            correct += 1

    return correct, total, sum(latencies) / len(latencies) if latencies else 0, json_failures


def run_step3b_eval(client, model):
    """Evaluate Step 3b (relation extraction). Returns (correct, total, avg_latency_ms, json_failures)."""
    correct = 0
    total = len(STEP3B_CASES)
    latencies = []
    json_failures = 0

    for entities, sentence, expected in STEP3B_CASES:
        prompt = build_step3b_prompt(entities, sentence)
        result, lat, raw = call_model(client, model, prompt)
        latencies.append(lat)

        if expected is None:
            # Expected null — check model returned null or no relation
            if result is None or result.get("relation_type") is None:
                correct += 1
            continue

        if result is None:
            json_failures += 1
            continue

        predicted = result.get("relation_type", "")
        if predicted == expected:
            correct += 1

    return correct, total, sum(latencies) / len(latencies) if latencies else 0, json_failures


def run_step6_eval(client, model):
    """Evaluate Step 6 (arbitration). Returns (correct, total, avg_latency_ms, json_failures)."""
    correct = 0
    total = len(STEP6_CASES)
    latencies = []
    json_failures = 0

    for new_concept, candidates, sentence, expected in STEP6_CASES:
        prompt = build_step6_prompt(new_concept, candidates, sentence)
        result, lat, raw = call_model(client, model, prompt)
        latencies.append(lat)

        if result is None:
            json_failures += 1
            continue

        predicted = result.get("classification", "")
        if predicted not in {"additive", "contradiction", "uncertain"}:
            json_failures += 1
            continue

        if predicted == expected:
            correct += 1

    return correct, total, sum(latencies) / len(latencies) if latencies else 0, json_failures


def run_full_eval(models=None):
    """Run the full benchmark suite."""
    client = OpenAI(base_url=OLLAMA_BASE, api_key="ollama")
    if models is None:
        models = MODELS

    print("=" * 80)
    print("SideQuests Brain — Model Evaluation Benchmark")
    print("=" * 80)
    print()

    results = {}
    for model in models:
        print(f"--- {model} ---")

        s2_correct, s2_total, s2_lat, s2_jf = run_step2_eval(client, model)
        s3b_correct, s3b_total, s3b_lat, s3b_jf = run_step3b_eval(client, model)
        s6_correct, s6_total, s6_lat, s6_jf = run_step6_eval(client, model)

        total_correct = s2_correct + s3b_correct + s6_correct
        total_cases = s2_total + s3b_total + s6_total
        total_jf = s2_jf + s3b_jf + s6_jf
        avg_lat = (s2_lat + s3b_lat + s6_lat) / 3

        print(f"  Step 2 (gist class):    {s2_correct}/{s2_total} correct, {s2_jf} JSON failures, {s2_lat:.0f}ms avg")
        print(f"  Step 3b (relations):    {s3b_correct}/{s3b_total} correct, {s3b_jf} JSON failures, {s3b_lat:.0f}ms avg")
        print(f"  Step 6 (arbitration):   {s6_correct}/{s6_total} correct, {s6_jf} JSON failures, {s6_lat:.0f}ms avg")
        print(f"  TOTAL: {total_correct}/{total_cases} ({total_correct/total_cases*100:.0f}%), "
              f"{total_jf} JSON failures, {avg_lat:.0f}ms avg latency")
        print()

        results[model] = {
            "accuracy": total_correct / total_cases,
            "json_failures": total_jf,
            "avg_latency_ms": avg_lat,
            "step2": {"correct": s2_correct, "total": s2_total, "latency": s2_lat, "json_failures": s2_jf},
            "step3b": {"correct": s3b_correct, "total": s3b_total, "latency": s3b_lat, "json_failures": s3b_jf},
            "step6": {"correct": s6_correct, "total": s6_total, "latency": s6_lat, "json_failures": s6_jf},
        }

    # Summary table
    print("=" * 80)
    print(f"{'Model':<20} {'Accuracy':>10} {'JSON Fail':>10} {'Avg Latency':>12} {'Verdict':>10}")
    print("-" * 80)
    for model, r in sorted(results.items(), key=lambda x: -x[1]["accuracy"]):
        verdict = "PASS" if r["accuracy"] >= 0.80 and r["json_failures"] <= 2 else "FAIL"
        print(f"{model:<20} {r['accuracy']*100:>9.0f}% {r['json_failures']:>10} {r['avg_latency_ms']:>10.0f}ms {verdict:>10}")
    print("=" * 80)

    # Save results
    with open("benchmarks/model_eval_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to benchmarks/model_eval_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark LLMs for SideQuests Brain")
    parser.add_argument("models", nargs="*", help="Specific models to test (default: all)")
    parser.add_argument("--pull", action="store_true", help="Pull all models from Ollama first")
    args = parser.parse_args()

    if args.pull:
        import subprocess
        for m in (args.models or MODELS):
            print(f"Pulling {m}...")
            subprocess.run(["ollama", "pull", m], check=True)

    run_full_eval(args.models or None)
```

### Phase 2: Update sidequests.toml with recommendation

After running the benchmark, update `sidequests.toml` based on results:

**If Qwen2.5 3B passes (>=80% accuracy, <=2 JSON failures):**
```toml
[llm]
model = "qwen2.5:3b"    # was llama3.1:8b — switched for low-resource hardware compat
```

**If only 1.5B passes:**
```toml
[llm]
model = "qwen2.5:1.5b"
```

**Do NOT change the model in sidequests.toml until benchmark results confirm a winner.** The B-plan creates the benchmark; the human decides which model to switch to.

### Phase 3: Add model recommendation to installer

**File: `sidequests/cli/install.py`**

Find the section where the model is configured. Add hardware-aware model selection:

```python
# After detecting LLM provider choice (local/cloud):
# If local (Ollama), detect available RAM and recommend model size
import shutil
total_ram_gb = shutil.disk_usage("/").total  # placeholder — use psutil if available

# Recommend model based on RAM
if total_ram_gb <= 8:
    recommended_model = "qwen2.5:1.5b"
elif total_ram_gb <= 16:
    recommended_model = "qwen2.5:3b"
else:
    recommended_model = "llama3.1:8b"
```

**Note:** The exact RAM detection code depends on what's already in install.py. Read the file first. The logic above is illustrative — adapt to the existing code structure. Use `psutil.virtual_memory().total` if psutil is available, otherwise fall back to a simpler heuristic.

## Expected Benchmark Output

```
===================================================================
Model                Accuracy   JSON Fail  Avg Latency    Verdict
-------------------------------------------------------------------
qwen2.5:3b               89%          0        850ms       PASS
llama3.2:3b               85%          1        920ms       PASS
llama3.1:8b               92%          0       1800ms       PASS
phi3.5                    87%          0       1100ms       PASS
qwen2.5:1.5b             75%          3       450ms        FAIL
===================================================================
```

(Numbers are illustrative — actual results will vary.)

## Passing Criteria

A model PASSES the benchmark if:
- **Overall accuracy >= 80%** across all 3 steps
- **JSON failures <= 2** out of ~37 total calls
- **Step 6 accuracy >= 60%** (arbitration is the hardest task — if a model can't do this, it's not viable)

## Files to Create

| File | Description |
|------|-------------|
| `benchmarks/model_eval.py` | Standalone benchmark script |

## Files to Modify

| File | Change |
|------|--------|
| `sidequests.toml` | Update default model AFTER benchmark confirms winner |
| `sidequests/cli/install.py` | Add RAM-aware model recommendation (if feasible) |

## What NOT to Do

- Do NOT change the default model before running the benchmark
- Do NOT modify any Loop step code (step2, step3b, step6) — the prompts must be tested as-is
- Do NOT add model-specific prompt tweaks — the model must work with our existing prompts

## Verification

1. `python benchmarks/model_eval.py --pull` — pulls all candidate models and runs full benchmark
2. `python benchmarks/model_eval.py qwen2.5:3b` — quick single-model test
3. Results saved to `benchmarks/model_eval_results.json` for comparison
4. Winner model loads and runs on 8GB RAM machine without swapping
5. Existing tests still pass after sidequests.toml model change
