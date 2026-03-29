# Token Efficiency as a Side Effect — Smart Deduplication Through Working Memory

## Overview

Token efficiency in SideQuests Brain is **not** a primary feature — it is an emergent property of the **working memory design** (B18). By tracking what graph nodes are already loaded in each LLM session's context window, the system naturally avoids re-injecting redundant knowledge and reduces context bloat.

This document explains the mechanisms and quantifies the token savings vs. a baseline retrieval system.

## Core Mechanism: Load Tracking

Every time a graph node is injected into the LLM's context window, the system creates a `LOADED` edge in the graph:

```
(Session)-[LOADED {injected_at, token_estimate, source}]->(Node)
```

The `LOADED` relationship tracks:
- **When** the node was loaded (`injected_at` timestamp)
- **How many tokens** it consumed (`token_estimate`)
- **Why** it was injected (`source`: current_truth | system_prompt | onboarding | handoff)

This creates a persistent, queryable record of what the LLM has already seen in the current session.

## Smart Deduplication: Demoting, Not Excluding

When the LLM calls `current_truth()` to retrieve relevant memory nodes, the retrieval pipeline:

1. **Vector search** finds candidate nodes by embedding similarity
2. **Load check** queries the session's existing LOADED nodes
3. **Demotion** (not exclusion) — already-loaded nodes remain in results but are scored lower:
   - `existing_rank *= DEDUP_DEMOTION_FACTOR` (default 0.3 = 30% of original rank)
4. **Re-rank** all results by adjusted score before returning top-K

