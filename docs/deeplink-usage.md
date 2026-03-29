# Deep-Link Handoff (Memory Control Panel)

The SideQuest Brain Daemon supports deep-linking from chat sessions (Claude, ChatGPT, etc.) directly into the Memory Control Panel (MCP). This allows for rapid auditing of reified decisions, constraints, and concepts.

## URL Structure

The deep-link URL follows this format:

```
http://127.0.0.1:8001/memory/node/{node_id}?context={quest_id}
```

- **node_id**: The unique ID of the Decision, Constraint, or Concept.
- **context** (optional): The Quest ID to filter the graph view.

## Integration in Chat

When the Brain Daemon retrieves memory via `current_truth` or processes a turn via `notify_turn`, it automatically injects `memory_link` metadata.

### 1. Retrieval Links
In `current_truth` responses, each result includes a `memory_link`. UI adapters can surface these as small "View in Memory" buttons or links.

### 2. Insight Links
In `notify_turn` responses, the `insights` object includes links for any newly extracted entities.

## UI Behavior

1. **Automatic Navigation**: Clicking a deep-link opens the MCP and highlights the specific node.
2. **Neighbor Context**: The MCP automatically fetches and displays 1-hop neighbors of the linked node in a side panel.
3. **Graph Centering**: The D3.js force graph pans and zooms to center on the requested node.
4. **History Support**: The MCP uses the Browser History API, allowing you to use the "Back" button to return to previously viewed nodes.

## Configuration

The base URL for deep-links can be configured in `sidequests.toml` (or via the daemon config):

```toml
[mission_control]
base_url = "http://127.0.0.1:8001"
```

Defaults to `http://127.0.0.1:8001`.
