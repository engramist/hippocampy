#!/usr/bin/env python3
"""Test submission runner for a small ARC puzzle batch."""


import argparse
import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path

from benchmarks.arc3.adapter import LocalBrainClient
from agents.arc3.runner import DurableARCRunner
from benchmarks.arc3.harness import ARC3Harness, load_tasks_from_manifest
from benchmarks.harness import BenchmarkConfig
from mcp_engine.config import load_config
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import init_schema
from mcp_engine.graph import embeddings as emb
from mcp_engine.tools import init_loop_queue
from mcp_engine.loop.step2_gist import load_centroids
from mcp_engine.loop.step3_schema_org import load_routing_table

# Configuration paths
REPO_ROOT = Path(__file__).resolve().parents[0]
CONFIG_PATH = REPO_ROOT / "sidequests.toml"
MANIFEST_PATH = REPO_ROOT / "benchmarks/arc3/tasks_manifest.json"
DB_PATH = Path.home() / ".sidequests" / "brain_single_test.db"
SEED_PATH = REPO_ROOT / "sidequests/data/GistSeedExamples.md"
TASK_BATCH_SIZE = 5
FINAL_OUTPUT_PATH = REPO_ROOT / "submission_results_single.json"
ARC_SERVER_OUTPUT_PATH = REPO_ROOT / "submission_results_arcServer.json"
AGENT_EXECUTION_TRACE_PATH = REPO_ROOT / "agent_execution_trace.json"
MASTER_TIMELINE_PATH = REPO_ROOT / "master_timeline.json"
LIVE_OUTPUT_PATH = REPO_ROOT / "submission_results_single.live.jsonl"
ARC_KEY_PATHS = (
    REPO_ROOT / "benchmarks/.arc/arc.json",
    REPO_ROOT / "benchmarks/arc3/.arc/arc.json",
)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _apply_llm_overrides(config: dict, overrides: dict | None = None) -> dict:
    """Return a config copy with one-shot LLM overrides applied."""
    if not overrides:
        return config

    merged = dict(config)
    llm_cfg = dict(config.get("llm", {}))
    for key, value in overrides.items():
        if value is not None:
            llm_cfg[key] = value
    merged["llm"] = llm_cfg
    return merged