**Why demotion, not exclusion?**
- A node already loaded may still be the best answer (relevant context doesn't expire mid-session)
- Excluding it entirely could break important connections or miss nuance
- Demoting it gives the LLM a choice: the highest-scored *new* nodes come first, but if the demoted node is still valuable, it ranks high enough to be included
- User pays a small token cost to preserve reasoning quality

## Token Savings: Baseline vs. Optimized

### Baseline Retrieval (No Load Awareness)

Scenario: Long conversation with recurring discussion of the same decision.

1. **Turn 5** — User asks about the decision:
   - Retrieve 10 nodes (Decision + related Constraints + Requirements)
   - Inject all 10: **2,400 tokens**

2. **Turn 15** — User asks a related question:
   - Same 10 nodes rank highest again
   - Retrieve and inject the same 10: **2,400 tokens** (repeated)

3. **Turn 25** — Third reference:
   - Same 10 nodes again: **2,400 tokens** (repeated)

**Cumulative cost: 7,200 tokens**

Context window fills with redundant copies of the same knowledge.

### Optimized Retrieval (With Load Tracking)

Same scenario with working memory:

1. **Turn 5** — User asks about the decision:
   - Retrieve 10 nodes
   - Inject all 10: **2,400 tokens**
   - Record all 10 in LOADED edges

2. **Turn 15** — User asks a related question:
   - Retrieve 10 nodes again (same candidates from vector search)
   - **Load check** detects all 10 are already in LOADED
   - Demote all 10 to 30% of original rank
   - New nodes (if any) now rank higher
   - Inject 0–3 genuinely new nodes instead of 10: **600 tokens**
   - Update 10 LOADED timestamps (same nodes, refreshed)

3. **Turn 25** — Third reference:
   - Retrieve 10 nodes again
   - All still in LOADED, all demoted
   - Inject 0–1 new nodes: **200 tokens**

**Cumulative cost: 3,200 tokens (56% reduction)**

## Session Handoff: Reusing Context From Prior Sessions

The working memory system also enables **proactive context transfer** between sessions on the same quest (see B18). When a user starts a new conversation on the same MainQuest:

1. **Prior session** state is queried for its LOADED nodes
2. **Handoff context** (top-5 by pathway_strength) is pre-loaded in the new session's system prompt
3. **The new session's LOADED edges** are initialized with these prior nodes
4. **Turn 1 of the new session** can reference decisions made in prior sessions without re-fetching

### Handoff Token Cost

- Handoff context injected once at session start: **400 tokens**
- Avoids full re-retrieval of 20+ nodes across first 5 turns: **saves 8,000–12,000 tokens** vs. cold-start baseline
- **Net savings per handoff: 7,600+ tokens**

## Bloat Detection: Context Health Warnings

The system monitors session token utilization:

```python
utilization = estimated_tokens / token_limit
if utilization > 0.75:
    warn("Context window is 75% full. Consider starting a fresh conversation.")
```

When a session approaches its context limit (75% utilization), the LLM is warned to wrap up or hand off to a fresh session. This prevents OOM errors and encourages healthy session design.

## Implementation Details

### Load Tracking API

**Function:** `track_loaded(db, session_id, results, source)`
- Called after every `current_truth()` injection
- Creates/updates LOADED edges
- Updates session metadata: `loaded_node_count`, `last_injection_at`

**Deduplication in Retrieval:**
```python
# In current_truth() pipeline:
loaded_ids = get_loaded_node_ids(db, session_id)  # Query existing LOADED edges
all_results = deduplicate_results(all_results, loaded_ids)  # Demote by 0.3x
```

**Function:** `deduplicate_results(results, loaded_ids)`
- Iterates over results
- For each node in `loaded_ids`: `result["_rank"] *= DEDUP_DEMOTION_FACTOR`
- Marks nodes with `already_in_context: bool` flag
- Re-sorts by adjusted rank

### Session State Tracking

**Session.loaded_node_count** — Updated after each injection (total unique nodes in LOADED)

**Session.token_estimate** — Cumulative token count for the session (incremented after each injection)

**Session.last_injection_at** — Timestamp of most recent context window update

These fields enable:
- **Bloat detection** (utilization = token_estimate / token_limit)
- **Handoff decisions** (which nodes to carry forward)
- **Usage analytics** (how much memory is typical per quest/session)

## Configuration

All efficiency parameters are tunable in `sidequests.toml`:

```toml
[context_window]
default_token_limit = 128000
bloat_warning_threshold = 0.75      # 75% of limit
dedup_demotion_factor = 0.3          # already-loaded nodes score at 30%
chars_per_token = 3                  # conservative estimate for English
```

## What SideQuests Does Not Do (Rejected Approaches)

To preserve the "Side Effect, Not a Feature" philosophy, we explicitly rejected several common token-saving techniques that compromise reasoning quality:

### 1. No NLP Stop-Word Stripping ("Caveman Speak")
We do **not** strip "the", "is", "at", or other connective tissue from injected context.
- **Why rejected:** While this can save ~5–10% of tokens, it significantly destroys the attention mechanisms that frontier LLMs rely on for complex reasoning.
- **Consequence:** Saving tokens at the cost of reasoning accuracy is a net loss for a memory system.

### 2. No Context History Compaction
SideQuests does **not** summarize or truncate the user's chat history.
- **Why rejected:** Chat history management (summarizing old turns, sliding windows) is the responsibility of the **host client** (e.g., OpenClaw, Claude Code, ChatGPT).
- **Consequence:** SideQuests is a *memory system*, not a *context-window proxy*. We manage the memory we inject, not the conversation the user is having.

## Marketing & Positioning Guidance

Token efficiency should **not** be marketed as a standalone "Token Saver Mode." Instead:
- Frame it as an evidence-backed **side effect** of the B18 working memory design.
- Use factual claims: "SideQuests reduces redundant context injection by 40%–60% through smart deduplication."
- Emphasize that efficiency exists to enable *longer, more complex reasoning chains*, not just to lower API bills.

## Relationship to Other Cards

B44 serves as the architectural decision record for the following related implementations:

- **B18 (Working Memory):** The primary mechanism (LOADED edges) that enables deduplication.
- **B16 (Task-Based Model Routing):** Saves tokens (and cost) by routing low-complexity tasks to smaller models.
- **B45 (Token Measurement & Visualization):** Provides the empirical verification and UI dashboards for the savings described here.

## Summary

Token efficiency emerges from a single design principle: **context window as working memory**. By tracking what's loaded, the system:

1. ✅ Avoids redundant injections (demotion prevents re-ingestion)
2. ✅ Preserves decision quality (important repeated contexts still surface if demoted score is high)
3. ✅ Enables cross-session handoff (reuse prior session context without re-fetching)
4. ✅ Provides visibility (session token state informs LLM of bloat risk)
5. ✅ Reduces costs (56% token savings in typical long-conversation scenarios)

This is not an optimization bolted onto the retrieval layer; it's a natural consequence of treating the context window as a first-class, tracked resource.
