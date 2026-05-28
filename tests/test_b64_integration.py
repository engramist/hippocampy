
import os
import shutil
import pytest
import asyncio
import uuid
from datetime import datetime, timezone
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools import notify_turn, context_status

@pytest.mark.asyncio
async def test_b64_integration_message_count():
    """
    B64 Integration Test:
    1. notify_turn 5 times -> stats show message_count = 5
    2. Archived messages are not counted.
    3. Handles messages without 'archived' property (simulated via older creation).
    """
    db_path = "./test_b64_integration_final.db"
    if os.path.exists(db_path):
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        else:
            os.remove(db_path)
            
    db = KuzuClient(db_path)
    
    # Init schema
    seed_path = "InvertorsDocs/GistSeedExamples.md"
    embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
    init_schema(db, seed_path, embedding_model)
    
    config = {
        "embeddings": {"model": embedding_model},
        "ingestion": {"max_ingest_chars": 4000}
    }
    session_id = f"test-session-{uuid.uuid4()}"
    
    # AC3: notify_turn 5 times
    for i in range(5):
        await notify_turn({
            "role": "user",
            "content": f"Message {i}",
            "session_id": session_id,
            "repo_root": "/tmp/fake-repo"
        }, db, config)
        
    stats = await context_status({"session_id": session_id}, db, config)
    assert stats["message_count"] == 5
    
    # AC2: Archive one message and verify count drops to 4
    # We need to find one message ID linked to this session
    r = db.execute(
        "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
        "RETURN m.message_id LIMIT 1",
        {"sid": session_id}
    )
    msg_id = r.get_next()[0]
    
    await db.execute_write(
        "MATCH (m:Message {message_id: $mid}) SET m.archived = true",
        {"mid": msg_id}
    )
    
    stats = await context_status({"session_id": session_id}, db, config)
    assert stats["message_count"] == 4
    
    # Verify NULL archived (simulated)
    msg_id_2 = str(uuid.uuid4())
    await db.execute_write(
        "CREATE (m:Message {message_id: $mid, text_raw: 'null msg', created_at: timestamp($now)})",
        {"mid": msg_id_2, "now": datetime.now(timezone.utc).isoformat()}
    )
    await db.execute_write(
        "MATCH (s:Session {session_id: $sid}), (m:Message {message_id: $mid}) "
        "MERGE (m)-[:SENT_IN]->(s)",
        {"sid": session_id, "mid": msg_id_2}
    )
    
    # Total active: 4 (from notify_turn) + 1 (manual NULL) = 5
    stats = await context_status({"session_id": session_id}, db, config)
    assert stats["message_count"] == 5

    db.close()
    if os.path.exists(db_path):
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        else:
            os.remove(db_path)
