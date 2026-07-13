# Emotional Salience Weighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 7th Cocktail Party sense ("Emotion") to Step 4 of the GCL that detects emotional language and boosts pathway_strength at encoding time.

**Architecture:** Three regex signal groups (frustration, excitement, urgency) produce a single salience multiplier [1.0–1.6]. The multiplier applies at two points in the orchestrator: (1) confidence rescue for borderline content with strong emotional cues, (2) pathway_strength boost at node creation. No schema changes, no new dependencies.

**Tech Stack:** Python regex (already imported), existing `_match_signals()` helper, existing `infer_outcome_valence()` function.

**Spec:** `docs/superpowers/specs/2026-05-25-emotional-salience-weighting.md`

---

### Task 1: Add Emotion Signal Lists and Salience Multiplier to step4_pattern.py

**Files:**
- Modify: `mcp_engine/loop/step4_pattern.py:67` (after `_FAILURE_SIGNALS`, before `_GIST_ARTIFACT_PRIOR`)
- Modify: `mcp_engine/loop/step4_pattern.py:247` (after `infer_outcome_valence`, append new function)
- Test: `tests/test_step4_salience.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_step4_salience.py`:

```python
"""Tests for the Emotion sense (7th Cocktail Party sense) in Step 4."""
import pytest
from mcp_engine.loop.step4_pattern import compute_salience_multiplier


class TestComputeSalienceMultiplier:
    """Unit tests for compute_salience_multiplier()."""

    def test_neutral_text_returns_1(self):
        assert compute_salience_multiplier("ok sounds good") == 1.0

    def test_empty_string_returns_1(self):
        assert compute_salience_multiplier("") == 1.0

    def test_none_returns_1(self):
        assert compute_salience_multiplier(None) == 1.0

    def test_single_frustration_signal(self):
        result = compute_salience_multiplier("I told you not to do that")
        assert result == pytest.approx(1.15, abs=0.01)

    def test_single_excitement_signal(self):
        result = compute_salience_multiplier("I love it")
        assert result == pytest.approx(1.105, abs=0.01)

    def test_single_urgency_signal(self):
        result = compute_salience_multiplier("we need this ASAP")
        assert result == pytest.approx(1.12, abs=0.01)

    def test_multiple_frustration_signals_stack(self):
        result = compute_salience_multiplier(
            "No no, wrong again! I told you not to do that!"
        )
        assert result > 1.15

    def test_mixed_signals_combine(self):
        result = compute_salience_multiplier(
            "I told you this is critical and needs to be done ASAP!"
        )
        # frustration (1.0) + urgency (0.8) + urgency (0.8) = 2.6 raw
        # 1.0 + 2.6 * 0.15 = 1.39
        assert result > 1.3

    def test_caps_at_1_6(self):
        result = compute_salience_multiplier(
            "NO! Stop! I told you! This is broken and terrible! "
            "Wrong again! How many times! Damn! Ugh!"
        )
        assert result == pytest.approx(1.6, abs=0.01)

    def test_outcome_valence_contributes(self):
        # "that's wrong" triggers both _FAILURE_SIGNALS (outcome valence)
        # and _FRUSTRATION_SIGNALS ("not what i wanted" overlap)
        result_with_failure = compute_salience_multiplier("that's wrong, revert it")
        result_neutral = compute_salience_multiplier("please update the config")
        assert result_with_failure > result_neutral

    def test_case_insensitive(self):
        result_lower = compute_salience_multiplier("i told you not to do that")
        result_upper = compute_salience_multiplier("I TOLD YOU NOT TO DO THAT")
        assert result_lower == result_upper
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/test_step4_salience.py -v`

Expected: FAIL — `ImportError: cannot import name 'compute_salience_multiplier'`

- [ ] **Step 3: Add the three emotion signal lists**

In `mcp_engine/loop/step4_pattern.py`, add these three signal lists after `_FAILURE_SIGNALS` (after line 67, before `_GIST_ARTIFACT_PRIOR`):

