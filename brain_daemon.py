"""
brain_daemon.py — HippoCampy Brain Daemon

Entry point. On startup:
  1. Load campy.toml (or legacy sidequests.toml fallback)
  2. Pre-warm sentence-transformers model
  3. Initialize Kùzu schema (idempotent)
  4. Load gist centroids + schema.org routing table
  5. Initialize LLM client (Ollama default; degrades gracefully if unavailable)
  6. Start Loop worker asyncio task (Gated Consolidation Loop, M3+)
  7. Start Unix domain socket IPC server (JSON-RPC 2.0)
  8. Start background sweep asyncio task

IPC: JSON-RPC 2.0 over the active Campy runtime socket.
Concurrency: single asyncio event loop, asyncio.Lock for all Kùzu writes.
"""

import asyncio
import json
import logging
import os
import signal
import socket
from pathlib import Path
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

import uvicorn

from mcp_engine.config import load_config
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.graph import embeddings as emb
from mcp_engine.schema import init_schema
from mcp_engine.tools import TOOL_HANDLERS, init_loop_queue
from mcp_engine.llm.provider import create_llm_client
from mcp_engine.loop import step2_gist, step3_schema_org
from mcp_engine.loop.orchestrator import run_loop
from mcp_engine.sweep import run_sweep
from mcp_engine.dictionary import find_dictionary, load_dictionary, ingest_dictionary
from mcp_engine.activity_log import compact_details, emit_activity
from campy.branding import PRODUCT_NAME, PRIMARY_MCP_SERVER
from campy.paths import get_daemon_socket_path, get_database_path
from mcp_engine.capture import (
    CaptureEvent,
    ClaudeCodeSessionConnector,
    CodexSessionConnector,
    VSCodeChatSessionConnector,
)

SOCKET_PATH = get_daemon_socket_path()
DB_PATH     = get_database_path()
# D3 fix: package-relative seed path — GistSeedExamples.md lives alongside
# the repo, not in a hardcoded OneDrive path that only works on DJ's machine.
SEED_PATH   = Path(__file__).parent / "InvertorsDocs" / "GistSeedExamples.md"


