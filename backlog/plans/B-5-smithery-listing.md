# B-5-smithery-listing — Smithery Registry Listing

**Card:** B5 | **Priority:** P2 | **Depends on:** B4 (PyPI publish complete)

## Summary
Register SideQuests on Smithery (the MCP ecosystem marketplace) to make it discoverable for developers. Enables community installation via `npx @smithery/cli install sidequests-brain`.

## Technical Approach

### Smithery Server Definition
Create `smithery.json` in project root:
```json
{
  "name": "sidequests-brain",
  "version": "0.1.0",
  "type": "stdio",
  "description": "Local AI memory system with gated consolidation loop and graph-native Kùzu database",
  "command": "python",
  "args": ["-m", "sidequests.adapters.mcp_server"],
  "tools": [
    {
      "name": "notify_turn",
      "description": "Forward conversation turn to brain for passive ingestion and background processing"
    },
    {
      "name": "current_truth",
      "description": "Retrieve relevant memory before answering architecture/decision questions"
    },
    {
      "name": "explore_graph",
      "description": "Traverse the knowledge graph via directed traversal and pattern matching"
    },
    {
      "name": "branch_quest",
      "description": "Create a new SideQuest for tangent explorations"
    },
    {
      "name": "complete_quest",
      "description": "Mark the current quest as completed"
    }
  ],
  "resources": [
    {
      "name": "Memory Index",
      "description": "Real-time knowledge graph with Kùzu embedded vector store",
      "type": "graph_database"
    }
  ]
}
```

### Smithery Publisher Account
- Create account at smithery.ai (if not already done)
- Register GitHub organization or individual account
- Link to GitHub repo: github.com/djshelton/sidequests-brain

### Publishing Step
```bash
npx @smithery/cli publish smithery.json --token <SMITHERY_TOKEN>
```

### Verification
- After publish, verify listing appears in: https://smithery.ai/server/sidequests-brain
- Test: `npx @smithery/cli install sidequests-brain --client claude`
- Verify installation instructions work in clean environment
- Cross-check: from Smithery, install → setup → smoke test

## Files to Create/Modify

- `smithery.json` — registry definition (root of project)
- `docs/smithery-install.md` — installation instructions from Smithery
- Update `README.md` — add Smithery install one-liner section

## Acceptance Criteria

1. `smithery.json` is valid and passes Smithery validator
2. Smithery listing is live and searchable by "sidequests-brain"
3. `npx @smithery/cli install sidequests-brain --client claude` completes without errors
4. All 5+ tools are correctly listed on the Smithery registry page
5. From registry-installed version: `sidequests setup` runs and connects successfully
6. README includes Smithery install instruction: `npx @smithery/cli install sidequests-brain --client claude`

## Notes

- Provisional patent filed March 25, 2026 (Application #64/017,066); publication is no longer blocked by pre-filing disclosure constraints.
- Ensure no hardcoded paths or environment dependencies in MCP server entry point