```python
# Emotion sense — 7th Cocktail Party sense (Amygdala)
# Emotional language boosts pathway_strength via salience multiplier.
_FRUSTRATION_SIGNALS = [
    r"\bi told you\b", r"\bhow many times\b", r"\bstop doing\b",
    r"\bwrong again\b", r"\bnot what i (?:asked|wanted|meant)\b",
    r"\bthis is (?:broken|terrible|awful)\b", r"\bugh\b",
    r"\bdamn\b", r"\bwhy (?:does|is) (?:it|this)\b",
    r"\bso frustrat", r"\bi(?:'m| am) (?:annoyed|frustrated|angry)\b",
    r"\bfor the (?:third|fourth|fifth|last) time\b",
    r"\bno[,!]+ no\b", r"\bstop[!]+\b",
]
_EXCITEMENT_SIGNALS = [
    r"\byes[!]+", r"\bexactly[!]+", r"\bbrilliant\b",
    r"\blove (?:it|this|that)\b", r"\bamazing\b",
    r"\bthis is (?:great|awesome|incredible|fantastic)\b",
    r"\bhell yeah\b", r"\blet(?:'s| us) go\b",
    r"\bi(?:'m| am) (?:excited|pumped|stoked)\b",
]
_URGENCY_SIGNALS = [
    r"\basap\b", r"\bneed this (?:now|today|immediately)\b",
    r"\bcritical\b", r"\bblocking\b", r"\bemergency\b",
    r"\bdeadline\b", r"\burgent\b", r"\btime.?sensitive\b",
    r"\bcan(?:'t| not) wait\b", r"\bdrop everything\b",
]
```

- [ ] **Step 4: Add the `compute_salience_multiplier()` function**

Append at the end of `mcp_engine/loop/step4_pattern.py` (after `infer_outcome_valence`):

```python
def compute_salience_multiplier(text: str) -> float:
    """
    Compute emotional salience multiplier from text signals.

    7th Cocktail Party sense — the Amygdala. Detects frustration,
    excitement, and urgency language. Returns a multiplier in [1.0, 1.6]
    that boosts pathway_strength at encoding time.

    Frustration weighs highest (1.0 per hit) because negative emotional
    memories encode more strongly than positive ones.
    """
    if not text:
        return 1.0

    frustration_hits = _match_signals(text, _FRUSTRATION_SIGNALS)
    excitement_hits = _match_signals(text, _EXCITEMENT_SIGNALS)
    urgency_hits = _match_signals(text, _URGENCY_SIGNALS)

    # Reuse existing outcome sense as additional input
    valence = infer_outcome_valence(text)
    outcome_boost = 0.5 if valence is not None else 0.0

    # Weight frustration highest (amygdala: negative > positive)
    raw_score = (
        frustration_hits * 1.0 +
        excitement_hits * 0.7 +
        urgency_hits * 0.8 +
        outcome_boost
    )

    if raw_score == 0:
        return 1.0

    return min(1.0 + (raw_score * 0.15), 1.6)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/test_step4_salience.py -v`

Expected: All 11 tests PASS.

- [ ] **Step 6: Run existing step4/orchestrator tests to check for regressions**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/test_orchestrator.py -v`

Expected: All existing tests still PASS — no behavior change yet (multiplier not wired in).

- [ ] **Step 7: Commit**

```bash
git add mcp_engine/loop/step4_pattern.py tests/test_step4_salience.py
git commit -m "feat: add Emotion sense signal lists and salience multiplier to Step 4"
```

---

### Task 2: Wire Salience into the Orchestrator

**Files:**
- Modify: `mcp_engine/loop/orchestrator.py:32` (add import)
- Modify: `mcp_engine/loop/orchestrator.py:209-223` (after Step 4 classification, before noise floor gate)
- Modify: `mcp_engine/loop/orchestrator.py:534` (pathway_strength computation in `_store_concept`)
- Test: `tests/test_step4_salience.py` (append integration tests)

- [ ] **Step 1: Write the failing tests for confidence rescue**

Append to `tests/test_step4_salience.py`:

```python
from mcp_engine.loop.step4_pattern import (
    compute_salience_multiplier,
    classify_artifact,
    NOISE_FLOOR,
)


class TestConfidenceRescue:
    """Tests for the amygdala burn-in: emotional content rescues from noise floor."""

    def test_borderline_with_high_salience_is_rescued(self):
        """Content at 0.55 confidence with strong emotion should be rescued."""
        # "Agent" gist class with no keyword signals → confidence 0.40 (noise)
        # But if salience >= 1.3, confidence should be rescued to 0.62
        result = classify_artifact(
            "I told you stop doing that with the database!",
            gist_class="Agent",
            schema_org_type="Person",
            role="user",
        )
        # Without rescue this would be noise (Agent → prior_conf 0.40, no signals)
        # The classify_artifact function itself doesn't apply rescue —
        # rescue happens in the orchestrator. This test documents the baseline.
        assert result["confidence"] == 0.0  # noise result

    def test_salience_above_rescue_threshold(self):
        """Strongly emotional text produces salience >= 1.3."""
        result = compute_salience_multiplier(
            "NO! I told you! Stop doing that! This is broken!"
        )
        assert result >= 1.3
```

- [ ] **Step 2: Run tests to verify baseline behavior**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/test_step4_salience.py::TestConfidenceRescue -v`

Expected: Both tests PASS (documenting current baseline behavior).

- [ ] **Step 3: Add the import to orchestrator.py**