def _remove_db_artifacts(db_path: Path) -> None:
    """Delete the local smoke-test database and any SQLite/Kùzu sidecars."""
    import shutil

    candidates = [
        db_path,
        Path(f"{db_path}.wal"),
        Path(f"{db_path}.shm"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]
    for candidate in candidates:
        if candidate.exists():
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()


def _ensure_arc_api_key(arc_key_path: str | Path | None = None) -> str | None:
    """Populate ARC_API_KEY from the repo credential file when the env var is absent."""
    existing = (os.environ.get("ARC_API_KEY") or "").strip()
    if existing:
        return existing

    candidate_paths = [Path(arc_key_path)] if arc_key_path else list(ARC_KEY_PATHS)
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            key = str(json.loads(path.read_text()).get("key", "")).strip()
        except Exception as exc:
            logger.warning("Could not read ARC key from %s: %s", path, exc)
            continue
        if key:
            os.environ["ARC_API_KEY"] = key
            logger.info("Loaded ARC_API_KEY from %s", path)
            return key
    return None


class SingleTaskRunner:
    def __init__(self, real_api=False, config_path: str | Path | None = None, llm_overrides: dict | None = None):
        resolved_config_path = Path(config_path) if config_path else (CONFIG_PATH if CONFIG_PATH.exists() else None)
        self.config = _apply_llm_overrides(load_config(resolved_config_path), llm_overrides)
        self.db = None
        self.harness = None
        self.loop_queue = asyncio.Queue()
        self.loop_task = None
        self.tasks = []
        self.results = []
        self.real_api = real_api
        self.live_output_path = LIVE_OUTPUT_PATH
        self.final_output_path = FINAL_OUTPUT_PATH
        self.arc_server_output_path = ARC_SERVER_OUTPUT_PATH
        self.agent_execution_trace_path = AGENT_EXECUTION_TRACE_PATH
        self.master_timeline_path = MASTER_TIMELINE_PATH

    async def initialize(self):
        logger.info("Initializing Single Task Runner...")

        # Clean up old database and stale sidecars from prior smoke runs.
        _remove_db_artifacts(DB_PATH)

        # 1. Initialize Database
        DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = KuzuClient(str(DB_PATH))

        # 2. Configure + pre-warm embedder
        emb.configure(self.config)
        embedding_model = self.config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        emb.prewarm(embedding_model)

        # 3. Initialize Schema
        init_schema(self.db, str(SEED_PATH), embedding_model)

        # 4. Load Loop State
        centroids = load_centroids(self.db)
        load_routing_table(self.db)
        init_loop_queue(self.loop_queue)

        # 5. Start Background Loop Worker
        self.loop_task = asyncio.create_task(self._loop_worker(centroids))

        # 6. Initialize Harness
        benchmark_config = BenchmarkConfig(
            name="ARC-AGI-3",
            description="Single puzzle test",
            timeout=3600,
            memory_limit_gb=8.0,
            cpu_limit_percent=80.0,
            parameters=self.config.get("benchmark", {})
        )
        self.harness = ARC3Harness(benchmark_config, db=self.db, mock_api=not self.real_api)
        await self.harness.setup()

        # 7. Load all tasks (main() will slice)
        if MANIFEST_PATH.exists():
            self.tasks = load_tasks_from_manifest(str(MANIFEST_PATH))
            logger.info(f"Loaded {len(self.tasks)} task(s) from manifest.")
        else:
            logger.warning(f"Manifest not found at {MANIFEST_PATH}. Running with empty task set.")

        if self.real_api and self.tasks:
            live_games = await self.harness.list_games()
            if not live_games:
                raise RuntimeError("Live ARC API returned no games.")

            usable_count = min(len(self.tasks), len(live_games))
            for task, game in zip(self.tasks[:usable_count], live_games[:usable_count]):
                game_id = game["game_id"]
                setattr(task, "game_id", game_id)
                task.prompt = f"Solve live ARC puzzle {game_id}"

            logger.info(
                "Mapped %d manifest task(s) onto live ARC game ids. First game: %s",
                usable_count,
                getattr(self.tasks[0], "game_id", "unknown"),
            )

    async def _loop_worker(self, centroids):
        """Minimal loop worker for submission."""
        from mcp_engine.loop.orchestrator import run_loop
        from mcp_engine.llm.provider import create_llm_client
        
        llm_client = create_llm_client(self.config)
        
        while True:
            got_item = False
            try:
                item = await self.loop_queue.get()
                got_item = True
                
                # B108: Added precomputed to queue tuple
                if len(item) == 4:
                    message_id, text, role, session_id = item
                    precomputed = None
                else:
                    message_id, text, role, session_id, precomputed = item

                await run_loop(
                    message_id=message_id,
                    text=text,
                    role=role,
                    db=self.db,
                    llm_client=llm_client,
                    config=self.config,
                    centroids=centroids,
                    session_id=session_id,
                    precomputed=precomputed,
                )
            except Exception as e:
                logger.error(f"Loop worker error: {e}")
            finally:
                if got_item:
                    self.loop_queue.task_done()

    def reset_live_output(self):
        self.live_output_path.write_text("")

    def append_live_snapshot(self, snapshot: dict):
        with open(self.live_output_path, "a") as f:
            f.write(json.dumps(snapshot) + "\n")

    def export_results(self):
        output_path = self.final_output_path
        logger.info(f"Exporting results to {output_path}")
        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        # Chronological timeline of function calls + ARC API request/response events.
        call_timeline = []
        for result in self.results:
            for entry in result.get("sidequests_ledger", []) or []:
                if not isinstance(entry, dict):
                    continue

                call_type = entry.get("call_type")
                timestamp = entry.get("timestamp_iso")
                if not call_type or not timestamp:
                    continue

                # ARC API request/response are emitted from arc_server_responses below.
                if call_type == "arc_api_action":
                    continue

                name = str(call_type)

                call_timeline.append(
                    {
                        "name": name,
                        "event": "call",
                        "data": entry,
                        "timestamp_iso": timestamp,
                        "event_detail": "internal harness or agent function call (memory/planning/orchestration tools)",
                        "what": entry.get("input_summary") or entry.get("result_summary") or name,
                    }
                )

            for response in result.get("arc_server_responses", []) or []:
                if not isinstance(response, dict):
                    continue

                request = response.get("request", {}) if isinstance(response.get("request"), dict) else {}
                reply = response.get("response", {}) if isinstance(response.get("response"), dict) else {}

                endpoint = request.get("endpoint")
                if isinstance(endpoint, str) and endpoint:
                    op_name = endpoint.rsplit("/", 1)[-1].upper().replace("/", "_")
                else:
                    op_name = str(request.get("label") or "ARC_CALL")

                request_ts = request.get("timestamp_iso")
                if isinstance(request_ts, str) and request_ts:
                    method = request.get("method")
                    if isinstance(method, str) and method:
                        what_request = f"{method} {endpoint}" if isinstance(endpoint, str) else method
                    else:
                        what_request = request.get("label") or op_name
                    call_timeline.append(
                        {
                            "name": op_name,
                            "event": "request",
                            "data": request,
                            "timestamp_iso": request_ts,
                            "event_detail": "ARC API request",
                            "what": what_request,
                        }
                    )

                response_ts = reply.get("timestamp_iso")
                if isinstance(response_ts, str) and response_ts:
                    response_summary = reply.get("response_summary")
                    if not response_summary:
                        http_status = reply.get("http_status")
                        response_summary = f"http_status={http_status}" if http_status is not None else "response received"
                    call_timeline.append(
                        {
                            "name": op_name,
                            "event": "response",
                            "data": reply,
                            "timestamp_iso": response_ts,
                            "event_detail": "ARC API response",
                            "what": response_summary,
                        }
                    )

        def _sort_key(item: dict) -> tuple:
            ts = item.get("timestamp_iso")
            if not isinstance(ts, str):
                return (datetime.datetime.max, "")
            try:
                parsed = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                parsed = datetime.datetime.max
            return (parsed, str(item.get("name", "")))

        call_timeline.sort(key=_sort_key)

        logger.info(f"Exporting ARC-only responses to {self.arc_server_output_path}")
        with open(self.arc_server_output_path, 'w') as f:
            json.dump(call_timeline, f, indent=2)

        # B131: Export agent execution trace (CloudWatch-style logs)
        agent_execution_trace = []
        for result in self.results:
            trace_events = result.get("agent_execution_trace", []) or []
            agent_execution_trace.extend(trace_events)
        
        # Sort by timestamp
        agent_execution_trace.sort(key=lambda e: e.get("timestamp_iso", ""))
        
        logger.info(f"Exporting agent execution trace to {self.agent_execution_trace_path}")
        with open(self.agent_execution_trace_path, 'w') as f:
            json.dump(agent_execution_trace, f, indent=2)

        # B131: Export master timeline — all events from both streams merged chronologically.
        master_timeline = []
        for event in call_timeline:
            master_timeline.append({
                "source": "arc_server",
                "timestamp_iso": event.get("timestamp_iso"),
                "name": event.get("name"),
                "event": event.get("event"),
                "what": event.get("what"),
                "event_detail": event.get("event_detail"),
                "data": event.get("data"),
            })
        for event in agent_execution_trace:
            master_timeline.append({
                "source": "agent_trace",
                "timestamp_iso": event.get("timestamp_iso"),
                "name": event.get("operation"),
                "event": event.get("event_type"),
                "what": (
                    (event.get("result") or {}).get("action_id")
                    or str((event.get("details") or {}).get("action_taken", ""))
                    or event.get("operation", "")
                ),
                "event_detail": f"{event.get('event_type')} — {event.get('operation')}",
                "details": event.get("details"),
                "result": event.get("result"),
                "elapsed_ms": event.get("elapsed_ms"),
            })

        master_timeline.sort(key=_sort_key)

        logger.info(f"Exporting master timeline to {self.master_timeline_path}")
        with open(self.master_timeline_path, 'w') as f:
            json.dump(master_timeline, f, indent=2)

    async def shutdown(self):
        """Tear down background resources so the runner exits cleanly."""
        if self.loop_task is not None:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
            self.loop_task = None

        if self.harness is not None:
            await self.harness.teardown()
            self.harness = None

        if self.db is not None:
            self.db.close()
            self.db = None


async def main():
    parser = argparse.ArgumentParser(description="Run ARC puzzles (optionally real API)")
    parser.add_argument("--real-api", action="store_true", help="Run against the real ARC-AGI-3 API")
    parser.add_argument(
        "--live-smoke",
        action="store_true",
        help=(
            "Convenience mode for a one-puzzle live smoke: implies --real-api, auto-loads ARC_API_KEY "
            "from the repo credential file when needed, and uses more forgiving local-Ollama timeout/retry defaults."
        ),
    )
    parser.add_argument("--num-puzzles", type=int, default=None, help="Number of puzzles to run (default: 1 for real, 5 for mock)")
    parser.add_argument("--card-id", type=str, default=None, help="Override ARC checkpoint card id")
    parser.add_argument("--config", type=str, default=None, help="Explicit path to the sidequests.toml file to use for this run")
    parser.add_argument("--model", type=str, default=None, help="Override llm.model for this run only")
    parser.add_argument("--base-url", type=str, default=None, help="Override llm.base_url for this run only")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Override llm.timeout_seconds for this run only")
    parser.add_argument("--max-retries", type=int, default=None, help="Override llm.max_retries for this run only")
    parser.add_argument(
        "--arc-key-path",
        type=str,
        default=None,
        help="Load ARC_API_KEY from this JSON file if the environment variable is not already set",
    )
    args = parser.parse_args()

    real_api = args.real_api or args.live_smoke

    llm_overrides = {
        key: value
        for key, value in {
            "model": args.model,
            "base_url": args.base_url,
            "timeout_seconds": args.timeout_seconds,
            "max_retries": args.max_retries,
        }.items()
        if value is not None
    }
    if args.live_smoke:
        llm_overrides.setdefault("timeout_seconds", 300.0)
        llm_overrides.setdefault("max_retries", 5)

    if real_api and not _ensure_arc_api_key(args.arc_key_path):
        logger.warning(
            "ARC_API_KEY was not found in the environment or repo credential files; the live run may fail to authenticate."
        )

    # Determine number of puzzles
    if args.num_puzzles is not None:
        num_puzzles = args.num_puzzles
    else:
        num_puzzles = 1 if real_api else TASK_BATCH_SIZE

    runner = SingleTaskRunner(real_api=real_api, config_path=args.config, llm_overrides=llm_overrides)
    try:
        await runner.initialize()

        # Override loaded tasks to first N
        if runner.tasks:
            runner.tasks = runner.tasks[:num_puzzles]

        if not runner.tasks:
            logger.error("No tasks to run!")
            return

        if args.card_id:
            card_id = args.card_id
        elif real_api:
            # Real API test runs should not silently reuse stale local checkpoints.
            card_id = f"real_test_{int(time.time())}"
        else:
            card_id = runner.config.get("benchmark", {}).get("card_id") or "local_test"
        brain_client = LocalBrainClient(runner.db, runner.config)
        runner.reset_live_output()
        durable = DurableARCRunner(
            runner.harness,
            brain_client,
            runner.config,
            progress_callback=runner.append_live_snapshot,
        )

        llm_cfg = runner.config.get("llm", {})
        logger.info(
            "Running %d puzzle(s), starting with: %s | provider=%s model=%s timeout=%s retries=%s",
            len(runner.tasks),
            runner.tasks[0].task_id,
            llm_cfg.get("provider"),
            llm_cfg.get("model"),
            llm_cfg.get("timeout_seconds", "default"),
            llm_cfg.get("max_retries", "default"),
        )
        runner.results = await durable.run(runner.tasks, card_id)

        # Print result summary
        for idx, result in enumerate(runner.results):
            logger.info(f"Task {idx+1}: {result.get('task_id')}")
            logger.info(f"  Correct: {result['metadata'].get('correct')}")
            logger.info(f"  Steps: {result['metadata'].get('steps')}")

            solve_summary = result.get("solve_phase_summary") or result.get("metadata", {}).get("solve_phase_summary") or {}
            if solve_summary:
                logger.info(f"  [SOLVE] archetype: {solve_summary.get('final_archetype')} ({solve_summary.get('final_archetype_confidence', 0):.0%})")
                logger.info(f"  [SOLVE] victory: {solve_summary.get('final_victory_condition')} ({solve_summary.get('final_victory_confidence', 0):.0%})")
                logger.info(f"  [SOLVE] strategy: {solve_summary.get('final_strategy_summary', '')[:80]}")
                logger.info(f"  [SOLVE] dissonance: {solve_summary.get('dissonance_triggered')}")
                if solve_summary.get("archetype_evolution"):
                    logger.info(f"  [SOLVE] archetype evolution: {' → '.join(solve_summary['archetype_evolution'])}")

            error = result['metadata'].get('error')
            if error:
                logger.error(f"  Error: {error}")
            else:
                logger.info("  ✅ No parameter binding error!")

        runner.export_results()
    finally:
        await runner.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
