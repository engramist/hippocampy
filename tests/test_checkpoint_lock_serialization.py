"""
B337: Test checkpoint lock serialization to prevent races with in-flight writes.

The checkpoint() method must hold the same per-db write lock as execute_write()
to ensure writes don't overlap with checkpoint boundaries.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient, _get_write_lock

# Reduce noise during testing
logging.getLogger("campy.brain.hippocampus.graph.kuzu_client").setLevel(
    logging.WARNING
)


@pytest.fixture
def temp_kuzu_db():
    """Temporary directory for Kuzu database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.kuzu"


@pytest.mark.asyncio
async def test_checkpoint_holds_write_lock(temp_kuzu_db):
    """Verify checkpoint() acquires the same write lock as execute_write().
    
    This test verifies the B337 fix: checkpoint must not bypass write
    serialization. The test:
    1. Starts checkpoint running
    2. While checkpoint holds the lock, tries to acquire it from a concurrent task
    3. Verifies the concurrent task blocks (cannot acquire the lock)
    4. Verifies the concurrent task succeeds once checkpoint releases the lock
    
    If checkpoint didn't hold the lock, the concurrent task would acquire it
    immediately and the test would fail.
    """
    import time as time_module
    client = KuzuClient(str(temp_kuzu_db))
    lock = _get_write_lock(str(temp_kuzu_db))
    
    # Event to signal when checkpoint's execute() is running
    checkpoint_executing = asyncio.Event()
    
    original_execute = client.execute
    checkpoint_call_count = [0]
    
    def mock_execute(query, params=None):
        if "CHECKPOINT" in query:
            checkpoint_call_count[0] += 1
            # Signal that checkpoint is in execute()
            checkpoint_executing.set()
            # Simulate checkpoint work (0.5 seconds)
            time_module.sleep(0.5)
        return original_execute(query, params)
    
    client.execute = mock_execute
    
    # Start checkpoint in the background
    checkpoint_task = asyncio.create_task(client.checkpoint())
    
    # Wait for checkpoint to enter execute()
    await asyncio.wait_for(checkpoint_executing.wait(), timeout=2.0)
    
    # At this point, checkpoint should be sleeping in its thread, holding the lock.
    # Try to acquire it with a short timeout. Should timeout if lock is held.
    lock_acquired_while_checkpoint_running = False
    
    try:
        async with asyncio.timeout(0.2):
            async with lock:
                lock_acquired_while_checkpoint_running = True
    except asyncio.TimeoutError:
        # Expected: checkpoint was holding the lock
        lock_acquired_while_checkpoint_running = False
    
    # Verify the lock was NOT acquired (because checkpoint held it)
    assert not lock_acquired_while_checkpoint_running, (
        "Concurrent task acquired lock while checkpoint() was running. "
        "This means checkpoint() is NOT properly holding the write lock."
    )
    
    # Wait for checkpoint to complete
    result = await asyncio.wait_for(checkpoint_task, timeout=2.0)
    assert result is True, "checkpoint() should return True on success"
    assert checkpoint_call_count[0] == 1, "checkpoint should have been called once"


@pytest.mark.asyncio
async def test_checkpoint_returns_true_on_success(temp_kuzu_db):
    """Verify checkpoint() returns True on successful execution."""
    client = KuzuClient(str(temp_kuzu_db))
    result = await client.checkpoint()
    assert result is True, "checkpoint() should return True on success"


@pytest.mark.asyncio
async def test_checkpoint_returns_false_on_error(temp_kuzu_db):
    """Verify checkpoint() returns False when an error occurs."""
    client = KuzuClient(str(temp_kuzu_db))
    
    # Patch execute to raise an error
    def mock_execute_error(query, params=None):
        if "CHECKPOINT" in query:
            raise RuntimeError("Mock checkpoint error")
        return MagicMock()
    
    client.execute = mock_execute_error
    
    result = await client.checkpoint()
    assert result is False, "checkpoint() should return False on error"


@pytest.mark.asyncio
async def test_checkpoint_error_logged(temp_kuzu_db):
    """Verify checkpoint errors are logged."""
    client = KuzuClient(str(temp_kuzu_db))
    
    error_msg = "Test checkpoint error"
    
    def mock_execute_error(query, params=None):
        if "CHECKPOINT" in query:
            raise RuntimeError(error_msg)
        return MagicMock()
    
    client.execute = mock_execute_error
    
    with patch("logging.getLogger") as mock_logger:
        mock_log_instance = MagicMock()
        mock_logger.return_value = mock_log_instance
        
        result = await client.checkpoint()
        
        assert result is False
        # Verify warning was logged
        mock_log_instance.warning.assert_called_once()
        call_args = mock_log_instance.warning.call_args
        assert error_msg in str(call_args)