In `mcp_engine/loop/orchestrator.py`, modify the existing import on line 32:

Change:
```python
from mcp_engine.loop.step4_pattern   import classify_artifact
```

To:
```python
from mcp_engine.loop.step4_pattern   import classify_artifact, compute_salience_multiplier
```

- [ ] **Step 4: Add confidence rescue after Step 4 classification**

In `mcp_engine/loop/orchestrator.py`, in the `for entity in typed_entities:` loop, after the `step4_result = classify_artifact(...)` call (line 213-219) and BEFORE the `if not step4_result["should_proceed"]:` check (line 221), insert the salience rescue logic:

```python
        # Emotion sense — 7th Cocktail Party sense (Amygdala)
        # Compute salience from full message text (emotional cues are
        # message-global, not entity-scoped like other senses).
        salience = compute_salience_multiplier(text)

        # Amygdala rescue: emotional content in the 0.45–0.60 dead zone
        # gets pulled above the noise floor. Below 0.45 stays noise —
        # emotion alone can't create memories from nothing.
        if (not step4_result["should_proceed"]
                and step4_result["confidence"] >= 0.45
                and salience >= 1.3):
            step4_result = {
                "artifact_type":  step4_result["artifact_type"] or "decision",
                "confidence":     NOISE_FLOOR + 0.02,  # 0.62
                "confidence_low": True,
                "should_proceed": True,
            }
            summary["salience_rescues"] = summary.get("salience_rescues", 0) + 1
```

Also add the `NOISE_FLOOR` import — modify the existing import on line 32 to:

```python
from mcp_engine.loop.step4_pattern   import (
    classify_artifact, compute_salience_multiplier, NOISE_FLOOR,
)
```

Wait — `NOISE_FLOOR` is already used inside `classify_artifact`, but the orchestrator doesn't currently import it. Check: actually the orchestrator doesn't reference `NOISE_FLOOR` directly — `classify_artifact` handles the gate internally and returns `should_proceed=False` for noise. But for the rescue, we need `NOISE_FLOOR` in the orchestrator. So add it to the import.

Note: the rescue checks `step4_result["confidence"] >= 0.45` — but when `classify_artifact` returns noise, it returns `confidence: 0.0` (see `_noise_result()`). So the rescue needs to re-run the raw confidence computation. Actually, looking at the code more carefully:

`classify_artifact` returns `_noise_result()` (confidence 0.0) in two cases:
1. `gist_class` is None → truly nothing to work with
2. confidence computed but fell below `NOISE_FLOOR`

For case 2, the raw confidence is lost. To rescue, we need the raw confidence. The cleanest approach: have `classify_artifact` always return the raw confidence, even for noise. Let's modify `_noise_result` and the noise gate to preserve the raw score.

Actually, simpler: add a `raw_confidence` field to the result dict. Let me revise.

- [ ] **Step 5: Modify classify_artifact to preserve raw confidence for rescue**

In `mcp_engine/loop/step4_pattern.py`, change the noise floor gate at line 157-158:

Change:
```python
    if confidence < NOISE_FLOOR:
        return _noise_result()
```

To:
```python
    if confidence < NOISE_FLOOR:
        return {
            "artifact_type":  artifact_type,
            "confidence":     confidence,  # preserve raw for salience rescue
            "confidence_low": True,
            "should_proceed": False,
        }
```

And change `_noise_result()` to only be used for the truly-no-data case (gist_class is None):

The function `_noise_result()` at line 174-180 stays unchanged — it's still used for the `gist_class is None` case at line 121-122, which returns confidence 0.0 (no data at all, not rescuable).

- [ ] **Step 6: Update the rescue condition in orchestrator.py**

Now the rescue in orchestrator.py can check the raw confidence:

```python
        # Amygdala rescue: emotional content in the 0.45–0.60 dead zone
        # gets pulled above the noise floor. Below 0.45 stays noise —
        # emotion alone can't create memories from nothing.
        if (not step4_result["should_proceed"]
                and step4_result["confidence"] >= 0.45
                and salience >= 1.3):
            step4_result = {
                "artifact_type":  step4_result["artifact_type"] or "decision",
                "confidence":     NOISE_FLOOR + 0.02,  # 0.62
                "confidence_low": True,
                "should_proceed": True,
            }
            summary["salience_rescues"] = summary.get("salience_rescues", 0) + 1
```

This works because `classify_artifact` now returns the raw confidence (e.g. 0.55) when it falls below the noise floor, instead of 0.0.

- [ ] **Step 7: Pass salience multiplier to _store_concept for pathway_strength boost**

In `mcp_engine/loop/orchestrator.py`, modify the `_store_concept` function signature at line 450:

