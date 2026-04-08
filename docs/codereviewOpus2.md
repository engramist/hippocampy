# ARC Agent Intelligence Review — Making the Solver Smarter

**Date:** April 3, 2026
**Reviewer:** Claude Opus 4.6
**Scope:** agents/arc3/ — focused on puzzle-solving quality, not infrastructure bugs
**Context:** Single puzzle run: 15 steps, 0 wins, 366s runtime, qwen2.5:7b, `no_progress_step_count: 15`

---

## Executive Summary

The ARC agent has impressive engineering scaffolding (hypothesis manager, solve engine, plan chunker, decision guard, graduation assessment, plateau policy) but the **actual puzzle-solving intelligence is thin**. The agent is spending its budget on exploration bookkeeping rather than reasoning about the puzzle. The submission results confirm this: 15 steps, zero progress, every step `no_progress`.

The core problem is architectural: **the agent treats ARC puzzles as navigation games** (player moves toward goal through a grid), when ARC-AGI-3 puzzles are abstract transformation puzzles requiring pattern recognition. The entire GameArchetype/ObjectRole/VictoryCondition ontology is tuned for Atari-like grid games, not ARC's actual challenge of discovering input->output transformation rules.

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Directly prevents the agent from solving puzzles it could otherwise solve |
| **HIGH** | Materially degrades solve rate or wastes most of the step budget |
| **MEDIUM** | Reduces quality or creates unnecessary confusion in the reasoning chain |
| **LOW** | Optimization or code quality that would help incrementally |

---

## Section 1: Fundamental Strategy Problems

### F1. Wrong Mental Model — ARC Is Not a Navigation Game [CRITICAL]

**Files:** `solver.py` (entire file), `prompts.py`

The entire solve engine is built around:
- **GameArchetype**: race, space, chase, displace — these are movement/video-game concepts
- **ObjectRole**: player, enemy, goal, wall, collectible, exit — Atari-style roles
- **VictoryCondition**: reach_goal, collect_all, survive, score_threshold, eliminate
- **PlanChunker**: BFS pathfinding, directional movement toward a goal position

ARC-AGI-3 puzzles require the agent to discover **abstract transformation rules** — rotations, reflections, color substitutions, pattern completions, symmetry operations, conditional fills. None of these map to "move player toward goal."

The submission results confirm this misalignment: the agent classified the puzzle as `space` archetype with `reach_goal` victory condition, identified color 0 as "player" and color 1 as "goal," then spent 15 steps trying to navigate color 0 toward color 1 — when the actual puzzle likely required discovering a grid transformation rule.

**Root cause:** The agent was designed for interactive grid-world games where you take discrete movement actions. ARC puzzles present input/output grid pairs where you must infer and apply a transformation.

**Fix:** The entire solve strategy needs to pivot from "navigate to goal" to "discover transformation rule." This is a fundamental rearchitecture:

1. **Pattern recognition phase**: Compare input grids across training examples to identify what changed and why. Look for: symmetry operations, color mappings, spatial translations, conditional rules, border/fill operations, counting patterns.

2. **Rule hypothesis generation**: Instead of VictoryCondition ("reach the goal"), generate TransformationHypotheses ("rotate 90 degrees," "fill enclosed regions," "mirror across vertical axis").

3. **Rule testing**: Apply hypothesized rules to training inputs and verify against training outputs. This is where the REPL sandbox should shine — run the transformation in Python and diff against expected output.

4. **Rule application**: Apply the confirmed rule to the test input to produce the answer.

---

### F2. The LLM Is Asked the Wrong Question [CRITICAL]

**File:** `prompts.py:8-29`, `orchestrator.py:1484-1581`

The system prompt says:
> "You are an ARC puzzle solver. Treat action ids as opaque operators until this puzzle provides evidence about their effects."

And the instruction says:
> "What should you try next? Choose the next valid action based on observed effects."

This frames the problem as "trial and error with opaque buttons" instead of "analyze the pattern and deduce the rule." The LLM is never asked to:
- Look at the grid structure and identify patterns
- Compare before/after states to infer what transformation occurred
- Hypothesize what the puzzle is testing
- Verify a hypothesis against evidence
- Reason about spatial relationships, symmetries, or color mappings

