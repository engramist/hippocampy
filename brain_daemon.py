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
import collections
import gc
import json
import logging
import os
import resource
import signal
import socket
from pathlib import Path
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

import uvicorn

from campy.brain.brainstem.config import load_config
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools import TOOL_HANDLERS, init_loop_queue
from campy.brain.llm.provider import create_llm_client
from campy.brain.temporal_lobe.loop import step2_gist, step3_schema_org
from campy.brain.temporal_lobe.loop.orchestrator import run_loop
from campy.brain.brainstem.sweep import run_sweep
from campy.brain.temporal_lobe.dictionary import find_dictionary, load_dictionary, ingest_dictionary
from campy.brain.brainstem.activity_log import compact_details, emit_activity
from campy.branding import PRODUCT_NAME, PRIMARY_MCP_SERVER
from campy.paths import get_daemon_socket_path, get_database_path
from campy.brain.sensory_cortex.capture import (
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
        # B337: Extract checkpoint tuning from config (memory spike mitigation)
        checkpoint_cfg = config.get("checkpoint", {})
        auto_checkpoint = checkpoint_cfg.get("auto_checkpoint", True)
        checkpoint_threshold_bytes = checkpoint_cfg.get("threshold_bytes", -1)
        self.db = KuzuClient(
            str(DB_PATH),
            auto_checkpoint=auto_checkpoint,
            checkpoint_threshold=checkpoint_threshold_bytes
        )
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

        # B337: Start periodic checkpoint task (memory spike mitigation)
        # Decouples checkpoint cadence from transaction commit boundaries,
        # allowing tuned checkpoints independent of write load.
        checkpoint_interval = self.config.get("checkpoint", {}).get("interval_seconds", 60)
        if checkpoint_interval > 0:
            checkpoint_task = asyncio.create_task(
                self._periodic_checkpoint(checkpoint_interval), name="periodic_checkpoint"
            )
            checkpoint_task.add_done_callback(
                lambda t: _restart_on_failure(t, self._periodic_checkpoint, checkpoint_interval)
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
        """Route JSON-RPC method calls to tool handlers in campy/brain/thalamus/tools.py."""
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
                    f"patterns={summary.get('patterns_discovered', 0)} "
                    f"errors={summary['errors']}"
                )
            except Exception as e:
                print(f"[Sweep] Error during sweep: {e}")

    async def _periodic_checkpoint(self, interval_seconds: int):
        """
        B337: Periodic manual checkpoint to decouple checkpoint cadence from
        transaction commit boundaries. Mitigates memory spikes during write-heavy phases
        by forcing checkpoints independent of WAL threshold triggers.
        
        First run is deferred by one full interval to let the daemon warm up.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                success = await self.db.checkpoint()
                if success:
                    _logger.info("[Checkpoint] Manual checkpoint completed")
                else:
                    _logger.warning("[Checkpoint] Manual checkpoint failed")
            except Exception as e:
                _logger.exception("[Checkpoint] Unexpected error during checkpoint: %s", e)

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
# B343/B344: on-demand, in-process memory diagnostic (no external attach
# needed -- a process can always introspect itself; this sidesteps macOS's
# task_for_pid/sudo requirement for external profilers like py-spy).
# Trigger with: kill -USR1 <pid>
# Output: ~/.campy/memory_debug.log (created on first trigger)
#
# Deliberately does NOT use tracemalloc. It was tried and reverted, twice,
# on this exact daemon, 2026-08-21 -- kept here so it isn't tried a third
# time:
#   1. tracemalloc.start() unconditionally at process launch made a live
#      restart hang at ~98% CPU, unhealthy, for over a minute. Root cause:
#      it's expensive during the startup phase's allocation-heavy schema
#      init + embedding model load -- measured in isolation afterward,
#      tracemalloc.start(10) made schema init alone take 96s instead of 2s
#      (43x slower).
#   2. Fixed by starting tracemalloc lazily on first SIGUSR1 instead, well
#      after startup -- this looked safe (verified via a careful restart)
#      but left tracemalloc running continuously afterward, since nothing
#      ever called tracemalloc.stop(). ~24 minutes later the same daemon
#      was found pegged at 100%+ CPU and unresponsive again. Confirmed by
#      isolated test that lower depth doesn't fix it either: even
#      tracemalloc.start(1), the minimum, was ~8x slower on the same
#      schema-init benchmark (17.9s vs 2.2s) -- the overhead comes from
#      instrumenting every allocation, not primarily from traceback depth.
#      tracemalloc is not compatible with this daemon's allocation-heavy
#      workload (embedding model, KuzuDB's C++ extension) at any depth,
#      for continuous use.
#
# What this diagnostic does instead: gc.get_objects(), grouped by type
# name. Far coarser than a real allocation-site profile (it can show "N
# more dict objects than last time", not which line created them), but it
# is a single pass over already-live objects -- no per-allocation
# instrumentation, no ongoing cost after the call returns. Safe to leave
# wired up permanently. If a real allocation-site profile is ever needed,
# that requires a deliberate, supervised session against a disposable
# instance (not this shared daemon) with tracemalloc enabled for a known,
# bounded, consented window -- not something to wire into a signal handler
# on the production process again.
# ---------------------------------------------------------------------------

_MEMORY_DEBUG_LOG = Path.home() / ".campy" / "memory_debug.log"
_last_type_counts = None


def _dump_memory_snapshot():
    """B343/B344: on-demand snapshot, triggered by `kill -USR1 <pid>`.

    Cheap by construction (see the module comment above for why tracemalloc
    is deliberately not used here): RSS high-water mark, total gc object
    count, and top object-type counts, diffed against the previous trigger
    if there was one.
    """
    global _last_type_counts

    now = datetime.now(timezone.utc).isoformat()
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS, KB on Linux

    objects = gc.get_objects()
    obj_count = len(objects)
    type_counts = collections.Counter(type(o).__name__ for o in objects)
    del objects  # don't hold the whole live-object list any longer than needed

    lines = [
        f"=== memory snapshot {now} ===",
        f"ru_maxrss={rss_kb} (bytes on macOS, KB on Linux -- high-water mark, not current RSS)",
        f"gc object count={obj_count}",
        "",
        "-- top 15 object types by count --",
    ]
    for type_name, count in type_counts.most_common(15):
        lines.append(f"{type_name}: {count}")

    if _last_type_counts is not None:
        lines.append("")
        lines.append("-- top 15 type-count growth since last snapshot --")
        deltas = collections.Counter()
        for type_name, count in type_counts.items():
            delta = count - _last_type_counts.get(type_name, 0)
            if delta != 0:
                deltas[type_name] = delta
        for type_name, delta in deltas.most_common(15):
            lines.append(f"{type_name}: {'+' if delta > 0 else ''}{delta}")
    else:
        lines.append("")
        lines.append("(no prior snapshot -- this is the first dump, nothing to diff against yet)")

    lines.append("")
    _last_type_counts = type_counts

    _MEMORY_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_MEMORY_DEBUG_LOG, "a") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[MemoryDebug] Snapshot written to {_MEMORY_DEBUG_LOG}", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    config = load_config()
    daemon = BrainDaemon(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.shutdown)
    # B343/B344: SIGUSR1 triggers an in-process memory snapshot -- a plain
    # gc.get_objects() type-count pass, negligible cost, safe to leave
    # wired up permanently. See the comment above _dump_memory_snapshot
    # for why this deliberately does NOT use tracemalloc.
    loop.add_signal_handler(signal.SIGUSR1, _dump_memory_snapshot)

    await daemon.start()


if __name__ == "__main__":
    asyncio.run(main())
