# B-10-explore-graph-tool — explore_graph Tool (Directed Graph Traversal)

**Card:** B10 | **Priority:** P5 | **Depends on:** None (core tool)

## Summary
Implement `explore_graph` MCP tool for directed graph traversal. Enables LLMs to follow causal chains and multi-hop relationships in the knowledge graph.

## Technical Approach

### Graph Traversal
- Depth-first search (DFS) with max depth limit (default 3)
- Breadth-first search (BFS) option for wider context recall
- Filter by relationship type (e.g., only REQUIRES → ENABLES chains)
- Return path + intermediate nodes + relationship metadata

### Tool Signature
```json
{
  "name": "explore_graph",
  "description": "Traverse knowledge graph from a seed node, following relationships up to N hops",
  "inputSchema": {
    "type": "object",
    "properties": {
      "start_node_id": { "type": "string", "description": "Node ID to start traversal" },
      "session_id": { "type": "string" },
      "depth": { "type": "integer", "default": 3, "minimum": 1, "maximum": 5 },
      "strategy": { "type": "string", "enum": ["dfs", "bfs"], "default": "dfs" },
      "edge_types": { "type": "array", "items": { "type": "string" } },
      "direction": { "type": "string", "enum": ["outgoing", "incoming", "both"], "default": "both" }
    },
    "required": ["start_node_id", "session_id"]
  }
}
```

### Response Format
```json
{
  "paths": [
    {
      "nodes": [
        { "node_id": "...", "node_type": "...", "text": "...", "confidence": 0.95 },
        { "node_id": "...", "node_type": "...", "text": "...", "confidence": 0.87 }
      ],
      "edges": [
        { "from": "...", "to": "...", "type": "REQUIRES", "confidence": 0.92 }
      ],
      "path_depth": 2,
      "path_strength": 0.89
    }
  ],
  "total_nodes_visited": 15,
  "exploration_complete": true
}
```

### Implementation Files
- `mcp_engine/tools/explore_graph.py` — core traversal logic
- Update `mcp_engine/tools.py` — register tool in MCP interface
- `tests/test_explore_graph.py` — traversal behavior validation

## Acceptance Criteria

1. Tool accepts start_node_id and session_id, returns paths
2. DFS and BFS strategies produce different but valid results
3. Edge type filtering works (only returns REQUIRES edges if specified)
4. Depth limit prevents runaway traversal (max 5 hops)
5. Response includes node metadata, edge types, and path strength
6. Integration test: traverse from decision → enables → downstream requirements
7. Performance: traversal of 1000-node subgraph completes in <1s

## Notes

- Keep traversal cost-aware: don't collect entire reachable set
- Confidence clamping: exclude low-confidence intermediate nodes optionally