The prompt is also cluttered with ~15 structured sections (SYSTEM, STATE, ENTITY_CONTEXT, MEMORY, SOLVE_CONTEXT, PLAN, ACTION_FACTS, EXPLORATION_SUMMARY, PATH_HYPOTHESES, HYPOTHESIS, OBSERVED_EFFECTS, REFLEX, HISTORY, OBSERVATION, INSTRUCTION) that fill the context window with navigation metadata instead of the actual puzzle content.

**Fix:** Restructure the prompt around pattern discovery:
```
SYSTEM: You are solving an ARC puzzle. Your goal is to discover the
transformation rule that maps input grids to output grids.

TRAINING EXAMPLES:
  Input 1: [grid]  -> Output 1: [grid]
  Input 2: [grid]  -> Output 2: [grid]

TEST INPUT: [grid]

ANALYSIS SO FAR:
  - Hypothesis: [current best guess at the rule]
  - Evidence for: [what supports it]
  - Evidence against: [what contradicts it]

What is the transformation rule? Apply it to produce the test output.
```

---

### F3. No Training Example Analysis [CRITICAL]

**Files:** `orchestrator.py`, `runner.py`

ARC puzzles provide training examples (input/output pairs) that demonstrate the transformation rule. The agent never systematically analyzes these examples to discover the pattern. Instead, it treats each step as an isolated "observe state, pick action" cycle.

The `perceive()` method ingests the observation into SideQuests memory, but never performs structured analysis like:
- Diffing training input vs output to identify what changed
- Finding commonalities across multiple training examples
- Extracting the rule that explains all examples

**Fix:** Add a dedicated `analyze_training_examples()` phase before any action selection:
1. For each training pair, compute a structured diff (what cells changed, what colors mapped to what, what spatial operation was applied)
2. Cross-reference diffs to find the common transformation
3. Verify the candidate rule against all training pairs
4. Only then apply to the test input

---

### F4. Centroid-Based Object Detection Misses ARC Patterns [HIGH]

**File:** `solver.py:260-284`, `solver.py:325-790`

The `ObjectRoleMapper` computes per-color centroids and tracks their movement to assign roles (player, goal, wall). This assumes:
- Objects are identified by color (correct for ARC)
- Objects move between frames (wrong — ARC grids are static transformations)
- The important thing is which color moves (wrong — the important thing is what spatial/logical rule governs the change)

A color centroid moving from (3,2) to (5,4) doesn't mean "player moved down-right." In ARC, it might mean "the pattern was translated," "a fill operation expanded," or "a rotation was applied."

**Fix:** Replace centroid tracking with structural analysis:
- Connected component extraction per color
- Shape recognition (rectangles, lines, L-shapes, etc.)
- Symmetry detection (vertical, horizontal, rotational)
- Topological relationship analysis (containment, adjacency, alignment)

---

## Section 2: Hypothesis and Reasoning Weaknesses

### H1. HypothesisManager Optimized for Game Transitions, Not Pattern Discovery [HIGH]

**File:** `hypothesis.py` (entire file, ~1500 lines)

The HypothesisManager tracks:
- State hashes and transitions between states
- Action effects (what happens when you press each button)
- Directional drift (which way things move)
- Loop detection (did we revisit a state)

None of this helps with ARC. What the hypothesis engine should track:
- **Structural invariants**: What stays the same between input and output?
- **Change patterns**: What systematic rule explains the differences?
- **Rule candidates**: Ranked hypotheses about the transformation, with evidence scores
- **Cross-example consistency**: Does the candidate rule explain ALL training examples?

**Fix:** Build an `ARCPatternHypothesizer` that generates and ranks transformation hypotheses:
- Symmetry hypothesis: test for reflection, rotation
- Color mapping hypothesis: test for systematic color substitution
- Spatial operation hypothesis: test for translation, scaling, cropping
- Conditional rule hypothesis: "if cell neighbors include X, then fill with Y"
- Compositional hypothesis: combinations of the above

---

