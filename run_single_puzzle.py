#!/usr/bin/env python3
"""Test submission runner for a small ARC puzzle batch."""


import argparse
import asyncio
import json
import logging
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
LIVE_OUTPUT_PATH = REPO_ROOT / "submission_results_single.live.jsonl"

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SingleTaskRunner:
    def __init__(self, real_api=False):
        self.config = load_config()
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

    async def initialize(self):
        logger.info("Initializing Single Task Runner...")

        # Clean up old database
        if DB_PATH.exists():
            import shutil
            if DB_PATH.is_dir():
                shutil.rmtree(DB_PATH)
            else:
                DB_PATH.unlink()

        # 1. Initialize Database
        DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = KuzuClient(str(DB_PATH))

        # 2. Pre-warm Embedder
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

        arc_server_results = [
            response
            for result in self.results
            for response in result.get("arc_server_responses", [])
        ]
        logger.info(f"Exporting ARC-only responses to {self.arc_server_output_path}")
        with open(self.arc_server_output_path, 'w') as f:
            json.dump(arc_server_results, f, indent=2)

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
    parser.add_argument("--num-puzzles", type=int, default=None, help="Number of puzzles to run (default: 1 for real, 5 for mock)")
    parser.add_argument("--card-id", type=str, default=None, help="Override ARC checkpoint card id")
    args = parser.parse_args()

    # Determine number of puzzles
    if args.num_puzzles is not None:
        num_puzzles = args.num_puzzles
    else:
        num_puzzles = 1 if args.real_api else TASK_BATCH_SIZE

    runner = SingleTaskRunner(real_api=args.real_api)
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
        elif args.real_api:
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

        logger.info(f"Running {len(runner.tasks)} puzzle(s), starting with: {runner.tasks[0].task_id}")
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
