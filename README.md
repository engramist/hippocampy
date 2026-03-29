# SideQuests Brain

Persistent AI memory system with a Gated Consolidation Loop and graph-native Kùzu database.

## Installation

### Via Smithery (Recommended for MCP Clients)

Install the SideQuests Brain directly into your preferred MCP client (e.g., Claude Desktop):

```bash
npx @smithery/cli install sidequests-brain --client claude
```

### Via Pip

```bash
pip install sidequests-brain
```

Or run directly with uv:

```bash
uvx sidequests-brain
```

## Features

- **Persistent Context:** Remembers your decisions, constraints, and concepts across sessions.
- **Graph-Native:** Built on Kùzu for efficient relationship management.
- **Gated Consolidation:** Biomimetic heuristic processing to filter noise from knowledge.
- **MCP Compatible:** Works with any MCP-enabled AI client.

## Requirements

- Python 3.12 or 3.13
- Kùzu 0.11.3

## Quick Start

```bash
sidequests setup
sidequests-daemon start
```

For more details, see the [Documentation](docs/).