def _socket_path() -> Path:
    """Return the daemon socket path, allowing sandbox-safe overrides."""
    configured = (
        os.environ.get("CAMPY_BRAIN_SOCKET")
        or os.environ.get("CAMPY_SOCKET_PATH")
        or os.environ.get("SIDEQUESTS_BRAIN_SOCKET")
        or os.environ.get("SIDEQUESTS_SOCKET_PATH")
    )
    if configured:
        return Path(configured).expanduser()
    return SOCKET_PATH


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
        print(f"{PRODUCT_NAME} Brain Daemon starting...")

        # Configure embedding provider dispatch (sentence-transformers | ollama | openai)
        emb.configure(self.config)

        # Pre-warm embedder
        embedding_model = self.config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        print(f"Pre-warming embedder: {embedding_model}")
        emb.prewarm(embedding_model)

        # Initialize Kùzu schema (idempotent)
        seed_path = self._resolve_seed_path()
        init_schema(self.db, str(seed_path), embedding_model)

        # B160: Load domain dictionary if present in workspace (pre-seed concepts)
        try:
            workspace_root = self.config.get("workspace_root", ".")
            dict_path = find_dictionary(workspace_root)
            if dict_path:
                entities = load_dictionary(dict_path)
                if entities:
                    now = datetime.now(timezone.utc).isoformat()
                    result = await ingest_dictionary(entities, self.db, now)
                    _logger.info(
                        "B160: Domain dictionary ingested: %d created, %d skipped, %d altLabels",
                        result.get("concepts_created", 0), result.get("concepts_skipped", 0),
                        result.get("alt_labels_added", 0)
                    )
        except Exception:
            _logger.exception("B160: Domain dictionary ingest failed")

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
        emit_activity("daemon", config=self.config, lane="status", status="started")

        # D2 fix: attach done callbacks so task crashes are logged and the task
        # is restarted rather than silently dying.
        def _restart_on_failure(task: asyncio.Task, coro_factory, *args):
            exc = task.exception() if not task.cancelled() else None
            if exc:
                _logger.exception(
                    "Background task '%s' died unexpectedly — restarting",
                    task.get_name(), exc_info=exc,
                )
                new_task = asyncio.create_task(coro_factory(*args),
                                               name=task.get_name())
                new_task.add_done_callback(
                    lambda t: _restart_on_failure(t, coro_factory, *args)
                )

        # Start Loop worker (Gated Consolidation Loop, M3)
        loop_task = asyncio.create_task(self._loop_worker(), name="loop_worker")
        loop_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._loop_worker)
        )

        # Start background sweep
        sweep_interval = self.config.get("pruning", {}).get("sweep_interval_seconds", 300)
        sweep_task = asyncio.create_task(
            self._background_sweep(sweep_interval), name="background_sweep"
        )
        sweep_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._background_sweep, sweep_interval)
        )

        # Start Memory Control Panel web server (M7)
        web_port = self.config.get("web", {}).get("port", 7799)
        web_task = asyncio.create_task(
            self._start_web_server(web_port), name="web_server"
        )
        web_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._start_web_server, web_port)
        )

        # Start durable passive capture connectors. These complement MCP by
        # tailing local transcript files for clients that don't reliably call
        # notify_turn after each model response.
        capture_cfg = self.config.get("capture", {}) or {}
        if capture_cfg.get("enabled", True):
            for source_name, connector_cls in (
                ("codex", CodexSessionConnector),
                ("claude_code", ClaudeCodeSessionConnector),
                ("vscode", VSCodeChatSessionConnector),
            ):
                if (capture_cfg.get(source_name, {}) or {}).get("enabled", True):
                    task = asyncio.create_task(
                        self._background_capture(source_name, connector_cls),
                        name=f"{source_name}_capture",
                    )
                    task.add_done_callback(
                        lambda t, s=source_name, c=connector_cls: _restart_on_failure(
                            t, self._background_capture, s, c
                        )
                    )

        # Start IPC server
        await self._run_ipc_server()

    def _resolve_seed_path(self) -> Path:
        """Find GistSeedExamples.md — check config path dir first, then default."""
        config_dir = Path(self.config.get("_config_path", "campy.toml")).parent
        candidates = [
            config_dir.parent / "InvertorsDocs" / "GistSeedExamples.md",
            SEED_PATH,
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "GistSeedExamples.md not found. Expected alongside campy.toml."
        )

    # ------------------------------------------------------------------
    # IPC Server (JSON-RPC 2.0 over Unix domain socket)
    # ------------------------------------------------------------------

    async def _run_ipc_server(self):
        socket_path = _socket_path()
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Clean up stale socket from previous crash
        if socket_path.exists():
            socket_path.unlink()

        # 4 MB limit — notify_turn payloads can be large (full assistant responses)
        server = await asyncio.start_unix_server(
            self._handle_connection, path=str(socket_path),
            limit=4 * 1024 * 1024,
        )
        self.running = True
        print(f"Brain Daemon listening on {socket_path}")

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

        # MCP protocol introspection methods
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"protocolVersion": "2024-11-05",
                               "serverInfo": {"name": PRIMARY_MCP_SERVER, "version": "0.1.0"},
                               "capabilities": {"tools": {}}}}
        if method == "tools/list":
            tools = [{"name": name} for name in TOOL_HANDLERS]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        handler = TOOL_HANDLERS.get(method)
        if not handler:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            }

        try:
            result = await handler(params, self.db, self.config)
            emit_activity(
                "tool",
                config=self.config,
                method=method,
                status="ok",
                details=compact_details(method, params),
            )
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            emit_activity(
                "tool",
                config=self.config,
                method=method,
                status="error",
                details={
                    **compact_details(method, params),
                    "error": str(e)[:160],
                },
            )
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    # ------------------------------------------------------------------
    # Gated Consolidation Loop worker (M3)
    # ------------------------------------------------------------------

    async def _loop_worker(self):
        """
        Reads (message_id, text, role, session_id, precomputed) tuples from the queue and
        runs the Gated Consolidation Loop on each. Runs as a background task.
        """
        print("Loop worker started.")
        while True:
            # B108: Added precomputed to queue tuple
            item = await self._loop_queue.get()
            # Handle both 4-tuple (old) and 5-tuple (new) for compatibility
            if len(item) == 4:
                message_id, text, role, session_id = item
                precomputed = None
            else:
                message_id, text, role, session_id, precomputed = item

            try:
                print(f"[Loop] Processing ({role}): {text[:120]!r}")
                summary = await run_loop(
                    message_id=message_id,
                    text=text,
                    role=role,
                    db=self.db,
                    llm_client=self._llm_client,
                    config=self.config,
                    centroids=self._centroids,
                    session_id=session_id,
                    precomputed=precomputed,
                )
                print(
                    f"[Loop] msg={message_id[:8]} "
                    f"entities={summary['entities_found']} "
                    f"concepts={summary['concepts_stored']} "
                    f"relations={summary['relations_found']} "
                    f"noise={summary['noise_count']}"
                )

                # B14: Persist loop summary to Session node
                if summary and session_id != "unknown":
                    try:
                        await self.db.execute_write(
                            "MATCH (s:Session {session_id: $sid}) "
                            "SET s.last_loop_summary = $summary",
                            {"sid": session_id, "summary": json.dumps(summary)}
                        )
                    except Exception:
                        pass  # Non-critical

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
    # Background sweep — Synaptic Pruning + Hebbian Trigger 2
    # ------------------------------------------------------------------

    async def _background_sweep(self, interval_seconds: int):
        """
        Periodic sweep: pathway decay, archive, resurrection, Hebbian Trigger 2.
        Runs per-table to keep write-lock windows short.
        First run is deferred by one full interval to let the daemon warm up.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                summary = await run_sweep(
                    db=self.db,
                    config=self.config,
                    llm_client=self._llm_client,
                )
                print(
                    f"[Sweep] decayed={summary['decayed']} "
                    f"archived={summary['archived']} "
                    f"resurrected={summary['resurrected']} "
                    f"promoted={summary['promoted']} "
                    f"centroids={summary.get('centroids_updated', 0)} "
                    f"errors={summary['errors']}"
                )
            except Exception as e:
                print(f"[Sweep] Error during sweep: {e}")

    # ------------------------------------------------------------------
    # Durable passive capture
    # ------------------------------------------------------------------

    async def _background_capture(self, source_name: str, connector_cls):
        capture_cfg = self.config.get("capture", {}) or {}
        source_cfg = capture_cfg.get(source_name, {}) or {}
        interval = float(source_cfg.get("scan_interval_seconds", 10))
        connector = connector_cls(
            sessions_root=source_cfg.get("sessions_root") or None,
            max_events_per_scan=int(source_cfg.get("max_events_per_scan", 50)),
            initial_backfill_events=int(source_cfg.get("initial_backfill_events", 20)),
            max_initial_backfill_files=int(source_cfg.get("max_initial_backfill_files", 1)),
        )

        async def ingest(event: CaptureEvent):
            params = event.notify_params()
            params["precomputed"] = {
                "capture_event_id": event.event_id,
                "source_app": event.source_app,
                "source_path": event.source_path,
                "source_offset": event.source_offset,
            }
            handler = TOOL_HANDLERS["notify_turn"]
            await handler(params, self.db, self.config)

        while True:
            try:
                summary = await connector.scan_once(ingest=ingest)
                if summary["journaled"] or summary["ingested"]:
                    emit_activity(
                        "capture",
                        config=self.config,
                        lane="write",
                        status="ok",
                        details={
                            "source": source_name,
                            "scanned": summary["scanned"],
                            "journaled": summary["journaled"],
                            "ingested": summary["ingested"],
                        },
                    )
                    print(
                        f"[Capture:{source_name}] "
                        f"scanned={summary['scanned']} "
                        f"journaled={summary['journaled']} "
                        f"ingested={summary['ingested']}"
                    )
            except Exception as e:
                emit_activity(
                    "capture",
                    config=self.config,
                    lane="write",
                    status="error",
                    details={"source": source_name, "error": str(e)[:160]},
                )
                print(f"[Capture:{source_name}] Error during scan: {e}")
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self.running = False
        self.db.close()
        socket_path = _socket_path()
        if socket_path.exists():
            socket_path.unlink()
        emit_activity("daemon", config=self.config, lane="status", status="stopped")
        print("Brain Daemon stopped.")
        # D1 fix: stop the event loop so the process exits cleanly.
        try:
            asyncio.get_running_loop().stop()
        except RuntimeError:
            pass


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