### H2. meaningful_change_score Rewards Novelty Over Understanding [MEDIUM]

**File:** `hypothesis.py` (lines ~609-690 per the exploration agent)

The scoring formula:
```
0.40 * reward_signal + 0.25 * progress_signal + 0.25 * novelty_signal + 0.10 * effect_visibility
```

This rewards "something changed" (novelty, pixels moved) rather than "we learned something about the rule." A step that produces a completely new grid state but teaches nothing about the transformation scores higher than a step that revisits a known state but provides crucial insight about the pattern.

**Fix:** Add an `information_gain` signal that measures whether the transition helped narrow down the transformation hypothesis space. A transition is valuable if it disambiguates between competing hypotheses, not just if pixels changed.

---

### H3. VictoryHypothesizer Uses Game Categories, Not ARC Categories [HIGH]

**File:** `solver.py:843-956`

The VictoryHypothesizer classifies win conditions as:
```python
class VictoryType(str, Enum):
    REACH_GOAL       = "reach_goal"
    COLLECT_ALL      = "collect_all"
    SURVIVE          = "survive"
    SCORE_THRESHOLD  = "score_threshold"
    ELIMINATE        = "eliminate"
```

For ARC, the "victory condition" is always the same: **produce the correct output grid.** The variable is the transformation rule, not the goal type.

**Fix:** Replace `VictoryType` with `TransformationType`:
```python
class TransformationType(str, Enum):
    GEOMETRIC     = "geometric"      # rotation, reflection, translation
    COLOR_MAP     = "color_map"      # systematic color substitution
    FILL          = "fill"           # flood fill, border fill, conditional fill
    EXTRACTION    = "extraction"     # extract a subpattern from the grid
    COMPOSITION   = "composition"    # combine multiple operations
    CONDITIONAL   = "conditional"    # if-then rules based on neighbors/position
    COMPLETION    = "completion"     # complete a partial pattern
    UNKNOWN       = "unknown"
```

---

### H4. ArchetypeClassifier Categories Are Irrelevant to ARC [MEDIUM]

**File:** `solver.py:120-255`

The classifier distinguishes race/space/chase/displace based on:
- Number of directional actions
- HUD presence
- Reward trends
- Path hypothesis count

None of these signals exist in ARC puzzles. The classifier defaults to `space` after enough observations, which is meaningless.

**Fix:** Replace with a `PuzzleComplexityClassifier` that categorizes ARC puzzles by:
- Grid size (small grids suggest simpler rules)
- Number of distinct colors (more colors = more complex mapping)
- Symmetry presence in the input
- Number of connected components
- Whether the output grid is the same size as input (suggests in-place transformation vs extraction)

---

## Section 3: Action Selection and Planning Problems

### A1. The Agent Doesn't Use the REPL Sandbox for Verification [HIGH]

**File:** `prompts.py:40-45`, `orchestrator.py:1145-1310`

The REPL sandbox exists and can execute Python to verify grid logic. But the prompt only mentions it as a tool for "verifying grid logic or hypotheses." The agent never systematically uses it to:
1. Write a candidate transformation function
2. Apply it to training inputs
3. Compare against expected training outputs
4. Iterate until the function is correct

This is the single most impactful improvement available. A small LLM (qwen2.5:7b) can write simple Python functions much more reliably than it can reason about 2D grids in text.

**Fix:** Make REPL verification the primary solving strategy:
1. Ask the LLM to hypothesize a transformation rule
2. Ask it to write a Python function implementing the rule
3. Run the function against training examples in the REPL
4. If outputs match: apply to test input, done
5. If outputs don't match: feed the diff back to the LLM and iterate

This is essentially a "generate and test" loop, which is the most effective strategy for ARC with small LLMs.

---

### A2. Policy Override Cascade Defeats LLM Reasoning [HIGH]

**File:** `orchestrator.py:2058-2280`

The action selection pipeline is:
1. LLM proposes an action
2. `_enforce_action_policy()` may override it (exploration enforcement)
3. `_ensure_action6_coordinates()` may modify coordinates
4. `DecisionGuard.critique_action()` may override again
5. Verifier (if enabled) may reject and retry

