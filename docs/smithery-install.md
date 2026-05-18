# HippoCampy — Smithery Installation

HippoCampy is available on [Smithery](https://smithery.ai), the registry for Model Context Protocol (MCP) servers.

## One-Click Installation

You can install the HippoCampy directly into your preferred MCP client using the Smithery CLI:

### For Claude Desktop
```bash
npx @smithery/cli install hippocampy --client claude
```

## Manual Configuration

If you prefer to configure your client manually, use the following server definition:

**Type:** `stdio`  
**Command:** `python`  
**Arguments:** `["-m", "campy.adapters.mcp_server"]`

### Tools Included
- **notify_turn**: Passive ingestion of conversation history.
- **current_truth**: Retrieval of relevant project memory.
- **explore_graph**: Traversal of the knowledge graph.
- **branch_quest**: Manage tangents and sub-tasks.
- **complete_quest**: Synthesis of lessons learned.

## Post-Installation
After installation, ensure the Brain Daemon is running:
```bash
campy setup
```
This will initialize the local database and verify connectivity.
