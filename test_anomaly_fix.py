#!/usr/bin/env python3
"""Quick test to verify the get_anomalies fix."""

import asyncio
from mcp_engine.graph.kuzu_client import KuzuClient
from pathlib import Path

async def test():
    db_path = Path.home() / ".sidequests" / "brain_test_anomaly.db"
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if db_path.exists():
        import shutil
        shutil.rmtree(db_path)
    
    db = KuzuClient(str(db_path))
    
    # Test get_anomalies with different scope values
    from mcp_engine.tools import get_anomalies
    
    print("=== Test 1: branch scope with quest_id ===")
    result = await get_anomalies({"scope": "branch", "quest_id": "test-quest", "limit": 5}, db, {})
    print(f"Result: {result}")
    
    print("\n=== Test 2: branch scope without quest_id ===")
    result = await get_anomalies({"scope": "branch", "limit": 5}, db, {})
    print(f"Result: {result}")
    
    print("\n=== Test 3: global scope ===")
    result = await get_anomalies({"scope": "global", "limit": 5}, db, {})
    print(f"Result: {result}")
    
    print("\nAll tests passed - no parameter binding errors!")

if __name__ == "__main__":
    asyncio.run(test())
