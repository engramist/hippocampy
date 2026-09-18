import os
import shutil
import pytest
import asyncio
import uuid
from datetime import datetime, timezone
from campy.brain.hippocampus.graph.oxigraph_client import CAMPY_NS, OxigraphClient
from campy.brain.hippocampus.graph.vector_store import mint_uri
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

    db = OxigraphClient(db_path)

    # Init schema
    seed_path = "campy/data/GistSeedExamples.md"
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
    rows = list(db.store.query(
        f'PREFIX campy: <{CAMPY_NS}> '
        f'SELECT ?message_id WHERE {{ '
        f'  ?m campy:SENT_IN ?s . ?s campy:session_id "{session_id}" . '
        f'  ?m campy:message_id ?message_id . '
        f'}} LIMIT 1'
    ))
    msg_id = rows[0]["message_id"].value

    db.store.update(
        f'PREFIX campy: <{CAMPY_NS}> '
        f'DELETE {{ ?m campy:archived ?old . }} '
        f'INSERT {{ ?m campy:archived true . }} '
        f'WHERE {{ ?m campy:message_id "{msg_id}" . OPTIONAL {{ ?m campy:archived ?old }} }}'
    )

    stats = await context_status({"session_id": session_id}, db, config)
    assert stats["message_count"] == 4

    # Verify NULL archived (simulated)
    msg_id_2 = str(uuid.uuid4())
    db.write_node("Message", {
        "message_id": msg_id_2, "text_raw": "null msg",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.write_edge("SENT_IN", mint_uri("Message", msg_id_2), mint_uri("Session", session_id), None)

    # Total active: 4 (from notify_turn) + 1 (manual NULL) = 5
    stats = await context_status({"session_id": session_id}, db, config)
    assert stats["message_count"] == 5

    db.close()
    if os.path.exists(db_path):
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        else:
            os.remove(db_path)
