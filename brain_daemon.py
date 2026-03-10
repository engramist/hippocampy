"""
brain_daemon.py — SideQuest Brain Daemon

Entry point. On startup:
  1. Load sidequests.toml
  2. Pre-warm sentence-transformers model
  3. Initialize Kùzu schema (idempotent)
  4. Start Unix domain socket IPC server (JSON-RPC 2.0)
  5. Start background sweep asyncio task

IPC: JSON-RPC 2.0 over ~/.sidequests/brain.sock
Concurrency: single asyncio event loop, asyncio.Lock for all Kùzu writes.
"""

import asyncio
import json
import os
import signal
import socket
from pathlib import Path

from mcp_engine.config import load_config
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.graph import embeddings as emb
from mcp_engine.schema import init_schema
from mcp_engine.tools import TOOL_HANDLERS

SOCKET_PATH = Path.home() / ".sidequests" / "brain.sock"
DB_PATH     = Path.home() / ".sidequests" / "brain.db"
SEED_PATH   = Path(__file__).parent.parent / (
    "Library/CloudStorage/OneDrive-ChurchofJesusChrist"
    "/my-documents/SideQuest/InvertorsDocs/GistSeedExamples.md"
)


class BrainDaemon:

    def __init__(self, config: dict):
        self.config = config
        self.db = KuzuClient(str(DB_PATH))
        self.running = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self):
        print("SideQuest Brain Daemon starting...")

        # Pre-warm embedder (loads ~90MB model into memory)
        embedding_model = self.config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        print(f"Pre-warming embedder: {embedding_model}")
        emb.prewarm(embedding_model)

        # Initialize Kùzu schema (idempotent)
        seed_path = self._resolve_seed_path()
        init_schema(self.db, str(seed_path), embedding_model)

        # Start background sweep
        sweep_interval = self.config.get("pruning", {}).get("sweep_interval_seconds", 300)
        asyncio.create_task(self._background_sweep(sweep_interval))

        # Start IPC server
        await self._run_ipc_server()

    def _resolve_seed_path(self) -> Path:
        """Find GistSeedExamples.md — check config path dir first, then default."""
        config_dir = Path(self.config.get("_config_path", "sidequests.toml")).parent
        candidates = [
            config_dir.parent / "InvertorsDocs" / "GistSeedExamples.md",
            SEED_PATH,
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "GistSeedExamples.md not found. Expected alongside sidequests.toml."
        )

    # ------------------------------------------------------------------
    # IPC Server (JSON-RPC 2.0 over Unix domain socket)
    # ------------------------------------------------------------------

    async def _run_ipc_server(self):
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Clean up stale socket from previous crash
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        server = await asyncio.start_unix_server(
            self._handle_connection, path=str(SOCKET_PATH)
        )
        self.running = True
        print(f"Brain Daemon listening on {SOCKET_PATH}")

        async with server:
            await server.serve_forever()

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle a single adapter connection. Reads newline-delimited JSON-RPC 2.0."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line)
                    response = await self._dispatch(request)
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
                except json.JSONDecodeError:
                    error_response = {
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}
                    }
                    writer.write((json.dumps(error_response) + "\n").encode())
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch(self, request: dict) -> dict:
        """Route JSON-RPC method calls to tool handlers in mcp_engine/tools.py."""
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        handler = TOOL_HANDLERS.get(method)
        if not handler:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            }

        try:
            result = await handler(params, self.db, self.config)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    # ------------------------------------------------------------------
    # Background sweep (M4 — stub for now)
    # ------------------------------------------------------------------

    async def _background_sweep(self, interval_seconds: int):
        """
        Periodic sweep: confidence re-scoring + pathway decay + archive + resurrection.
        Runs per-table to keep write-lock windows short.
        # Implementation note: acquire write lock per table, not one giant transaction.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            # TODO M4: implement sweep
            pass

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self.running = False
        self.db.close()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        print("Brain Daemon stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    config = load_config()
    daemon = BrainDaemon(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.shutdown)

    await daemon.start()


if __name__ == "__main__":
    asyncio.run(main())
