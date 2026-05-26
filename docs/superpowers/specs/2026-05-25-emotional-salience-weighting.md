# Emotional Salience Weighting ("The Amygdala")

## Context

Campy's Gated Consolidation Loop treats all text equally during encoding. A user saying "NO! I told you three times not to do that!" produces the same pathway_strength as "ok, sounds good." In human neuroscience, the amygdala tags memories with emotional intensity — pain burns memories into long-term storage permanently; boring information evaporates. Campy needs the same mechanism to solve the recall prioritization problem.

**Problem:** High-emotion memories (frustration, excitement, urgency) have the same pathway_strength as neutral ones. During recall, emotionally important context competes equally with background noise for limited context window space.

**Solution:** Add a 7th Cocktail Party sense ("Emotion") to Step 4 of the GCL. Emotional language detected via regex boosts pathway_strength at encoding time, making high-salience memories more durable and higher-ranked in recall.

## Design

### Detection: Three Signal Groups

Same regex pattern-matching architecture as the existing 6 senses in `step4_pattern.py`. Three groups, scored by the existing `_match_signals()` helper:

**Frustration signals** (avoidance/correction — highest weight):

```python
_FRUSTRATION_SIGNALS = [
    r"\bi told you\b", r"\bhow many times\b", r"\bstop doing\b",
    r"\bwrong again\b", r"\bnot what i (?:asked|wanted|meant)\b",
    r"\bthis is (?:broken|terrible|awful)\b", r"\bugh\b",
    r"\bdamn\b", r"\bwhy (?:does|is) (?:it|this)\b",
    r"\bso frustrat", r"\bi(?:'m| am) (?:annoyed|frustrated|angry)\b",
    r"\bfor the (?:third|fourth|fifth|last) time\b",
    r"\bno[,!]+ no\b", r"\bstop[!]+\b",
]
```

**Excitement signals** (core interest/flow):

```python
_EXCITEMENT_SIGNALS = [
    r"\byes[!]+", r"\bexactly[!]+", r"\bbrilliant\b",
    r"\blove (?:it|this|that)\b", r"\bamazing\b",
    r"\bthis is (?:great|awesome|incredible|fantastic)\b",
    r"\bhell yeah\b", r"\blet(?:'s| us) go\b",
    r"\bi(?:'m| am) (?:excited|pumped|stoked)\b",
]
```

**Urgency signals** (temporal pressure):

```python
_URGENCY_SIGNALS = [
    r"\basap\b", r"\bneed this (?:now|today|immediately)\b",
    r"\bcritical\b", r"\bblocking\b", r"\bemergency\b",
    r"\bdeadline\b", r"\burgent\b", r"\btime.?sensitive\b",
    r"\bcan(?:'t| not) wait\b", r"\bdrop everything\b",
]
```

The existing `_SUCCESS_SIGNALS` and `_FAILURE_SIGNALS` (from `infer_outcome_valence()`) feed into the salience score as an additional input — no duplication.

### Scoring: Single Numeric Multiplier

All emotional signals contribute to one `salience_multiplier` in the range [1.0, 1.6]:

```python
def compute_salience_multiplier(text: str) -> float:
    frustration_hits = _match_signals(text, _FRUSTRATION_SIGNALS)
    excitement_hits = _match_signals(text, _EXCITEMENT_SIGNALS)
    urgency_hits = _match_signals(text, _URGENCY_SIGNALS)

    valence = infer_outcome_valence(text)
    outcome_boost = 0.5 if valence is not None else 0.0

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

Frustration weighs most (1.0 per hit) because negative emotional memories are encoded more strongly than positive ones — the amygdala analogy. Excitement (0.7) and urgency (0.8) contribute but don't dominate.

Examples:
- Neutral text → 1.0x (no change)
- 1 frustration signal → 1.15x
- 2 frustration + 1 urgency → 1.42x
- Heavy emotional language (3+ signals) → caps at 1.6x

### Integration: Two Application Points

Both in `mcp_engine/loop/orchestrator.py`:

**1. Confidence rescue ("amygdala burn-in"):**

After `classify_artifact()` returns confidence but before the noise floor gate. Unlike entity-scoped signal matching (which uses `_entity_sentence()`), salience runs against the **full message text** — emotional cues often appear outside entity-local sentences ("Ugh, this whole approach is wrong" applies globally, not to one entity):

```python
salience = compute_salience_multiplier(full_message_text)

