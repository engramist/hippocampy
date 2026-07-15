"""B304 — ask-eval matrix runner.

Runs the `ask` pipeline across (model x harness variant) combinations against
a deterministic fixture graph, scores each answer with deterministic regexes
(no LLM judge), and reports a table + a JSON result file under the runtime
dir (~/.campy/eval_results/ — never in the repo).

CLI: `python -m benchmarks.ask_eval.runner --model llama3.1:8b --variant H0 --variant H1`

Not wired into `campy/cli/main.py`: `docs/ecosystem-rules.md` (enforced by
`tests/test_architecture_import_boundaries.py`) forbids any file under
`campy/` from importing `benchmarks/` — production Campy code must stay
importable without dragging in dev/eval tooling. This harness stays
self-contained under `benchmarks/` and is invoked as its own module instead.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from benchmarks.ask_eval.fixtures import seed_fixture_graph
from benchmarks.ask_eval.questions import QUESTIONS

eval_app = typer.Typer(help="Evaluation harnesses for ask/retrieval quality (B304).")
console = Console()

_RESULTS_DIR = Path.home() / ".campy" / "eval_results"


def score_question(question: dict, answer: str, latency: Optional[float] = None) -> dict:
    """Score a single question's answer against its must/must-not regexes.

    covered = all must_match hit; hallucinated = any must_not_match hit.
    score: 1.0 if covered and not hallucinated; 0 if not covered;
    -1.0 if hallucinated (fabrication is worse than ignorance).
    """
    must_match = question.get("must_match", [])
    must_not_match = question.get("must_not_match", [])

    covered = all(re.search(pattern, answer, re.IGNORECASE) for pattern in must_match)
    hallucinated = any(re.search(pattern, answer, re.IGNORECASE) for pattern in must_not_match)

    if hallucinated:
        score = -1.0
    elif covered:
        score = 1.0
    else:
        score = 0

    return {
        "score": score,
        "covered": covered,
        "hallucinated": hallucinated,
        "latency": latency,
        "answer": answer,
    }


def _model_available(model: str) -> bool:
    """Precondition check: is `model` present in `ollama list`? Never auto-pulls."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return False
    return model in result.stdout


async def _run_combo(model: str, variant: str, base_config: dict) -> dict:
    """Run all questions for one (model, variant) combo against a fresh temp DB."""
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.hippocampus.schema import init_schema
    from campy.brain.thalamus.ask import run_ask

    cfg = copy.deepcopy(base_config)
    cfg.setdefault("llm", {})["model"] = model
    cfg.setdefault("ask", {})["harness_variant"] = variant

    tmp_dir = tempfile.mkdtemp(prefix="ask-eval-")
    db_path = os.path.join(tmp_dir, "eval.db")
    embedding_model = cfg.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    db = KuzuClient(db_path)
    try:
        init_schema(db, "campy/data/GistSeedExamples.md", embedding_model)
        await seed_fixture_graph(db, cfg)

        question_results = []
        for question in QUESTIONS:
            meta: dict = {}
            start = time.monotonic()
            answer = await run_ask(
                query=question["question"],
                session_id="ask-eval",
                db=db,
                config=cfg,
                capture=False,
                meta=meta,
            )
            latency = time.monotonic() - start
            scored = score_question(question, answer, latency=latency)
            scored["id"] = question["id"]
            scored["family"] = question["family"]
            scored["retried"] = meta.get("retried", False)
            question_results.append(scored)
    finally:
        db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return _aggregate(model, variant, question_results)


def _aggregate(model: str, variant: str, question_results: list[dict]) -> dict:
    scores = [q["score"] for q in question_results]
    overall = statistics.mean(scores) if scores else 0.0

    families: dict[str, list[float]] = {}
    for q in question_results:
        families.setdefault(q["family"], []).append(q["score"])
    per_family = {fam: statistics.mean(vals) for fam, vals in families.items()}

    negative_control_scores = families.get("negative_control", [])
    negative_control_pass_rate = (
        sum(1 for s in negative_control_scores if s == 1.0) / len(negative_control_scores)
        if negative_control_scores
        else None
    )

    latencies = [q["latency"] for q in question_results if q["latency"] is not None]
    median_latency = statistics.median(latencies) if latencies else None

    return {
        "model": model,
        "variant": variant,
        "overall_score": overall,
        "per_family_score": per_family,
        "negative_control_pass_rate": negative_control_pass_rate,
        "median_latency_seconds": median_latency,
        "questions": question_results,
    }


async def run_matrix(models: List[str], variants: List[str]) -> list[dict]:
    """Run every (model, variant) combination in the matrix. Skips unavailable models."""
    from campy.brain.brainstem.config import load_config

    base_config = load_config("campy/data/config/campy.toml")

    results = []
    for model in models:
        if not _model_available(model):
            console.print(
                f"[yellow]Skipping {model}: not found in `ollama list`. "
                f"Pull it first: [bold]ollama pull {model}[/bold][/yellow]"
            )
            continue
        for variant in variants:
            console.print(f"[cyan]Running model={model} variant={variant}...[/cyan]")
            results.append(await _run_combo(model, variant, base_config))
    return results


def _render_table(results: list[dict]) -> Table:
    table = Table(title="ask-eval matrix (B304)")
    table.add_column("Model")
    table.add_column("Variant")
    table.add_column("Overall")
    table.add_column("Identifier")
    table.add_column("Paraphrase")
    table.add_column("Cross-lane")
    table.add_column("Continuation")
    table.add_column("Neg-control pass%")
    table.add_column("Median latency (s)")

    for row in results:
        fam = row["per_family_score"]
        ncr = row["negative_control_pass_rate"]
        table.add_row(
            row["model"],
            row["variant"],
            f"{row['overall_score']:.2f}",
            f"{fam.get('identifier', 0):.2f}",
            f"{fam.get('paraphrase', 0):.2f}",
            f"{fam.get('cross_lane', 0):.2f}",
            f"{fam.get('continuation', 0):.2f}",
            f"{ncr * 100:.0f}%" if ncr is not None else "n/a",
            f"{row['median_latency_seconds']:.2f}" if row["median_latency_seconds"] is not None else "n/a",
        )
    return table


def _write_json_results(results: list[dict]) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = _RESULTS_DIR / f"ask-eval-{timestamp}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    return out_path


async def _run_and_report(models: List[str], variants: List[str]) -> None:
    results = await run_matrix(models, variants)
    if not results:
        console.print("[red]No results — all requested models were unavailable.[/red]")
        raise typer.Exit(1)
    console.print(_render_table(results))
    out_path = _write_json_results(results)
    console.print(f"[green]Wrote results to {out_path}[/green]")


@eval_app.command("ask")
def eval_ask(
    model: List[str] = typer.Option(
        ..., "--model", help="Model(s) to evaluate (repeatable), e.g. --model llama3.1:8b"
    ),
    variant: List[str] = typer.Option(
        ["H0"],
        "--variant",
        help="Harness variant(s) to evaluate (repeatable): H0, H1, H1+H2",
    ),
):
    """Run the ask-eval matrix (models x harness variants) and report results."""
    asyncio.run(_run_and_report(model, variant))


if __name__ == "__main__":
    eval_app()