The submission results show `decision_source: "policy_override"` on many steps. The LLM's reasoning is frequently overridden by hardcoded exploration policy that forces untested actions. This means:
- The LLM learns nothing from being overridden
- The exploration policy treats all actions as equally worth testing
- The agent can't develop a strategy because its choices keep getting replaced

**Fix:** Trust the LLM more after the initial exploration phase. The policy override should only fire when the LLM proposes something demonstrably harmful (blocked action, infinite loop), not when it "hasn't tested all buttons yet."

---

### A3. Exploration Policy Is Too Aggressive [HIGH]

**File:** `orchestrator.py:2181-2193`

```python
if unexplored and action_id not in unexplored:
    forced = unexplored[0]
    action.update({"action_id": forced, ...})
```

If ANY action remains untested, the policy forces it — even if the LLM has good reason to exploit a known-good action. This means the agent always exhausts all 7 actions before it can focus on the one that works. With 15 steps total, spending 7 on blind exploration leaves only 8 for actual solving.

**Fix:** Allow the LLM to skip exploration when it has a strong hypothesis. Only force exploration when:
- The agent has been stuck for N steps with zero progress
- The LLM explicitly proposes the same action for the 3rd+ consecutive time on the same state

---

### A4. PlanChunker BFS Is Wasted on ARC [MEDIUM]

**File:** `solver.py:1020-1357`

The PlanChunker tries BFS pathfinding through the state graph to find a path to a "high reward state." In ARC, there's no incremental reward signal — you either produce the correct output grid or you don't. BFS through explored states is finding paths through random noise.

The directional fallback is similarly misguided: "move player toward goal" assumes physical navigation.

**Fix:** Replace with a rule-refinement chunker:
- Chunk 1: Analyze training examples (structured diff)
- Chunk 2: Generate candidate rules (via LLM)
- Chunk 3: Verify candidates (via REPL)
- Chunk 4: Apply verified rule to test input

---

## Section 4: Prompt Engineering Issues

### P1. Prompt Is Too Large for a 7B Model [HIGH]

**File:** `orchestrator.py:1484-1581`

The benchmark metrics show `avg_tokens_per_step: 1018`, with 15 distinct prompt sections. A 7B parameter model has limited ability to follow complex multi-section prompts. The critical information (what the grid looks like, what actions are available) is buried under layers of metadata.

**Fix:**
- For qwen2.5:7b, keep the prompt under 500 tokens
- Lead with the grid state and the specific question
- Remove sections the LLM can't meaningfully use (SOLVE_CONTEXT, GRADUATION, PLATEAU)
- Put the JSON response format immediately before the question

---

### P2. Action IDs Are Opaque But the Agent Assumes Directional Meaning [MEDIUM]

**File:** `prompts.py:9-10`, `solver.py:1296-1306`

The prompt says "Treat action ids as opaque operators" but the PlanChunker has hardcoded mappings:
```python
if aid == "ACTION1": vec = (-1.0, 0.0)  # Up
elif aid == "ACTION2": vec = (1.0, 0.0)  # Down
elif aid == "ACTION3": vec = (0.0, -1.0)  # Left
elif aid == "ACTION4": vec = (0.0, 1.0)  # Right
```

This contradicts the opaque-action principle and will be wrong for any puzzle that doesn't use standard cardinal directions.

**Fix:** Never assume action semantics. Infer them purely from observed transitions, or better yet, move to a generate-output strategy that doesn't rely on sequential actions at all.

---

### P3. Effect Summary Duplicates Information Across Sections [LOW]

**File:** `orchestrator.py:1594-1619`

The `_apply_packet_transformations()` method tries to deduplicate between OBSERVATION and OBSERVED_EFFECTS, but ACTION_FACTS, PATH_HYPOTHESES, HYPOTHESIS, and EXPLORATION_SUMMARY often contain overlapping information. The LLM sees the same transition described in 4 different ways.

**Fix:** Consolidate to 2 sections max: (1) what happened, (2) what to do next.

---

## Section 5: Learning and Memory Issues

### M1. SideQuests Memory Doesn't Help Across Puzzles [MEDIUM]