Change:
```python
async def _store_concept(entity: dict, step4: dict, vector: list[float],
                          embedding_model: str, db, now: str,
                          anomaly_result: dict | None = None) -> str | None:
```

To:
```python
async def _store_concept(entity: dict, step4: dict, vector: list[float],
                          embedding_model: str, db, now: str,
                          anomaly_result: dict | None = None,
                          salience: float = 1.0) -> str | None:
```

Then change line 534 where `pathway_strength` is set:

Change:
```python
                "pathway_strength": max(confidence, 0.50),
```

To:
```python
                "pathway_strength": max(confidence * salience, 0.50),
```

And the dedup-hit update at line 495:

Change:
```python
                 "ps": max(confidence, 0.50), "conf": confidence}
```

To:
```python
                 "ps": max(confidence * salience, 0.50), "conf": confidence}
```

- [ ] **Step 8: Pass salience to all _store_concept call sites**

There are 3 call sites for `_store_concept` in the orchestrator (contradiction, uncertain, new-concept). Add `salience=salience` to each:

Line ~285 (contradiction branch):
```python
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now,
                    anomaly_result=anomaly_result, salience=salience,
                )
```

Line ~324 (uncertain branch):
```python
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now,
                    anomaly_result=anomaly_result, salience=salience,
                )
```

Line ~353 (new concept branch):
```python
            concept_id = await _store_concept(
                entity, step4_result, vector, embedding_model, db, now,
                anomaly_result=anomaly_result, salience=salience,
            )
```

- [ ] **Step 9: Add integration tests for orchestrator wiring**

Append to `tests/test_step4_salience.py`:

```python
import asyncio

from mcp_engine.loop.orchestrator import _store_concept


class TestPathwayStrengthBoost:
    """Tests for salience multiplier effect on pathway_strength."""

    def test_store_concept_signature_accepts_salience(self):
        """Verify _store_concept accepts salience kwarg without error."""
        import inspect
        sig = inspect.signature(_store_concept)
        assert "salience" in sig.parameters

    def test_salience_default_is_1(self):
        """Default salience should be 1.0 (no boost)."""
        import inspect
        sig = inspect.signature(_store_concept)
        assert sig.parameters["salience"].default == 1.0
```

- [ ] **Step 10: Run all tests**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/test_step4_salience.py tests/test_orchestrator.py -v`

Expected: All tests PASS, including existing orchestrator tests (no regressions).

- [ ] **Step 11: Commit**

```bash
git add mcp_engine/loop/step4_pattern.py mcp_engine/loop/orchestrator.py tests/test_step4_salience.py
git commit -m "feat: wire emotion salience into orchestrator — confidence rescue + pathway boost"
```

---

### Task 3: Add Summary Counter and Update Architecture Docs

**Files:**
- Modify: `mcp_engine/loop/orchestrator.py:78-93` (summary dict initialization)
- Modify: `docs/ARCHITECTURE.md` (Cocktail Party senses table, Step 4 description)
- Modify: `docs/superpowers/specs/2026-05-25-emotional-salience-weighting.md` (implementation status)

- [ ] **Step 1: Add salience_rescues to summary dict**

In `mcp_engine/loop/orchestrator.py`, in the `summary = {` dict initialization (around line 78), add:

```python
        "salience_rescues":  0,
```

After `"noise_count"` or any other counter.

- [ ] **Step 2: Update ARCHITECTURE.md — Cocktail Party senses table**

In `docs/ARCHITECTURE.md`, find the Cocktail Party senses table (around line 424-431) and add a new row:

```markdown
| Emotion / Salience sense | Frustration, excitement, or urgency language detected — boosts pathway_strength via salience multiplier [1.0–1.6], rescues borderline content above noise floor |
```

- [ ] **Step 3: Update ARCHITECTURE.md — Step 4 description**

In `docs/ARCHITECTURE.md`, update the Step 4 description to mention 7 senses (currently says "six cognitive senses" or similar). Add a brief note about the salience multiplier.

- [ ] **Step 4: Update the spec implementation status**

In `docs/superpowers/specs/2026-05-25-emotional-salience-weighting.md`, add an Implementation Status section at the bottom:

```markdown
## Implementation Status

| Step | Status | Commit |
|---|---|---|
| Add signal lists and compute_salience_multiplier | Complete | — |
| Wire into orchestrator (rescue + boost) | Complete | — |
| Update docs | Complete | — |
```

- [ ] **Step 5: Run full test suite**

Run: `cd ~/GitProjects/hippocampy && .venv/bin/pytest tests/ -x -q`

Expected: All tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add mcp_engine/loop/orchestrator.py docs/ARCHITECTURE.md docs/superpowers/specs/2026-05-25-emotional-salience-weighting.md
git commit -m "docs: update architecture for Emotion sense, mark spec complete"
```