if confidence < NOISE_FLOOR and confidence >= 0.45 and salience >= 1.3:
    confidence = NOISE_FLOOR + 0.02  # 0.62
    confidence_low = True
```

Content in the 0.45–0.60 dead zone with strong emotional signals gets rescued above the noise floor. Below 0.45 stays noise — emotion alone can't create memories from nothing. The rescued node enters as `confidence_low=True` (tentative), eligible for normal re-scoring.

**2. Pathway strength boost:**

When writing nodes to Kuzu, initial pathway_strength gets the multiplier:

```python
initial_pathway_strength = confidence * salience
```

A concept at 0.75 confidence with 1.4x salience starts at pathway_strength 1.05 instead of 0.75. More durable against synaptic pruning, ranks higher in recall.

### What Doesn't Change

- **ASSISTANT_CAP (0.85):** Assistant-originated content still can't cross HARD_LOCK regardless of salience
- **Existing 6 senses:** Decision, Constraint, Requirement, Action, Plan, Outcome continue working exactly as before
- **Recall queries:** `compile_context` and `current_truth` already sort by `pathway_strength * confidence` — boosted nodes rank higher automatically
- **Graph schema:** No new node types, no new properties. Writes into existing `confidence` and `pathway_strength` fields
- **No new dependencies:** Pure regex, same `re` module already imported

### Graph Modeling Rationale

Per graph-solutions anti-pattern #4 ("Do not create node explosions for simple scalar facts"), emotional salience is a **property computation** on existing nodes, not a new node type. The hot query ("which memories rank highest for recall?") already sorts by `pathway_strength` — salience is a multiplier on that existing axis, not a separate one. This follows the access-pattern-driven modeling rule: design from the hot queries backward.

## Implementation

### Files to modify (2)

| File | Change |
|---|---|
| `mcp_engine/loop/step4_pattern.py` | Add 3 signal lists, add `compute_salience_multiplier()` function (~40 lines) |
| `mcp_engine/loop/orchestrator.py` | Call `compute_salience_multiplier()` after Step 4, apply confidence rescue, apply pathway_strength multiplier (~15 lines across 2 insertion points) |

### No new files

All changes are to existing GCL modules. No schema migration, no new dependencies.

### Testing

| Test | Expected |
|---|---|
| `compute_salience_multiplier("ok sounds good")` | Returns 1.0 |
| `compute_salience_multiplier("I told you not to do that!")` | Returns > 1.0 |
| `compute_salience_multiplier("NO! Stop doing that! I told you three times!")` | Returns close to 1.6 (capped) |
| Confidence rescue: confidence=0.55, salience=1.4 | Confidence rescued to 0.62 |
| Confidence rescue: confidence=0.40, salience=1.4 | Still below noise floor (not rescued) |
| Confidence rescue: confidence=0.55, salience=1.1 | Still below noise floor (salience < 1.3) |
| Full pipeline: frustrated message vs neutral message | Frustrated message node has higher pathway_strength |
| ASSISTANT_CAP: assistant turn with frustration language | Confidence still capped at 0.85 |

## IP Significance

This adds the **Amygdala** to Campy's biomimetic architecture. The existing system models Hebbian learning (fire-together-wire-together), synaptic pruning (Ebbinghaus decay), the hippocampus (quest routing), and the cocktail party effect (selective attention). Emotional salience weighting adds the missing piece: **emotional intensity as a memory encoding multiplier**, directly analogous to how the human amygdala modulates hippocampal memory consolidation based on emotional arousal.

## Implementation Status

| Step | Status | Commit |
|---|---|---|
| Add signal lists and compute_salience_multiplier | Complete | `280e2a68` |
| Wire into orchestrator (rescue + boost) | Complete | `d44aca59` |
| Update docs and summary counter | Complete | — |
