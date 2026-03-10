"""
brain_daemon.py — SideQuest Brain Daemon

Entry point. On startup:
  1. Load sidequests.toml
  2. Pre-warm sentence-transformers model
  3. Initialize Kùzu schema (idempotent)
  4. Load gist centroids + schema.org routing table
  5. Initialize LLM client (Ollama default; degrades gracefully if unavailable)
  6. Start Loop worker asyncio task (Gated Consolidation Loop, M3+)
  7. Start Unix domain socket IPC server (JSON-RPC 2.0)
  8. Start background sweep asyncio task

IPC: JSON-RPC 2.0 over ~/.sidequests/brain.sock
Concurrency: single asyncio event loop, asyncio.Lock for all Kùzu writes.
"""

import asyncio
import json
import os
import signal
import socket
from pathlib import Path

import uvicorn

from mcp_engine.config import load_config
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.graph import embeddings as emb
from mcp_engine.schema import init_schema
from mcp_engine.tools import TOOL_HANDLERS, init_loop_queue
from mcp_engine.llm.provider import create_llm_client
from mcp_engine.loop import step2_gist, step3_schema_org
from mcp_engine.loop.orchestrator import run_loop

SOCKET_PATH = Path.home() / ".sidequests" / "brain.sock"
DB_PATH     = Path.home() / ".sidequests" / "brain.db"
SEED_PATH   = Path(__file__).parent.parent / (
    "Library/CloudStorage/OneDrive-ChurchofJesusChrist"
    "/my-documents/SideQuest/InvertorsDocs/GistSeedExamples.md"
)


class BrainDaemon:

    def __init__(self, config: dict):
        self.config      = config
        self.db          = KuzuClient(str(DB_PATH))
        self.running     = False
        self._llm_client = None   # set in start()
        self._centroids  = {}     # set in start()
        self._loop_queue: asyncio.Queue = asyncio.Queue()

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

        # Load gist centroids (needed by Step 2 System 1 classifier)
        self._centroids = step2_gist.load_centroids(self.db)
        print(f"Loaded {len(self._centroids)} gist centroids.")

        # Load schema.org routing table into module cache (needed by Step 3)
        step3_schema_org.load_routing_table(self.db)
        print("Loaded schema.org routing table.")

        # Initialize LLM client (degrades gracefully to System 1 if unavailable)
        self._llm_client = create_llm_client(self.config)
        if self._llm_client:
            print(f"LLM provider ready: {self.config.get('llm', {}).get('provider', 'ollama')}")
        else:
            print("LLM provider unavailable. Loop running in System 1 (embedding) only mode.")

        # Wire loop queue into tools module
        init_loop_queue(self._loop_queue)

        # Start Loop worker (Gated Consolidation Loop, M3)
        asyncio.create_task(self._loop_worker())

        # Start background sweep
        sweep_interval = self.config.get("pruning", {}).get("sweep_interval_seconds", 300)
        asyncio.create_task(self._background_sweep(sweep_interval))

        # Start Memory Control Panel web server (M7)
        web_port = self.config.get("web", {}).get("port", 7799)
        asyncio.create_task(self._start_web_server(web_port))

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
    # Gated Consolidation Loop worker (M3)
    # ------------------------------------------------------------------

    async def _loop_worker(self):
        """
        Reads (message_id, text) tuples from the queue and runs the
        Gated Consolidation Loop on each. Runs as a long-lived background task.
        Errors are logged and swallowed — one bad message never kills the worker.
        """
        print("Loop worker started.")
        while True:
            message_id, text = await self._loop_queue.get()
            try:
                summary = await run_loop(
                    message_id=message_id,
                    text=text,
                    db=self.db,
                    llm_client=self._llm_client,
                    config=self.config,
                    centroids=self._centroids,
                )
                print(
                    f"[Loop] msg={message_id[:8]} "
                    f"entities={summary['entities_found']} "
                    f"concepts={summary['concepts_stored']} "
                    f"relations={summary['relations_found']} "
                    f"noise={summary['noise_count']}"
                )
            except Exception as e:
                print(f"[Loop] Error processing message {message_id}: {e}")
            finally:
                self._loop_queue.task_done()

    # ------------------------------------------------------------------
    # Memory Control Panel web server (M7)
    # ------------------------------------------------------------------

    async def _start_web_server(self, port: int):
        """
        Start the FastAPI Memory Control Panel on 127.0.0.1 only.
        Runs as a background asyncio task alongside the IPC server.
        """
        from web.server import create_app
        app = create_app(self.db)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",   # NEVER 0.0.0.0 — local-only by design
            port=port,
            log_level="error",
        )
        server = uvicorn.Server(config)
        print(f"Memory Control Panel: http://127.0.0.1:{port}")
        await server.serve()

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
