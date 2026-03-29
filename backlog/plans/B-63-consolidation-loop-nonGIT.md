# B-63-consolidation-loop-nonGIT — Consolidation Loop for Non-Git Sessions

**Card:** B63 | **Priority:** P8 | **Depends on:** B17 (Hippocampus routing)

## Summary
Extend consolidation loop to non-git sessions. Ensure passive ingestion and confidence re-scoring work for sessions without git context (desktop apps, non-dev workflows).

## Technical Approach

- Verify Loop Steps 1-7 operate correctly when `git_root_path` is None
- Ensure routing still works (B17 semantic routing handles this)
- Test Message ingestion → Classification → Artifact creation in non-git contexts
- No special conditional logic needed if B17 is robust

## Files to Create/Modify

- Validation/test only: `tests/test_consolidation_nonGIT_sessions.py`
- Verify end-to-end: non-git session notify_turn → Message stored → Concept created

## Acceptance Criteria

1. Non-git sessions (Codex, ChatGPT Desktop running standalone) ingest messages correctly
2. Loop Steps 1-7 execute without errors on non-git turns
3. Confidence classification works on non-git messages
4. Artifacts are created and linked to Session (not MainQuest git root)
5. Integration test: OpenClaw/Codex session → notify_turn → Message → artifact created

## Notes

- Largely validation work; core functionality should already support this if B17 is complete
