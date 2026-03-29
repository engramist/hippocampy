# B-64-message-count-bug — Bug: Message Count Shows 0 in Stats

**Card:** B64 | **Priority:** P8 | **Depends on:** None (stats bug)

## Summary
Fix bug where message count displays as 0 in session stats despite messages being stored.

## Technical Approach

- Likely root cause: stats query uses wrong relationship or filter (SENT_IN edge pruned, or archived filter too aggressive)
- Trace: Session node → count SENT_IN edges → return count
- Verify archived messages are excluded correctly but not over-aggressively
- Check Session.onboarded and other fields don't interfere

## Files to Create/Modify

- `mcp_engine/tools.py` — locate stats generation, fix count query
- `tests/test_session_stats.py` — verify message count is reported correctly

## Acceptance Criteria

1. Session stats report correct message count (non-zero after messages are ingested)
2. Archived messages are not double-counted or excluded incorrectly
3. Integration test: notify_turn 5 times → stats show message_count = 5

## Notes

- Low-effort bug fix; likely 1-2 line query correction
