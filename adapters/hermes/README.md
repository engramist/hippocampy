# Hermes Agent Adapter for Campy

This adapter integrates the Campy AI memory system with the Hermes agent orchestration framework.

## Overview

Hermes agents can use the `HermesAdapter` to access persistent memory capabilities from Campy, including:

- **Memory Recall**: Search the knowledge graph for relevant facts and lessons
- **Session Recall**: Retrieve a compiled context bundle for broad or multi-entity tasks
- **Spawned-Agent Context**: Get a task-scoped context bundle for Hermes-spawned sub-agents
- **Routing Decisions**: Ask the memory system which recall tool to use
- **Memory Notification**: Notify memory about interactions for future learning
- **Health Checks**: Verify the Campy daemon is running

## Installation

1. Ensure Campy is installed and the Brain Daemon is running
2. The adapter is included with the main Campy package

## Usage

### Basic Setup

```python
from adapters.hermes.adapter import HermesAdapter, get_adapter

# Create adapter instance
adapter = get_adapter({
    "session_id": "my-hermes-agent-001",
    "memory_url": "http://127.0.0.1:7799"
})

if not adapter:
    raise RuntimeError("Failed to initialize Campy adapter")
```

### Recall Memory

```python
# Recall relevant facts about a topic
result = await adapter.recall("What have we learned about customer preferences?")
if result:
    print(f"Relevant memories: {result}")
```

### Session Recall (compiled context bundle)

```python
# Get a full compiled bundle (decisions, constraints, tabular data, summaries)
# for a broad or multi-entity task - use this instead of recall() when the
# task spans more than one topic.
bundle = await adapter.session_recall("brief me on the auth refactor", token_budget=32000)
if bundle:
    print(bundle["bundle"])
```

### Spawned-Agent Context

```python
# When this Hermes agent spawns a sub-agent for a narrower task, give it a
# task-scoped slice of context (smaller default token budget than session_recall).
context = await adapter.spawn_context(
    parent_session_id="my-hermes-agent-001",
    task_description="investigate the failing test",
)
```

### Get Router Recommendation

```python
# Ask Campy which tool to use
recommendation = await adapter.decide("Should I use compile_context or current_truth here?")
if recommendation:
    tool = recommendation.get("recommended_tool")
    print(f"Recommended tool: {tool}")
```

### Notify About Interactions

```python
# Tell Campy about this agent's decision
success = await adapter.notify(
    role="assistant",
    content="I decided to use strategy X based on historical patterns"
)
```

### Health Check

```python
# Verify daemon is running before using adapter
if adapter.health_check():
    print("Memory daemon is healthy")
else:
    print("Warning: Memory daemon is not responding")
```

## Configuration

The adapter accepts the following configuration options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `session_id` | str | "hermes-default" | Session identifier for memory tracking |
| `memory_url` | str | "http://127.0.0.1:7799" | URL of Campy Brain Daemon |

## Architecture

- **MCP Transport**: Uses HTTP REST API endpoints on the Brain Daemon
- **Session Isolation**: Each adapter instance maintains its own session
- **Async Design**: All recall/decision operations are async-compatible
- **Graceful Degradation**: Adapter handles daemon downtime gracefully

## Troubleshooting

### "Connection refused" errors

Ensure the Campy Brain Daemon is running:

```bash
python3 brain_daemon.py
```

Or use the CLI to start it:

```bash
campy daemon start
```

### Memory recall returns None

- Check that the daemon is healthy: `adapter.health_check()`
- Verify the query is well-formed
- Check daemon logs for errors

### Import errors

Ensure the adapter is in the Python path:

```python
import sys
sys.path.insert(0, "/path/to/hippocampy")
from adapters.hermes.adapter import HermesAdapter
```

## API Reference

### HermesAdapter

#### `__init__(memory_url: str = "http://127.0.0.1:7799")`
Initialize the adapter with a memory daemon URL.

#### `configure(config: Dict[str, Any]) -> bool`
Configure the adapter with runtime settings. Returns True if successful.

#### `async recall(query: str, scope: str = "both") -> Optional[Dict[str, Any]]`
Recall relevant memories for a query. Scopes: "both", "lessons", "timeline". Backed by `current_truth` - single-fact lookups.

#### `async session_recall(task_description: str, token_budget: int = 32000, agent_type: str = "generic") -> Optional[Dict[str, Any]]`
Retrieve a compiled context bundle (decisions, constraints, tabular data, summaries). Backed by `compile_context` - use for broad or multi-entity tasks, unlike `recall()`.

#### `async spawn_context(parent_session_id: str, task_description: str, token_budget: int = 8000) -> Optional[Dict[str, Any]]`
Get a task-scoped context bundle for a Hermes-spawned sub-agent. Same `compile_context` backing as `session_recall()`, smaller default token budget.

#### `async decide(query: str) -> Optional[Dict[str, Any]]`
Get routing recommendation from memory system.

#### `async notify(role: str, content: str) -> bool`
Notify memory about a message exchange. Returns True if successful.

#### `async capture_turn(role: str, content: str, session_id: Optional[str] = None) -> bool`
Like `notify()`, with an optional per-call `session_id` override that does not persist past the call.

#### `health_check() -> bool`
Check if the daemon is running and healthy.

### Factory Function

#### `get_adapter(config: Optional[Dict[str, Any]] = None) -> Optional[HermesAdapter]`
Create and configure an adapter instance. Returns None if creation failed.

## Integration with Hermes

Typical Hermes agent integration:

```python
class HermesMemoryAgent:
    def __init__(self):
        self.memory = get_adapter({"session_id": "hermes-agent-001"})
    
    async def decide_action(self, situation: str):
        # Ask memory what we've learned before
        context = await self.memory.recall(situation)
        
        # Ask memory which tool to use
        routing = await self.memory.decide(f"Action for: {situation}")
        
        # Take action...
        
        # Tell memory what we did
        await self.memory.notify("assistant", f"Took action X based on context")
```

## Performance Notes

- REST API calls are async and non-blocking
- Health checks timeout after 2 seconds
- Memory queries return quickly (typically <100ms)
- Session ID helps correlate related interactions

## License

Part of the Campy AI Memory System. See main repository license.

## Support

For issues or questions:
1. Check the main Campy documentation
2. Review daemon logs: `~/.campy/daemon.log`
3. File issues in the main repository
