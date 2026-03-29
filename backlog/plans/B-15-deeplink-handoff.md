# B-15-deeplink-handoff — Deep-Link Handoff (Chat → Memory Control Panel)

**Card:** B15 | **Priority:** P6 | **Depends on:** B7 (adapters complete)

## Summary
Implement deep-linking between chat sessions and the Memory Control Panel. Users can click links in chat to jump directly to relevant memory nodes for review and audit.

## Technical Approach

### URL Scheme
- Memory Control Panel running at `http://127.0.0.1:8001/memory`
- Deep-link format: `http://127.0.0.1:8001/memory/node/{node_id}?context=quest_id`
- Query params: `context`, `highlight_edges`, `related_threshold`

### Integration Points
1. **In LLM responses**: when referencing a Decision/Constraint from memory, inject short link:
   - `[View in Memory: Decision-123]`
   - Link opens Memory Control Panel at that node with quest context

2. **In notify_turn response**: include memory retrieval results with deep-links
   - Each recalled node gets `memory_link` property
   - Format as markdown link in response

3. **In Memory Control Panel UI**: all node names are clickable → stay on same page, highlight node

### Implementation
- `web/routes/node_detail.py` — GET `/memory/node/{node_id}` route
- `mcp_engine/tools/notify_turn.py` — inject link generation in response
- `web/static/graph_ui.js` — handle deep-link navigation
- Test: link in chat → opens correct node in Memory Panel

## Files to Create/Modify

- `web/routes/node_detail.py` — new route for node detail view
- `web/static/graph_ui.js` — deep-link navigation handler
- `mcp_engine/tools.py` — augment responses with memory_link metadata
- `tests/test_deeplink_integration.py` — end-to-end link following
- `docs/deeplink-usage.md` — user documentation

## Acceptance Criteria

1. Memory Control Panel deep-link routes work: `/memory/node/{node_id}`
2. Links in chat responses open correct node in Memory Panel
3. Node context (quest filter) is preserved when following link
4. Multiple deep-links can be followed in sequence without losing state
5. Graph UI highlights linked node and shows 1-hop neighbors
6. Integration test: notify_turn → response includes link → click link → correct node displayed

## Notes

- Deep-links are user-facing audit trail — verify they work reliably
- No authentication required (127.0.0.1 only, local access)