**Files:** `orchestrator.py:293-468`, `runner.py:80-85`

Each puzzle branches a new quest scope. Memory retrieval (`current_truth`, `recall_relevant_lessons`, `analogical_search`) returns results from previous puzzles, but the results are generic game-playing lessons, not specific transformation rules.

The submission shows `retrieval_count: 1, total_retrieval_size_bytes: 6` — basically nothing was retrieved. Memory is not contributing to solving.

**Fix:** Store transformation rules discovered in previous puzzles as structured lessons:
```
Lesson: "When the input has a rectangular border of color X with interior
cells of color Y, the output fills all Y cells that are adjacent to X
cells with color Z."
```

Then retrieve these structural lessons when a new puzzle has similar grid characteristics (same colors, similar grid size, similar component structure).

---

### M2. Lesson Distillation Is Post-Hoc, Not Actionable [MEDIUM]

**File:** `runner.py:294`, `hypothesis.py` (distill_to_brain)

Lessons are only distilled after a puzzle completes (win or lose). By then, the learning is "I failed at this puzzle" or "I won" — neither helps the current puzzle. There's no mid-puzzle learning where the agent updates its understanding based on feedback.

**Fix:** Implement within-puzzle learning:
- After each step, update the transformation hypothesis based on the observed effect
- Track which hypotheses have been falsified
- Build a shrinking candidate set rather than a growing action history

---

## Section 6: Specific Code-Level Issues

### C1. DissonanceDetector Thresholds Are Too High [MEDIUM]

**File:** `solver.py:970-1010`

```python
STALL_THRESHOLD: int = 6
REWARD_STALL_THRESHOLD: int = 8
MAX_CHUNK_STEPS: int = 15
```

With only 10-15 max steps per puzzle, waiting 6 steps of zero progress before triggering dissonance wastes 40-60% of the budget. The submission result confirms: 15 steps of no progress, dissonance only triggered late.

**Fix:** Reduce to `STALL_THRESHOLD = 3`, `MAX_CHUNK_STEPS = 5`. If 3 steps produce zero progress, something is fundamentally wrong with the approach.

---

### C2. Graduation Assessment Is Overly Complex [LOW]

**File:** `solver.py:1034-1217`

The `_graduation_assessment()` method is 180 lines of weighted scoring to decide when to switch from exploration to directional play. With 15 steps total, spending any steps on "should we graduate from exploration to exploitation?" is wasteful. The agent should be solving from step 1.

**Fix:** Simplify to a binary: "Do I have a hypothesis? Yes -> verify it. No -> form one from training examples."

---

### C3. Plateau Policy Locks Into Dead Strategies [MEDIUM]

**File:** `orchestrator.py:2210-2280`

The plateau-aware exploitation policy locks the agent into a single "action family" when it detects sustained zero-reward. But if the fundamental strategy (navigate to goal) is wrong, locking into any action family just burns steps.

The submission shows: `LOCKED FAMILY: ACTION6` — the agent locked onto ACTION6 (click at coordinates) and kept clicking at different positions, producing zero reward for 15 consecutive steps.

**Fix:** Plateau detection should trigger a complete strategy reset (re-analyze the puzzle from scratch), not just switch to a different action within the same flawed framework.

---

### C4. Bootstrap Entity Discovery Assumes Smallest Color = Player [MEDIUM]

**File:** `solver.py:792-840`

```python
sorted_by_size = sorted(non_bg, key=lambda c: c.get("count") if isinstance(c, dict) else 0)
player_color_item = sorted_by_size[0]  # smallest = player
```

This assumes the smallest colored region is the player, which only works for navigation games. In ARC, the smallest region might be a key, a marker, a border decoration, or noise.

**Fix:** Don't assign roles at step 0 without evidence. Instead, analyze the grid structure (connected components, symmetries, patterns) and defer role assignment until after training example analysis.

---

## Section 7: Recommended Architecture Changes (Priority Order)

### Priority 1: Pivot to Generate-and-Test Strategy

The single highest-impact change: treat ARC as "write a Python function that transforms input to output" rather than "navigate a grid world."

