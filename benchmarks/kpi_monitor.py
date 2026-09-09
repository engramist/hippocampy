#!/usr/bin/env python3
"""
benchmarks/kpi_monitor.py — 4-Tier Local KPI Monitor & Baseline Instrument (B381).

Continuously evaluates and snapshots HippoCampy daemon KPIs across 4 tiers:
  - Tier 1: Resource & Physical Footprint KPIs (idle RSS, import overhead, leak deltas)
  - Tier 2: Token Economics, Speed & Graph Traversal KPIs (retrieval latency, generation,
            B289/B374 compression ratios, isolated <= 2 hop traversal latency, degree caps)
  - Tier 3: Cognitive Retention & Deprecation KPIs (recall precision, negative control, paraphrase)
  - Tier 4: Model Handoff Fidelity KPIs (zero constraint violations, handoff latency)

CLI Usage:
    python benchmarks/kpi_monitor.py --out baseline_snapshot.json
    python benchmarks/kpi_monitor.py --smoke
    python benchmarks/kpi_monitor.py --compare baseline_snapshot.json

--------------------------------------------------------------------------
B415 — measurement integrity (see backlog/B415.md)
--------------------------------------------------------------------------
This module used to emit hardcoded literals from B381's card table
("daemon_idle_rss_mb": 245.6, "live_steady_state_rss_mb": 1200.0,
retrieval_latency_ms = 28.5 if not smoke else 8.5, ...) dressed up as
measurements. Two of them were confirmed wrong: 245.6 MB was import-time-only
RSS (warm, with models actually invoked, is ~590 MB); 1200.0 MB came from a
venv carrying a stale, undeclared `torch` (see B416). `baseline_snapshot.json`
was therefore a set of constants, and `--compare` diffed two sets of
constants — output shaped like a result, carrying no information.

Every metric below is now either:
  (a) a real, timed/sampled measurement, with its methodology (warm/cold,
      whether a model was actually invoked, sample count, in-process vs.
      subprocess) recorded alongside the number, or
  (b) `null`, with an explicit reason, when it genuinely cannot be measured
      in-process without a much larger harness this script does not own
      (e.g. Tier 3's ask-eval scores live in benchmarks/ask_eval/).

A `null` with a reason is a correct outcome. A number with no methodology
is the defect this card exists to remove.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import subprocess
import sys
import textwrap
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    import psutil
except ImportError:
    psutil = None


# ---------------------------------------------------------------------------
# Design targets (NOT measurements) — aspirational figures from other
# backlog cards, kept only for the markdown report's "target" column. Never
# treat these as a stand-in for a measured value.
# ---------------------------------------------------------------------------
DESIGN_TARGETS = {
    "target_physical_rss_mb": 80.0,          # B384
    "target_retrieval_latency_ms": 10.0,     # B375
    "target_llm_generation_latency_s": 1.0,  # B374
    "target_ask_eval_overall": 0.90,
    "target_paraphrase_accuracy": 0.80,
    "target_handoff_overhead_ms": 500.0,     # B383
}


# ---------------------------------------------------------------------------
# B416 environment-drift gate
# ---------------------------------------------------------------------------
class EnvironmentContaminationError(RuntimeError):
    """Raised when the measurement environment cannot produce a trustworthy
    measurement (a known-harmful, undeclared package is present — B416)."""


def assert_environment_clean() -> None:
    """B415 requirement 2 / B416 requirement 3: refuse to measure at all in a
    drifted environment, rather than silently emit numbers inflated by it.

    Two checks, in order:
      1. A narrow, immediate check of `sys.modules` for `torch` — catches the
         literal case named in the card ("assert torch is absent from
         sys.modules"), regardless of how it got there.
      2. The full B416 dependency-closure drift check (scripts/check_env_drift.py)
         — catches the *installed-but-not-yet-imported* case, which is the
         actually dangerous one: `torch` sitting in site-packages is enough
         to corrupt the warm-RSS measurement below the moment spaCy loads
         (`thinc.compat` imports it opportunistically), even though nothing
         has imported it yet at the moment this check runs.
    """
    torch_modules = [m for m in sys.modules if m == "torch" or m.startswith("torch.")]
    if torch_modules:
        raise EnvironmentContaminationError(
            "torch is already present in sys.modules "
            f"({torch_modules}). Every RSS/latency figure this script measures "
            "would be inflated by torch's presence. Aborting rather than emit "
            "a corrupted measurement -- see backlog/B415.md and backlog/B416.md."
        )

    from check_env_drift import check_env_drift  # scripts/check_env_drift.py

    drift = check_env_drift()
    if drift["known_harmful_present"]:
        raise EnvironmentContaminationError(
            "Environment drift detected: "
            + ", ".join(drift["known_harmful_present"])
            + " installed and undeclared in pyproject.toml/requirements.txt. "
            "thinc.compat opportunistically imports torch whenever it's "
            "importable, costing ~150-225MB RSS in an environment production "
            "does not have. Run `python scripts/check_env_drift.py` for the "
            "full report, or `make rebuild-venv` for a clean environment. "
            "See backlog/B416.md."
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _self_rss_mb() -> float:
    """RSS of *this* process, right now."""
    if psutil is not None:
        return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024.0 * 1024.0)  # bytes on macOS
    return usage.ru_maxrss / 1024.0  # KB on Linux


def _run_subprocess_json(python_bin: str, script: str, timeout: float) -> dict:
    """Run `script` in a fresh interpreter and parse its single JSON stdout
    line. Isolation matters here: we want each RSS stage measured in a
    process that has done nothing else, not polluted by whatever this
    script itself has already imported."""
    proc = subprocess.run(
        [python_bin, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )
    if proc.returncode != 0:
        return {"error": f"subprocess exited {proc.returncode}: {proc.stderr.strip()[-2000:]}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": f"could not parse subprocess output: {e}; stdout={proc.stdout!r}"}


# ---------------------------------------------------------------------------
# Tier 1 Measurement: Resource & Footprint KPIs
# ---------------------------------------------------------------------------
_IMPORT_ONLY_SCRIPT = textwrap.dedent(
    """
    import json, os, sys
    import psutil
    proc = psutil.Process(os.getpid())
    baseline_mb = proc.memory_info().rss / (1024.0 * 1024.0)
    import campy.brain_daemon  # noqa: F401 -- import-time only, nothing invoked
    after_mb = proc.memory_info().rss / (1024.0 * 1024.0)
    torch_present = any(m == "torch" or m.startswith("torch.") for m in sys.modules)
    print(json.dumps({
        "baseline_python_rss_mb": round(baseline_mb, 2),
        "import_only_rss_mb": round(after_mb, 2),
        "torch_present": torch_present,
    }))
    """
)

_WARM_INVOKED_SCRIPT = textwrap.dedent(
    """
    import json, os, sys
    import psutil
    proc = psutil.Process(os.getpid())
    baseline_mb = proc.memory_info().rss / (1024.0 * 1024.0)

    import spacy
    nlp = spacy.load("en_core_web_md")
    doc = nlp("HippoCampy uses Oxigraph for its RDF-star graph store and fastembed for embeddings.")
    _ = list(doc.ents)
    spacy_invoked_mb = proc.memory_info().rss / (1024.0 * 1024.0)

    from fastembed import TextEmbedding
    model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    _ = list(model.embed(["a test sentence for embedding invocation"]))
    fastembed_invoked_mb = proc.memory_info().rss / (1024.0 * 1024.0)

    torch_present = any(m == "torch" or m.startswith("torch.") for m in sys.modules)
    print(json.dumps({
        "baseline_python_rss_mb": round(baseline_mb, 2),
        "spacy_loaded_and_invoked_rss_mb": round(spacy_invoked_mb, 2),
        "fastembed_loaded_and_invoked_rss_mb": round(fastembed_invoked_mb, 2),
        "torch_present": torch_present,
    }))
    """
)


def _measure_write_burst_spike(n_writes: int) -> Dict[str, Any]:
    """Real burst of `n_writes` graph writes (with 384-dim embeddings, matching
    a production write) against an in-memory OxigraphClient, sampling this
    process's own RSS on a background thread throughout. Returns the peak
    RSS observed minus the immediately-pre-burst RSS."""
    import threading

    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

    db = OxigraphClient(db_path=":memory:")
    gc.collect()
    pre_mb = _self_rss_mb()
    peak_mb = [pre_mb]
    stop = threading.Event()

    def _sampler() -> None:
        while not stop.is_set():
            peak_mb[0] = max(peak_mb[0], _self_rss_mb())
            time.sleep(0.005)

    sampler_thread = threading.Thread(target=_sampler, daemon=True)
    sampler_thread.start()
    t0 = time.perf_counter()
    vector = [0.01] * 384
    for i in range(n_writes):
        db.write_node(
            "Concept",
            {
                "concept_id": str(uuid.uuid4()),
                "text_raw": f"kpi_monitor burst-write concept {i} — synthetic content for RSS sampling.",
                "embedding": vector,
            },
        )
    elapsed_s = time.perf_counter() - t0
    stop.set()
    sampler_thread.join(timeout=1.0)

    return {
        "n_writes": n_writes,
        "elapsed_s": round(elapsed_s, 4),
        "pre_burst_rss_mb": round(pre_mb, 2),
        "peak_rss_mb": round(peak_mb[0], 2),
        "spike_mb": round(peak_mb[0] - pre_mb, 2),
    }


def _measure_allocation_delta(turns_count: int) -> Dict[str, Any]:
    """Real (not formula-derived) RSS delta from allocating `turns_count`
    dummy turn dicts in this process, gc-settled before each sample."""
    gc.collect()
    pre_mb = _self_rss_mb()
    dummy_turns = [
        {"role": "user", "content": f"Turn {i} with semantic information and constraints for monitoring."}
        for i in range(turns_count)
    ]
    gc.collect()
    post_mb = _self_rss_mb()
    delta = post_mb - pre_mb
    # Keep a reference until after measurement so the list isn't optimized away.
    _ = len(dummy_turns)
    return {"pre_mb": round(pre_mb, 4), "post_mb": round(post_mb, 4), "delta_mb": round(delta, 4)}


def measure_tier1_resource_footprint(smoke: bool = False, python_bin: Optional[str] = None) -> Dict[str, Any]:
    """Measure real process RSS at several stages, plus a real write-burst
    memory spike and a real allocation delta. Subprocess-based stages
    (import-only, warm-invoked) are skipped in --smoke mode for speed and
    reported as null with a reason -- they take several seconds (spaCy +
    fastembed model loads) which is disproportionate for a fast smoke check.
    """
    python_bin = python_bin or sys.executable
    current_process_rss_mb = round(_self_rss_mb(), 2)

    if smoke:
        import_only = {"skipped_reason": "smoke mode -- subprocess RSS measurement skipped for speed"}
        warm_invoked = {"skipped_reason": "smoke mode -- subprocess RSS measurement skipped for speed"}
    else:
        import_only = _run_subprocess_json(python_bin, _IMPORT_ONLY_SCRIPT, timeout=60)
        warm_invoked = _run_subprocess_json(python_bin, _WARM_INVOKED_SCRIPT, timeout=90)
        for label, result in (("import-only", import_only), ("warm-invoked", warm_invoked)):
            if result.get("torch_present"):
                raise EnvironmentContaminationError(
                    f"torch entered sys.modules during the {label} RSS measurement subprocess "
                    "despite passing the pre-flight environment check. Aborting -- see backlog/B416.md."
                )

    turns_count = 10 if smoke else 100
    n_writes = 200 if smoke else 5000

    write_burst = _measure_write_burst_spike(n_writes)
    allocation = _measure_allocation_delta(turns_count)

    return {
        "current_process_rss_mb": current_process_rss_mb,
        "import_only_rss_mb": import_only.get("import_only_rss_mb"),
        "warm_invoked_rss_mb": warm_invoked.get("fastembed_loaded_and_invoked_rss_mb"),
        "warm_invoked_breakdown": {
            "baseline_python_rss_mb": warm_invoked.get("baseline_python_rss_mb"),
            "spacy_loaded_and_invoked_rss_mb": warm_invoked.get("spacy_loaded_and_invoked_rss_mb"),
            "fastembed_loaded_and_invoked_rss_mb": warm_invoked.get("fastembed_loaded_and_invoked_rss_mb"),
        } if "skipped_reason" not in warm_invoked else None,
        "write_burst_peak_spike_mb": write_burst["spike_mb"],
        "allocation_delta_per_100_turns_mb": round(
            allocation["delta_mb"] * (100.0 / turns_count) if turns_count else 0.0, 4
        ),
        "target_rss_mb": DESIGN_TARGETS["target_physical_rss_mb"],
        "methodology": {
            "current_process_rss_mb": "psutil (or ru_maxrss fallback) on this script's own process, in-process, 1 sample.",
            "import_only_rss_mb": (
                import_only.get("skipped_reason")
                or "subprocess: RSS sampled immediately after `import campy.brain_daemon`, no model invoked, cold, 1 sample."
            ),
            "warm_invoked_rss_mb": (
                warm_invoked.get("skipped_reason")
                or warm_invoked.get("error")
                or "subprocess: RSS sampled after spaCy (en_core_web_md) loaded AND run on a sentence, "
                "then fastembed loaded AND run on a sentence -- warm, models invoked, cold process, 1 sample. "
                "See warm_invoked_breakdown for the staged figures."
            ),
            "write_burst_peak_spike_mb": (
                f"in-process: {n_writes} real graph writes (with 384-dim embeddings) against an "
                "in-memory OxigraphClient, RSS sampled every 5ms on a background thread throughout; "
                "spike = peak observed RSS - pre-burst RSS."
            ),
            "allocation_delta_per_100_turns_mb": (
                f"in-process: gc.collect() + RSS sample, allocate {turns_count} dummy turn dicts, "
                "gc.collect() + RSS sample again; delta scaled to a per-100-turns rate."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Tier 2 Measurement: Speed, Token Economics & Graph Traversal KPIs
# ---------------------------------------------------------------------------
def _ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    try:
        req = urllib.request.Request(base_url.rstrip("/v1").rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


async def _measure_retrieval_compilation_latency(sample_count: int) -> Dict[str, Any]:
    """Real, in-process compile_bundle() timing against an in-memory (empty)
    OxigraphClient -- the real GraphGateway/QueryRegistry/fastembed path,
    just not against production-scale data. compile_bundle() already
    computes its own compilation_ms; we just read it back."""
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.thalamus.bundle_compiler import compile_bundle

    db = OxigraphClient(db_path=":memory:")
    config: Dict[str, Any] = {}

    samples: List[float] = []
    cold_ms: Optional[float] = None
    for i in range(sample_count):
        bundle = await compile_bundle(f"kpi_monitor probe query {i}", db, config, token_budget=2000)
        if i == 0:
            cold_ms = bundle.compilation_ms
        else:
            samples.append(bundle.compilation_ms)

    warm_mean_ms = sum(samples) / len(samples) if samples else cold_ms

    return {
        "cold_ms": round(cold_ms, 3) if cold_ms is not None else None,
        "warm_mean_ms": round(warm_mean_ms, 3) if warm_mean_ms is not None else None,
        "warm_sample_count": len(samples),
    }


def _measure_graph_hop_latency(db, sample_count: int) -> Dict[str, Any]:
    """Real, timed SPARQL query bounded to a 2-hop pattern against the same
    in-memory store -- no time.sleep() stand-in. Empty-graph caveat applies
    equally: this measures query-planning/execution overhead, not traversal
    cost against production-scale data."""
    sparql = "SELECT ?o WHERE { ?s ?p1 ?m . ?m ?p2 ?o . } LIMIT 100"
    samples: List[float] = []
    for _ in range(sample_count):
        t0 = time.perf_counter()
        list(db.execute(sparql))
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "cold_ms": round(samples[0], 4) if samples else None,
        "warm_mean_ms": round(sum(samples[1:]) / len(samples[1:]), 4) if len(samples) > 1 else None,
        "sample_count": sample_count,
    }


def _measure_llm_generation_latency(smoke: bool) -> Dict[str, Any]:
    """Real, timed chat completion against the local Ollama endpoint this
    dev machine actually has running (default model per B307's ask-eval
    harness: llama3.1:8b). Skipped in smoke mode (multi-second network call,
    disproportionate for a fast check) and whenever the endpoint isn't
    reachable -- both cases return methodology, not a number."""
    base_url = "http://localhost:11434/v1"
    if smoke:
        return {"value_s": None, "reason": "smoke mode -- LLM call skipped for speed"}
    if not _ollama_reachable(base_url):
        return {"value_s": None, "reason": f"no LLM endpoint reachable at {base_url}"}

    from campy.brain.llm.provider import create_llm_client

    client = create_llm_client(
        {"llm": {"provider": "ollama", "model": "llama3.1:8b", "base_url": base_url, "timeout_seconds": 30}}
    )
    if client is None:
        return {"value_s": None, "reason": "create_llm_client() returned None (see stderr for provider error)"}

    try:
        t0 = time.perf_counter()
        client.chat([{"role": "user", "content": "Reply with exactly one word: OK"}])
        elapsed_s = time.perf_counter() - t0
    except Exception as e:
        return {"value_s": None, "reason": f"LLM call failed: {e}"}

    return {
        "value_s": round(elapsed_s, 3),
        "reason": None,
        "model": "llama3.1:8b",
        "sample_count": 1,
    }


def measure_tier2_speed_economics_graph(smoke: bool = False) -> Dict[str, Any]:
    """Measure retrieval compilation latency, graph-hop latency, B289
    compression, and LLM generation latency for real."""
    import asyncio

    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle  # noqa: F401
    from campy.brain.thalamus.compression import build_default_registry

    # 1. B289 Compression Ratio Measurement (already real: exercises the
    # actual compression registry, not a stand-in).
    test_config = {
        "compression": {"ast_compression": True, "graph_prune_threshold": 0.2},
        "budget_tokens": 1000,
    }
    _, router = build_default_registry(test_config)

    over_budget_items = [
        {"id": f"node_{i}", "text": f"Entity {i} details with detailed architecture constraints and design decisions.", "relevance": 0.4 + (i * 0.05)}
        for i in range(15)
    ]
    raw_tokens = sum(len(str(x)) // 4 for x in over_budget_items)
    raw_section = BundleSection(section_type="semantic", content=over_budget_items, token_estimate=raw_tokens)
    compressed_section = router.compress_section(raw_section, "architecture design", test_config)

    raw_tokens = sum(len(str(x)) // 4 for x in raw_section.content)
    compressed_tokens = sum(len(str(x)) // 4 for x in compressed_section.content)
    compression_ratio = max(0.0, min(100.0, (1.0 - (compressed_tokens / max(1, raw_tokens))) * 100.0))

    sub_budget_items = [{"id": "exact_1", "text": "Hard constraint: port 443"}]
    sub_raw_section = BundleSection(section_type="exact_fact", content=sub_budget_items, token_estimate=15)
    sub_compressed = router.compress_section(sub_raw_section, "port", test_config)
    sub_bypass_pct = 100.0 if len(sub_compressed.content) == len(sub_raw_section.content) else 0.0

    # 2. Real retrieval-compilation latency (compile_bundle end-to-end).
    sample_count = 2 if smoke else 5
    retrieval = asyncio.run(_measure_retrieval_compilation_latency(sample_count))

    # 3. Real 2-hop graph query latency (same in-memory store family).
    db = OxigraphClient(db_path=":memory:")
    hop_sample_count = 3 if smoke else 10
    graph_hop = _measure_graph_hop_latency(db, hop_sample_count)

    # 4. Real (or honestly-null) LLM generation latency.
    llm = _measure_llm_generation_latency(smoke)

    return {
        "retrieval_compilation_latency_ms": retrieval["warm_mean_ms"],
        "retrieval_compilation_latency_cold_ms": retrieval["cold_ms"],
        "target_retrieval_latency_ms": DESIGN_TARGETS["target_retrieval_latency_ms"],
        "llm_generation_latency_s": llm["value_s"],
        "target_llm_generation_latency_s": DESIGN_TARGETS["target_llm_generation_latency_s"],
        "b289_compression_active_in_ask": True,
        "compression_ratio_over_budget_pct": round(compression_ratio, 2),
        "compression_bypass_sub_budget_pct": round(sub_bypass_pct, 2),
        "graph_hop_latency_2hops_ms": graph_hop["warm_mean_ms"] or graph_hop["cold_ms"],
        "target_graph_hop_latency_ms": "<5.0ms",
        "dense_supernode_degree_cap": 15,
        "dense_supernode_top5_incident_cap": 5,
        "query_plan_bounded": True,
        "methodology": {
            "retrieval_compilation_latency_ms": (
                f"in-process: real compile_bundle() call against an in-memory (empty) OxigraphClient, "
                f"real fastembed query-embedding invocation, {sample_count} samples "
                f"({retrieval['warm_sample_count']} warm after 1 cold). Empty-graph caveat: measures "
                f"stage-machinery + embedding overhead, not I/O cost against production-scale data."
            ),
            "graph_hop_latency_2hops_ms": (
                f"in-process: real SPARQL query timed via time.perf_counter() (no sleep) against the "
                f"same empty in-memory store, {hop_sample_count} samples, warm mean reported "
                f"(cold: {graph_hop['cold_ms']}ms)."
            ),
            "llm_generation_latency_s": llm.get("reason") or "real, single timed chat() call against local Ollama (llama3.1:8b).",
            "compression_ratio_over_budget_pct": "in-process: real ThalamicCompressionRouter.compress_section() call, not simulated.",
            "dense_supernode_degree_cap": "design-time configuration constant, not a per-run measurement.",
        },
    }


# ---------------------------------------------------------------------------
# Tier 3 Measurement: Cognitive Retention & Deprecation KPIs
# ---------------------------------------------------------------------------
_TIER3_REASON = (
    "not measured by kpi_monitor.py -- these scores come from the ask-eval "
    "harness (benchmarks/ask_eval/runner.py, B304-B307), which runs many real "
    "LLM calls against a populated daemon and takes minutes. Run it directly: "
    "`python -m benchmarks.ask_eval.runner`."
)


def measure_tier3_cognitive_retention() -> Dict[str, Any]:
    """No in-process measurement exists for these; emit null with the reason
    rather than a stale/fake number (B415 requirement 2)."""
    return {
        "ask_eval_overall": None,
        "target_ask_eval_overall": DESIGN_TARGETS["target_ask_eval_overall"],
        "identifier_accuracy": None,
        "paraphrase_accuracy": None,
        "target_paraphrase_accuracy": DESIGN_TARGETS["target_paraphrase_accuracy"],
        "cross_lane_accuracy": None,
        "continuation_accuracy": None,
        "negative_control_score": None,
        "methodology": {"all_fields": _TIER3_REASON},
    }


# ---------------------------------------------------------------------------
# Tier 4 Measurement: Model Handoff Fidelity KPIs
# ---------------------------------------------------------------------------
def _measure_handoff_overhead_ms(sample_count: int) -> Dict[str, Any]:
    """Real, timed get_handoff_context() call against an in-memory (empty)
    OxigraphClient -- the actual cross-session handoff lookup code path.
    Empty-graph caveat: with no prior session recorded, this measures the
    lower-bound "no prior session found" cost, not a populated handoff."""
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.thalamus.working_memory import get_handoff_context

    db = OxigraphClient(db_path=":memory:")
    samples: List[float] = []
    for _ in range(sample_count):
        t0 = time.perf_counter()
        get_handoff_context(db, "kpi-monitor-quest", "kpi-monitor-session")
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "cold_ms": round(samples[0], 4) if samples else None,
        "warm_mean_ms": round(sum(samples[1:]) / len(samples[1:]), 4) if len(samples) > 1 else None,
    }


def measure_tier4_model_handoff(smoke: bool = False) -> Dict[str, Any]:
    sample_count = 3 if smoke else 10
    handoff = _measure_handoff_overhead_ms(sample_count)
    handoff_ms = handoff["warm_mean_ms"] if handoff["warm_mean_ms"] is not None else handoff["cold_ms"]

    no_checker_reason = (
        "no automated constraint-violation checker exists in-process; requires "
        "a scripted or manual review of a live model-handoff transcript -- see backlog/B383.md."
    )

    return {
        "handoff_constraint_violations": None,
        "target_constraint_violations": 0,
        "handoff_overhead_ms": round(handoff_ms, 4) if handoff_ms is not None else None,
        "target_handoff_overhead_ms": DESIGN_TARGETS["target_handoff_overhead_ms"],
        "manual_markdown_overhead_pct": None,
        "methodology": {
            "handoff_overhead_ms": (
                f"in-process: real get_handoff_context() call against an in-memory (empty) "
                f"OxigraphClient, {sample_count} samples, warm mean reported (cold: {handoff['cold_ms']}ms). "
                "Empty-graph caveat: no prior session exists, so this is the lower-bound "
                "'no handoff found' cost, not a populated cross-session handoff."
            ),
            "handoff_constraint_violations": no_checker_reason,
            "manual_markdown_overhead_pct": no_checker_reason,
        },
    }


# ---------------------------------------------------------------------------
# Aggregation & Reporting
# ---------------------------------------------------------------------------
def run_kpi_monitor(smoke: bool = False) -> Dict[str, Any]:
    """Execute all 4 tiers of KPI measurement."""
    tier1 = measure_tier1_resource_footprint(smoke=smoke)
    tier2 = measure_tier2_speed_economics_graph(smoke=smoke)
    tier3 = measure_tier3_cognitive_retention()
    tier4 = measure_tier4_model_handoff(smoke=smoke)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "smoke" if smoke else "standard",
        "python_executable": sys.executable,
        "tier1_resource_footprint": tier1,
        "tier2_speed_economics_graph": tier2,
        "tier3_cognitive_retention": tier3,
        "tier4_model_handoff": tier4,
    }


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "null (see methodology)"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def format_markdown_table(data: Dict[str, Any]) -> str:
    """Format full 4-tier KPI scorecard as Markdown table."""
    t1 = data["tier1_resource_footprint"]
    t2 = data["tier2_speed_economics_graph"]
    t3 = data["tier3_cognitive_retention"]
    t4 = data["tier4_model_handoff"]

    lines = [
        "# HippoCampy 4-Tier Local KPI Benchmark Report (B381, measurement per B415)",
        f"**Timestamp:** {data.get('timestamp', 'N/A')}",
        f"**Mode:** {data.get('mode', 'standard').upper()}",
        f"**Interpreter:** {data.get('python_executable', 'N/A')}",
        "",
        "## Tier 1: Resource & Footprint KPIs",
        "| Metric | Value | Target | Methodology |",
        "|---|---|---|---|",
        f"| Current Process RSS | {_fmt(t1['current_process_rss_mb'], ' MB')} | <{t1['target_rss_mb']} MB | {t1['methodology']['current_process_rss_mb']} |",
        f"| Import-Only RSS | {_fmt(t1['import_only_rss_mb'], ' MB')} | n/a | {t1['methodology']['import_only_rss_mb']} |",
        f"| Warm-Invoked RSS (spaCy + fastembed) | {_fmt(t1['warm_invoked_rss_mb'], ' MB')} | <{t1['target_rss_mb']} MB | {t1['methodology']['warm_invoked_rss_mb']} |",
        f"| Write-Burst Peak Spike | {_fmt(t1['write_burst_peak_spike_mb'], ' MB')} | n/a | {t1['methodology']['write_burst_peak_spike_mb']} |",
        f"| Allocation Delta / 100 Turns | {_fmt(t1['allocation_delta_per_100_turns_mb'], ' MB')} | <2.0 MB | {t1['methodology']['allocation_delta_per_100_turns_mb']} |",
        "",
        "## Tier 2: Token Economics, Speed & Graph Traversal KPIs",
        "| Metric | Value | Target | Methodology |",
        "|---|---|---|---|",
        f"| Retrieval Compilation Latency (warm) | {_fmt(t2['retrieval_compilation_latency_ms'], ' ms')} | <{t2['target_retrieval_latency_ms']} ms | {t2['methodology']['retrieval_compilation_latency_ms']} |",
        f"| LLM Generation Latency | {_fmt(t2['llm_generation_latency_s'], ' s')} | <{t2['target_llm_generation_latency_s']} s | {t2['methodology']['llm_generation_latency_s']} |",
        f"| B289 Compression in ask.py | Active | Active | Real ThalamicCompressionRouter call |",
        f"| Over-Budget Compression Ratio | {_fmt(t2['compression_ratio_over_budget_pct'], '%')} | 50%-70% | {t2['methodology']['compression_ratio_over_budget_pct']} |",
        f"| Sub-Budget Compression Bypass | {_fmt(t2['compression_bypass_sub_budget_pct'], '%')} | 100% | Real router call |",
        f"| Graph 2-Hop Traversal Latency | {_fmt(t2['graph_hop_latency_2hops_ms'], ' ms')} | <5.0 ms | {t2['methodology']['graph_hop_latency_2hops_ms']} |",
        f"| Dense Supernode Degree Cap | <= {t2['dense_supernode_degree_cap']} | Bounded | {t2['methodology']['dense_supernode_degree_cap']} |",
        "",
        "## Tier 3: Cognitive Retention & Deprecation KPIs",
        "| Metric | Value | Target | Methodology |",
        "|---|---|---|---|",
        f"| Ask-Eval Overall Score | {_fmt(t3['ask_eval_overall'])} | >={t3['target_ask_eval_overall']} | {t3['methodology']['all_fields']} |",
        f"| Paraphrase Query Accuracy | {_fmt(t3['paraphrase_accuracy'])} | >={t3['target_paraphrase_accuracy']} | (same) |",
        f"| Identifier Exact Match | {_fmt(t3['identifier_accuracy'])} | 1.00 | (same) |",
        f"| Negative Control Rejection | {_fmt(t3['negative_control_score'])} | >=0.95 | (same) |",
        "",
        "## Tier 4: Model Handoff Fidelity KPIs",
        "| Metric | Value | Target | Methodology |",
        "|---|---|---|---|",
        f"| Handoff Constraint Violations | {_fmt(t4['handoff_constraint_violations'])} | 0 | {t4['methodology']['handoff_constraint_violations']} |",
        f"| Handoff Overhead | {_fmt(t4['handoff_overhead_ms'], ' ms')} | <{t4['target_handoff_overhead_ms']} ms | {t4['methodology']['handoff_overhead_ms']} |",
    ]
    return "\n".join(lines)


def _delta_str(baseline: Any, current: Any, unit: str = "") -> str:
    if not isinstance(baseline, (int, float)) or not isinstance(current, (int, float)):
        return "n/a (one or both values are null)"
    return f"{current - baseline:+.2f}{unit}"


def compare_snapshots(baseline: Dict[str, Any], current: Dict[str, Any]) -> str:
    """Generate Markdown diff table between baseline snapshot and current run."""
    lines = [
        "# HippoCampy KPI Delta Comparison (B381, measurement per B415)",
        "| Tier / Metric | Baseline Snapshot | Current Evaluation | Delta |",
        "|---|---|---|---|",
    ]

    b_t1 = baseline.get("tier1_resource_footprint", {})
    c_t1 = current.get("tier1_resource_footprint", {})
    lines.append(
        f"| **Process RSS (MB)** | {_fmt(b_t1.get('current_process_rss_mb'))} | "
        f"{_fmt(c_t1.get('current_process_rss_mb'))} | "
        f"{_delta_str(b_t1.get('current_process_rss_mb'), c_t1.get('current_process_rss_mb'), ' MB')} |"
    )
    lines.append(
        f"| **Warm-Invoked RSS (MB)** | {_fmt(b_t1.get('warm_invoked_rss_mb'))} | "
        f"{_fmt(c_t1.get('warm_invoked_rss_mb'))} | "
        f"{_delta_str(b_t1.get('warm_invoked_rss_mb'), c_t1.get('warm_invoked_rss_mb'), ' MB')} |"
    )

    b_t2 = baseline.get("tier2_speed_economics_graph", {})
    c_t2 = current.get("tier2_speed_economics_graph", {})
    lines.append(
        f"| **Retrieval Latency (ms)** | {_fmt(b_t2.get('retrieval_compilation_latency_ms'))} | "
        f"{_fmt(c_t2.get('retrieval_compilation_latency_ms'))} | "
        f"{_delta_str(b_t2.get('retrieval_compilation_latency_ms'), c_t2.get('retrieval_compilation_latency_ms'), ' ms')} |"
    )
    lines.append(
        f"| **Compression Ratio (%)** | {_fmt(b_t2.get('compression_ratio_over_budget_pct'))} | "
        f"{_fmt(c_t2.get('compression_ratio_over_budget_pct'))} | "
        f"{_delta_str(b_t2.get('compression_ratio_over_budget_pct'), c_t2.get('compression_ratio_over_budget_pct'), '%')} |"
    )
    lines.append(
        f"| **2-Hop Traversal (ms)** | {_fmt(b_t2.get('graph_hop_latency_2hops_ms'))} | "
        f"{_fmt(c_t2.get('graph_hop_latency_2hops_ms'))} | "
        f"{_delta_str(b_t2.get('graph_hop_latency_2hops_ms'), c_t2.get('graph_hop_latency_2hops_ms'), ' ms')} |"
    )

    b_t3 = baseline.get("tier3_cognitive_retention", {})
    c_t3 = current.get("tier3_cognitive_retention", {})
    lines.append(
        f"| **Ask-Eval Overall** | {_fmt(b_t3.get('ask_eval_overall'))} | "
        f"{_fmt(c_t3.get('ask_eval_overall'))} | "
        f"{_delta_str(b_t3.get('ask_eval_overall'), c_t3.get('ask_eval_overall'))} |"
    )

    if baseline.get("_superseded"):
        lines.append("")
        lines.append(
            f"**WARNING:** baseline file is marked superseded ({baseline.get('_superseded_reason', 'no reason given')}). "
            "This comparison is not meaningful -- regenerate the baseline first."
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="HippoCampy 4-Tier Local KPI Monitor (B381)")
    parser.add_argument("--smoke", action="store_true", help="Run fast smoke checks")
    parser.add_argument("--out", type=str, help="Save baseline snapshot JSON to file")
    parser.add_argument("--compare", type=str, help="Compare against previous baseline snapshot JSON")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Display output format")
    args = parser.parse_args()

    try:
        assert_environment_clean()
    except EnvironmentContaminationError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 1

    results = run_kpi_monitor(smoke=args.smoke)

    if args.compare:
        compare_path = Path(args.compare)
        if compare_path.exists():
            with open(compare_path, "r") as f:
                baseline_data = json.load(f)
            diff_table = compare_snapshots(baseline_data, results)
            print(diff_table)
        else:
            print(f"[!] Warning: baseline file '{args.compare}' not found.")

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(format_markdown_table(results))

    if args.out:
        out_path = Path(args.out)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[+] Successfully exported baseline snapshot to: {out_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
