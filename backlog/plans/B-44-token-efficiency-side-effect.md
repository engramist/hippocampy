# B-44-token-efficiency-side-effect — Token Efficiency as a Side Effect (Not a Feature)

**Card:** B44 | **Priority:** P10 | **Depends on:** B18 (working memory)

## Summary
Position token efficiency as an emergent property of B18 working memory design, not a primary feature. Document load tracking smart deduplication and context health monitoring as mechanisms that naturally reduce bloat.

## Technical Approach

- Document how B18 load tracking demotes already-loaded nodes in retrieval ranking
- Explain how this reduces redundant node injection
- Calculate token savings vs. baseline retrieval (no dedup, no load awareness)
- Add commentary to schema and tools: why these design choices save tokens as side effect

### Current Verified State
- `docs/token-efficiency-side-effect.md` already exists and covers the core working-memory mechanism.
- `mcp_engine/working_memory.py` already contains substantial B44-oriented explanatory comments.
- `mcp_engine/tools/__init__.py` already contains an inline comment block above smart deduplication in `current_truth()`.

This card should therefore be finished as a **completion pass**, not a redesign.

### Completion Work Required

1. **Strengthen the documentation artifact** in `docs/token-efficiency-side-effect.md` so it reflects the full card intent, not just the mechanism.
2. **Preserve the framing** that token efficiency is a consequence of working memory, not a standalone product feature.
3. **Make the rejected approaches explicit** so the decision is documented and not re-litigated later.
4. **Mark the backlog card and tracker complete** only after the documentation is updated and validated.

### Required Documentation Additions

Update `docs/token-efficiency-side-effect.md` with the following explicit sections or equivalent content:

#### 1. What SideQuests Does Not Do
- Explicitly reject NLP stop-word stripping / "Caveman Speak".
- Explain why this is rejected:
	- small token savings
	- disproportionate reasoning-quality loss
	- not compatible with preserving the semantic structure LLMs rely on

#### 2. What SideQuests Does Not Own
- Explicitly state that chat-history compaction / summarizing old messages is the host client's responsibility, not the Brain's.
- Clarify that SideQuests is a memory system, not a context-window proxy.

#### 3. Marketing / Positioning Guidance
- Add a short section that says token efficiency should not be marketed as a standalone "token saver mode".
- Frame it as an evidence-backed side effect of B18 working memory and deduplication.
- Keep the tone architectural and factual.

#### 4. Relationship to Other Cards
- Explicitly tie B44 to:
	- B18 working memory
	- B16 task-based model routing
	- B45 token measurement and visualization
- Make clear that B44 is the architectural decision record and B45 is where empirical measurement belongs.

### Code Comment Changes

Only make code comment changes if something important is missing.

#### `mcp_engine/working_memory.py`
- Keep existing B44 comments unless they are clearly incomplete.
- If edited, stay documentation-only: no logic changes.

#### `mcp_engine/tools/__init__.py`
- Keep the existing smart-deduplication commentary unless a small clarification is needed.
- No behavior changes.

### Card / Tracker Updates

#### `backlog/B44.md`
- Change `State: ready` -> `State: complete`
- Update heading to include `— ✅ DONE (2026-03-28)`
- Add a `Validation Note (2026-03-28)` section listing:
	- `docs/token-efficiency-side-effect.md`
	- `mcp_engine/working_memory.py`
	- `mcp_engine/tools/__init__.py`
- Include the validation command(s) and result.

#### `backlog/masterBacklogTracker.md`
- Mark B44 complete with the same done marker/date format used elsewhere.
- Add the matched plan path if not already present.
- Update summary counts accordingly.

### Files To Modify

- `docs/token-efficiency-side-effect.md`
- `backlog/B44.md`
- `backlog/masterBacklogTracker.md`

Optional only if needed for wording consistency:
- `mcp_engine/working_memory.py`
- `mcp_engine/tools/__init__.py`

### Files Not To Modify

- No runtime logic files unless the change is comment-only.
- No benchmark or ARC files.
- No package/build files.

### Documentation Section
- Add `docs/token-efficiency-side-effect.md`
- Explain: "Context window is working memory. Load tracking prevents re-injecting known nodes."
- Show: baseline vs. optimized token consumption curve

## Files to Create/Modify

- `docs/token-efficiency-side-effect.md` — new documentation
- `mcp_engine/tools.py` — add inline comments explaining dedup behavior
- `mcp_engine/working_memory.py` — document load tracking side effects

## Acceptance Criteria

1. Token efficiency is documented as side effect, not primary feature
2. Load tracking benefits are clearly explained
3. Baseline-vs-optimized token charts are included
4. No new code needed; only clarification and documentation
5. Rejected approaches (stop-word stripping, host-history compaction) are documented explicitly
6. B44 card and tracker are updated to complete with a validation note

## Validation

Run:

1. `pytest tests/test_working_memory.py tests/test_retrieval.py -q`

This is a docs/comment card, so targeted regression is enough.

## Delegation Prompt

Use exactly:

`gemini -p "Read backlog/plans/B-44-token-efficiency-side-effect.md and implement exactly as specified. Read docs/token-efficiency-side-effect.md, backlog/B44.md, backlog/masterBacklogTracker.md, mcp_engine/working_memory.py, and mcp_engine/tools/__init__.py first. Use minimal safe changes. Do not change runtime behavior. Update the documentation/card/tracker, run the specified pytest command, and report changed files plus validation results." --yolo 2>&1`

## Notes

- This is predominantly a documentation card
- Sets foundation for B45 (measurement) with correct framing
