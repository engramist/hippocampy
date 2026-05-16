# HippoCampy

Persistent AI memory system with a Gated Consolidation Loop and graph-native Kùzu database.

**Patent Pending:** Campy includes patent-pending memory architecture. A U.S. provisional application was filed March 25, 2026 (Application #64/017,066). No patent has been granted. See [docs/nonprovisional-strategy.md](docs/nonprovisional-strategy.md) for filing facts and deadline.

## Installation

Current recommended path for private testing and work-machine installs is the source install path:

```bash
git clone git@github.com:djs54/hippocampy.git
cd hippocampy
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
campy install
campy status
campy activity --follow
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