1. Parse training examples into structured grids
2. Ask the LLM to describe the transformation pattern in natural language
3. Ask the LLM to implement the transformation as a Python function
4. Execute the function against training inputs via REPL sandbox
5. Compare outputs to expected training outputs
6. If match: apply to test input, submit
7. If no match: show the diff to the LLM, ask it to correct the function
8. Repeat until correct or out of steps

This leverages the LLM's strongest capability (code generation) rather than its weakest (spatial reasoning from text).

### Priority 2: Improve Grid Representation for LLM Reasoning

The current `StateSerializerForARC` converts grids to text. The representation matters enormously for a 7B model.

- Use a compact visual format where each color maps to a single character
- Show training input and output side-by-side
- Highlight differences with markers
- For small grids (< 10x10), show the full grid; for larger grids, show a summary of patterns

### Priority 3: Strip Down the Prompt

Remove all navigation-game scaffolding from the prompt:
- Remove ENTITY_CONTEXT (player/goal/wall roles)
- Remove SOLVE_CONTEXT (archetype/victory/graduation)
- Remove PLAN (chunk-based navigation plan)
- Remove EXPLORATION_SUMMARY (exploration/exploitation bookkeeping)
- Keep only: training examples, test input, current hypothesis, REPL results

### Priority 4: Use the REPL as Primary Verification

The REPL sandbox (`repl_sandbox.py`) already exists. Make it the core of the solving loop:
- Every hypothesis must be expressed as executable Python
- Every hypothesis must be tested against ALL training examples
- The agent can iterate on the code based on test failures

### Priority 5: Restructure Memory for Pattern Transfer

Store solved puzzles as:
```json
{
  "grid_characteristics": {"size": [5,5], "colors": 3, "symmetry": "vertical"},
  "transformation_type": "fill",
  "rule_description": "Fill enclosed regions with the border color",
  "python_function": "def transform(grid): ..."
}
```

Retrieve by grid characteristics similarity, not by game-archetype text matching.

---

## Appendix: Submission Results Analysis

From `submission_results_single.json`:
- **15 steps, all no_progress** — the agent never made meaningful progress
- **Archetype: space, Victory: reach_goal** — wrong mental model for ARC
- **Object roles: player=color0, goal=color1** — assigned game-like roles to colors
- **Locked onto ACTION6** — spent most steps clicking coordinates with zero effect
- **202K input tokens, 837 output tokens** — massive prompt, tiny response
- **366 seconds** — ~24 seconds per step, mostly LLM inference time

The agent is doing a lot of work (hypothesis tracking, graduation assessment, plateau detection, fatigue management) — but all of it is in service of a strategy that fundamentally misunderstands what ARC puzzles require.

---

## Summary

| Issue | Severity | Effort | Impact |
|-------|----------|--------|--------|
| F1. Wrong mental model (navigation vs transformation) | CRITICAL | XL | Unlocks solving entirely new puzzle classes |
| F2. LLM asked wrong question | CRITICAL | M | Directs reasoning toward actual puzzle |
| F3. No training example analysis | CRITICAL | L | Most puzzles need cross-example reasoning |
| A1. REPL not used for verification | HIGH | M | Code generation >> spatial text reasoning |
| P1. Prompt too large for 7B | HIGH | S | Smaller prompt = better LLM adherence |
| A2. Policy override defeats reasoning | HIGH | S | Let the LLM actually solve |
| A3. Exploration too aggressive | HIGH | S | Stop wasting steps on blind exploration |
| F4. Centroid detection misses patterns | HIGH | L | Need structural analysis, not motion tracking |
| H1. Hypothesis engine wrong focus | HIGH | XL | Need pattern hypotheses, not transition tracking |
| C1. DissonanceDetector too slow | MEDIUM | S | Faster recovery from bad strategies |
| C3. Plateau locks into dead strategies | MEDIUM | S | Strategy reset > action shuffle |
| M1. Memory doesn't transfer patterns | MEDIUM | M | Cross-puzzle learning needs structural keys |

**Bottom line:** The agent needs to stop thinking like a game player and start thinking like a puzzle solver. The infrastructure is solid — the strategy is wrong.
