# HippoCampy

Persistent AI memory system with a Gated Consolidation Loop and graph-native Kùzu database.

**Patent Pending:** Campy includes patent-pending memory architecture. A U.S. provisional application was filed March 25, 2026 (Application #64/017,066). No patent has been granted. See [docs/nonprovisional-strategy.md](docs/nonprovisional-strategy.md) for filing facts and deadline.

## Installation

### Quick Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash
```

### Inspect First

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
bash /tmp/campy-bootstrap.sh --dry-run   # See what it will do
bash /tmp/campy-bootstrap.sh             # Run it
```

### Manual Install

```bash
pipx install hippocampy    # or: pip install hippocampy
campy install              # Detect and register AI agents
campy doctor               # Verify everything works
campy start                # Start the memory daemon
```

### Developer Install (from Source)

```bash
git clone git@github.com:djs54/hippocampy.git
cd hippocampy
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
campy install
campy status
```

The provisional patent application is filed, so public release is no longer blocked by pre-filing disclosure constraints. The remaining work before making the one-line public installer canonical is packaging and installer hardening.

### Via Smithery (Recommended for MCP Clients)

Install the HippoCampy directly into your preferred MCP client (e.g., Claude Desktop):

```bash
npx @smithery/cli install hippocampy --client claude
```

### Via Pip

```bash
pip install hippocampy
```

Or run directly with uv:

```bash
uvx hippocampy
```

## Features

- **Persistent Context:** Remembers your decisions, constraints, and concepts across sessions.
- **Graph-Native:** Built on Kùzu for efficient relationship management.
- **Gated Consolidation:** Biomimetic heuristic processing to filter noise from knowledge.
- **MCP Compatible:** Works with any MCP-enabled AI client.
- **Context Window Integration (Layer Cake):** 4-layer system that automatically injects graph knowledge into agent context windows — File Bridge (CONTEXT.md generation), Associative Hooks (trigger manifest + Claude Code hooks), Anticipatory Engine (auto-discovers trigger bindings), and Process Skills (deliberate recall).

## Optional Debugging

If you want a local graph browser for inspecting Campy data directly, see
[Local Graph Visibility UI](tools/graph_viewer/README.md). It uses the archived official
Kuzu Explorer project, defaults to read-only mode, and stays out of the normal install/runtime
path.

## Requirements

- Python 3.12 or 3.13
- Kùzu 0.11.3

## Quick Start

```bash
campy setup
campy-daemon start
```

For more details, see the [Documentation](docs/).
