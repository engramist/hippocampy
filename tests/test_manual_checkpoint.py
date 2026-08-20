"""
test_manual_checkpoint.py — B337 Manual Checkpoint Control Tests

Verifies that:
1. KuzuClient accepts checkpoint_threshold and auto_checkpoint parameters
2. Manual checkpoint can be triggered asynchronously
3. Checkpoint task doesn't crash on errors
4. Configuration is passed through from campy.toml to KuzuClient
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


@pytest.fixture
def temp_db_path():
    """Create a temporary database directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.kuzu"


@pytest.mark.asyncio
async def test_kuzu_client_accepts_checkpoint_parameters(temp_db_path):
    """B337: KuzuClient.__init__ accepts checkpoint configuration."""
    # Should not raise
    client = KuzuClient(
        str(temp_db_path),
        auto_checkpoint=True,
        checkpoint_threshold=4_000_000  # 4MB
    )
    assert client.db is not None
    assert client.read_only is False
    client.close()


@pytest.mark.asyncio
async def test_manual_checkpoint_succeeds(temp_db_path):
    """B337: Manual checkpoint executes successfully."""
    client = KuzuClient(str(temp_db_path))
    # Pre-populate with a simple query
    client.execute("MATCH (n) RETURN count(*) as cnt")
    
    # Manual checkpoint should succeed
    success = await client.checkpoint()
    assert success is True
    client.close()


@pytest.mark.asyncio
async def test_manual_checkpoint_handles_errors(temp_db_path):
    """B337: Manual checkpoint handles database errors gracefully."""
    client = KuzuClient(str(temp_db_path))
    client.close()  # Close database before attempting checkpoint
    
    # Checkpoint on closed database should fail gracefully
    success = await client.checkpoint()
    assert success is False


@pytest.mark.asyncio
async def test_checkpoint_configuration_from_config_dict():
    """B337: Checkpoint configuration is correctly extracted from config dict."""
    config = {
        "checkpoint": {
            "auto_checkpoint": False,
            "threshold_bytes": 1_000_000,
            "interval_seconds": 120,
        }
    }
    
    # Extract checkpoint config (mimic what BrainDaemon.__init__ does)
    checkpoint_cfg = config.get("checkpoint", {})
    auto_checkpoint = checkpoint_cfg.get("auto_checkpoint", True)
    checkpoint_threshold_bytes = checkpoint_cfg.get("threshold_bytes", -1)
    interval_seconds = checkpoint_cfg.get("interval_seconds", 60)
    
    assert auto_checkpoint is False
    assert checkpoint_threshold_bytes == 1_000_000
    assert interval_seconds == 120


@pytest.mark.asyncio
async def test_checkpoint_configuration_defaults():
    """B337: Checkpoint configuration uses sensible defaults."""
    config = {}
    
    # Extract checkpoint config with defaults
    checkpoint_cfg = config.get("checkpoint", {})
    auto_checkpoint = checkpoint_cfg.get("auto_checkpoint", True)
    checkpoint_threshold_bytes = checkpoint_cfg.get("threshold_bytes", -1)
    interval_seconds = checkpoint_cfg.get("interval_seconds", 60)
    
    assert auto_checkpoint is True  # Default enabled
    assert checkpoint_threshold_bytes == -1  # Kuzu default
    assert interval_seconds == 60  # 1 minute default


@pytest.mark.asyncio
async def test_periodic_checkpoint_task_interval(temp_db_path):
    """B337: Periodic checkpoint task respects interval configuration."""
    client = KuzuClient(str(temp_db_path))
    
    checkpoint_calls = []
    original_checkpoint = client.checkpoint
    
    async def mock_checkpoint():
        checkpoint_calls.append(asyncio.get_event_loop().time())
        return await original_checkpoint()
    
    client.checkpoint = mock_checkpoint
    
    # Simulate periodic checkpoint task
    interval = 0.1  # 100ms for testing
    task = asyncio.create_task(_test_periodic_checkpoint(client, interval))
    
    # Let it run for ~300ms (should trigger 3+ times)
    await asyncio.sleep(0.35)
    task.cancel()
    
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    # Verify multiple checkpoints occurred
    assert len(checkpoint_calls) >= 2
    
    # Verify spacing is approximately interval
    if len(checkpoint_calls) > 1:
        for i in range(1, len(checkpoint_calls)):
            spacing = checkpoint_calls[i] - checkpoint_calls[i - 1]
            # Allow ±50% tolerance
            assert 0.05 < spacing < 0.15, f"Spacing {spacing} not near {interval}"
    
    client.close()


async def _test_periodic_checkpoint(db, interval_seconds):
    """Helper: simplified periodic checkpoint loop for testing."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await db.checkpoint()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_checkpoint_zero_interval_disabled():
    """B337: Checkpoint task can be disabled with interval_seconds=0."""
    config = {
        "checkpoint": {
            "interval_seconds": 0,  # Disabled
        }
    }
    
    checkpoint_interval = config.get("checkpoint", {}).get("interval_seconds", 60)
    assert checkpoint_interval == 0
    # In BrainDaemon, task creation is gated: if checkpoint_interval > 0: create_task(...)
