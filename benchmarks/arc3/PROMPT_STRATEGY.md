# ARC-AGI-3 Prompt Strategy

This document is the operating contract for prompt construction in the ARC runner and orchestrator.

## Goal

SideQuests should reduce decision-time prompt load, not amplify it.

For ARC, the prompt should contain only what changes the next action.

## Current Design Principle

The target is:

`prompt = stable operating frame + compact state summary + top-ranked decision support + short recent history + explicit valid actions + action request`

In plain language:
- small by default
- retrieval on demand
- compact summaries over raw dumps
- only include memory that can change the next move

## Prompt Equation

The current ARC action prompt should be composed of:

1. Stable operating frame
- role
- puzzle state
- energy
- valid action list

2. Compact state summary
- grid dimensions
- top color distribution
- frame hash
- coarse spatial summary

3. Top-ranked decision support
- at most 1 lesson
- at most 1 memory
- at most 1 analogy
- exclude boilerplate ARC API contract reminders from the action prompt

4. Hypothesis layer
- loop warning if present
- at most 1 confirmed hypothesis
- at most 1 active hypothesis
- untested actions list

5. Plan layer
- at most 2 plan steps

6. Recent history
- at most 2 prior actions
- concise rationale snippets only

7. Action request
- explicit output schema
- explicit valid actions
- ask for the next decision from observed effects, not generic pattern commentary

## First-Input Rule

The first puzzle-ingestion packet can be slightly richer than the per-step action prompt.

It should include compact structural features that help retrieval and pre-activation pattern match quickly:
- frame hash
- compact spatial sketch
- stable ids
- concise observed puzzle structure

This is not permission to stuff the action prompt. It is a targeted bootstrap for retrieval quality.

## Meaningful Change Equation

Yes: ARC should also have an explicit effect-value equation, not just a prompt equation.

The point is to stop treating "many pixels changed" as automatically good. For ARC control, action value should depend mainly on progress, novelty, and reward, with pixel delta only as a weak supporting signal.

Current rule:

`meaningful_change = 0.40 * reward + 0.25 * progress + 0.25 * novelty + 0.10 * effect_visibility - 0.35 * loop_penalty - 0.25 * no_change_penalty - repeat_zero_reward_penalty`

Where:
- `reward` = immediate reward signal from the environment
- `progress` = whether the action moved the puzzle into a genuinely new, non-terminal state
- `novelty` = whether the resulting state was new rather than a revisit
- `effect_visibility` = a small tie-breaker based on visible board change
- `loop_penalty` = penalty when the action leads back into a visited loop
- `no_change_penalty` = penalty when the action produces no visible change
- `repeat_zero_reward_penalty` = decay repeated exploitation when the same action keeps generating non-rewarding states

Additional decay rule:
- after 2 consecutive zero-reward uses of the same action, novelty and progress should decay unless the new attempt has stronger evidence than the previous ones

Interpretation bands:
- `>= 0.75` → `strong_progress`
- `>= 0.35` → `tentative_progress`
- `> 0.00` → `low_value`
- `0.00` → `no_progress`

Prompting rule:
- begin in an explicit exploration phase
- before exploiting, get at least one observed effect for each available action when the budget allows
- prefer `strong_progress`
- use `tentative_progress` for bounded exploration
- avoid repeating `low_value` or `no_progress` actions unless new evidence appears
- do not keep exploiting `tentative_progress` forever when reward stays at `0.0`
- if the top tested actions both decay into `low_value` or `no_progress`, broaden exploration rather than bouncing between them

## Hard Limits

These are the current implementation limits for the first prompt-slimming pass:

- `lessons <= 1`
- `memories <= 1`
- `analogies <= 1`
- `history steps <= 2`
- `plan steps <= 2`
- `confirmed hypotheses <= 1`
- `active hypotheses <= 1`
- `reflex warnings <= 1`
- `reflex suggestions <= 1`

## Anti-Goals

Do not:
- dump the full raw `64x64` grid every step
- inject repeated ARC API contract text into action prompts
- replay full memory payloads or graph node JSON blobs
- include memory just because it was retrieved
- allow unavailable actions returned by the LLM to pass through unvalidated

## Retrieval Rule

Memory exists to compress the next decision, not narrate the system state.

If retrieved context does not alter the next action choice, it should stay out of the prompt.

On the first move, memory should not steer action selection unless it clearly matches the current puzzle state.

## Backlog Direction

Longer term, ARC should move toward:
- minimal default prompt state
- content-window-free retrieval on demand
- passive pre-activation of likely-needed entities and paths
- fast delivery of compact summaries instead of bulk context

North star:

**small, purposeful context with fast, targeted retrieval**
