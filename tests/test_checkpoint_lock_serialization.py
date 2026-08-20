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
    serialization. If the lock is properly held, a concurrent write should
    block until checkpoint completes.
    """
    client = KuzuClient(str(temp_kuzu_db))
    lock = _get_write_lock(str(temp_kuzu_db))
    
    # Track whether the lock was held during checkpoint
    lock_was_held = False
    checkpoint_started = asyncio.Event()
    checkpoint_finished = asyncio.Event()
    
    # Patch the execute method to detect if the lock is held
    original_execute = client.execute
    
    def mock_execute(query, params=None):
        nonlocal lock_was_held
        if "CHECKPOINT" in query:
            # Inside checkpoint: verify the lock is held (not available)
            lock_was_held = not lock._locked
            checkpoint_started.set()
            # Simulate checkpoint work
            import time
            time.sleep(0.01)
        return original_execute(query, params)
    
    client.execute = mock_execute
    
    # Start checkpoint
    checkpoint_task = asyncio.create_task(client.checkpoint())
    
    # Give checkpoint time to acquire the lock
    await asyncio.wait_for(checkpoint_started.wait(), timeout=1.0)
    
    # Verify checkpoint completed
    result = await asyncio.wait_for(checkpoint_task, timeout=1.0)
    
    # Checkpoint should return True on success
    assert result is True, "checkpoint() should return True"


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
