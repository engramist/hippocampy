#!/usr/bin/env python3
"""Debug script to test LocalBrainClient."""

import asyncio
import traceback
from benchmarks.arc3.adapter import LocalBrainClient
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.config import load_config
from pathlib import Path

async def test():
    config = load_config()
    db_path = Path.home() / ".sidequests" / "brain_test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    db = KuzuClient(str(db_path))
    client = LocalBrainClient(db, config)
    
    print("=== Testing analogical_search ===")
    try:
        result = await client.analogical_search(
            query="test",
            current_quest_id="",
            limit=3,
            min_similarity=0.35
        )
        print("Result:", result)
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
