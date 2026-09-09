"""
tests/test_kpi_monitor.py — Tests for the 4-Tier Local KPI Monitor (B381),
rewritten for B415: every metric is now a real measurement or an honest
`null` with a reason, so these tests check shape/methodology/plausibility
rather than pinning exact hardcoded values (there are none left to pin).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from benchmarks.kpi_monitor import (
    DESIGN_TARGETS,
    compare_snapshots,
    format_markdown_table,
    measure_tier1_resource_footprint,
    measure_tier2_speed_economics_graph,
    measure_tier3_cognitive_retention,
    measure_tier4_model_handoff,
    run_kpi_monitor,
)
from check_env_drift import check_env_drift


def _env_is_drifted() -> bool:
    return bool(check_env_drift()["known_harmful_present"])


def test_tier1_resource_footprint_smoke():
    t1 = measure_tier1_resource_footprint(smoke=True)
    # Real, always-available in-process measurement.
    assert t1["current_process_rss_mb"] > 0
    # Subprocess-based stages are explicitly skipped (null + reason) in smoke mode.
    assert t1["import_only_rss_mb"] is None
    assert t1["warm_invoked_rss_mb"] is None
    assert "smoke mode" in t1["methodology"]["import_only_rss_mb"]
    assert "smoke mode" in t1["methodology"]["warm_invoked_rss_mb"]
    # Real, in-process, always-on measurements.
    assert t1["write_burst_peak_spike_mb"] >= 0
    assert t1["allocation_delta_per_100_turns_mb"] >= 0
    assert t1["target_rss_mb"] == DESIGN_TARGETS["target_physical_rss_mb"]
    # Every emitted metric carries methodology (B415 requirement 3).
    for key in (
        "current_process_rss_mb",
        "import_only_rss_mb",
        "warm_invoked_rss_mb",
        "write_burst_peak_spike_mb",
        "allocation_delta_per_100_turns_mb",
    ):
        assert key in t1["methodology"] and t1["methodology"][key]


def test_tier2_speed_economics_graph_smoke():
    t2 = measure_tier2_speed_economics_graph(smoke=True)
    assert t2["b289_compression_active_in_ask"] is True
    assert t2["compression_ratio_over_budget_pct"] >= 0.0
    assert t2["compression_bypass_sub_budget_pct"] == 100.0
    # Real compile_bundle() timing -- must be a positive, plausible number.
    assert t2["retrieval_compilation_latency_ms"] > 0
    assert t2["retrieval_compilation_latency_ms"] < 10_000  # sanity ceiling
    # Real SPARQL-timed 2-hop query.
    assert t2["graph_hop_latency_2hops_ms"] is not None
    assert t2["graph_hop_latency_2hops_ms"] >= 0
    # LLM call is skipped in smoke mode -- null with a reason, not a fake number.
    assert t2["llm_generation_latency_s"] is None
    assert "smoke mode" in t2["methodology"]["llm_generation_latency_s"]
    assert t2["dense_supernode_degree_cap"] == 15
    assert t2["dense_supernode_top5_incident_cap"] == 5
    assert t2["query_plan_bounded"] is True
    assert t2["target_retrieval_latency_ms"] == DESIGN_TARGETS["target_retrieval_latency_ms"]
    assert t2["target_llm_generation_latency_s"] == DESIGN_TARGETS["target_llm_generation_latency_s"]


def test_tier3_cognitive_retention_is_honest_null():
    """No in-process measurement exists for ask-eval scores; B415 requires
    null + reason here, never a stale/fake number."""
    t3 = measure_tier3_cognitive_retention()
    for key in (
        "ask_eval_overall",
        "identifier_accuracy",
        "paraphrase_accuracy",
        "cross_lane_accuracy",
        "continuation_accuracy",
        "negative_control_score",
    ):
        assert t3[key] is None
    assert "ask_eval" in t3["methodology"]["all_fields"]
    assert t3["target_ask_eval_overall"] == DESIGN_TARGETS["target_ask_eval_overall"]


def test_tier4_model_handoff_smoke():
    t4 = measure_tier4_model_handoff(smoke=True)
    # Real, timed get_handoff_context() call.
    assert t4["handoff_overhead_ms"] is not None
    assert t4["handoff_overhead_ms"] >= 0
    assert t4["handoff_overhead_ms"] < DESIGN_TARGETS["target_handoff_overhead_ms"]
    # No automated checker exists for these -- honest null.
    assert t4["handoff_constraint_violations"] is None
    assert t4["manual_markdown_overhead_pct"] is None
    assert "no automated constraint-violation checker" in t4["methodology"]["handoff_constraint_violations"]


def test_run_kpi_monitor_smoke():
    data = run_kpi_monitor(smoke=True)
    assert "tier1_resource_footprint" in data
    assert "tier2_speed_economics_graph" in data
    assert "tier3_cognitive_retention" in data
    assert "tier4_model_handoff" in data
    assert data["mode"] == "smoke"
    assert data["python_executable"] == sys.executable


def test_format_markdown_table():
    data = run_kpi_monitor(smoke=True)
    md = format_markdown_table(data)
    assert "# HippoCampy 4-Tier Local KPI Benchmark Report" in md
    assert "Tier 1: Resource & Footprint KPIs" in md
    assert "Tier 2: Token Economics, Speed & Graph Traversal KPIs" in md
    assert "Tier 3: Cognitive Retention & Deprecation KPIs" in md
    assert "Tier 4: Model Handoff Fidelity KPIs" in md
    assert "B289 Compression in ask.py" in md
    # A null metric renders as an honest placeholder, not a blank or a "0".
    assert "null (see methodology)" in md


def test_compare_snapshots_reflects_real_variance():
    """Two independent measurement runs will not be bit-identical (unlike two
    reads of a hardcoded constant) -- this is itself evidence of real
    measurement, not a defect. compare_snapshots() must handle that."""
    baseline = run_kpi_monitor(smoke=True)
    current = run_kpi_monitor(smoke=True)
    diff = compare_snapshots(baseline, current)
    assert "# HippoCampy KPI Delta Comparison" in diff
    assert "Process RSS" in diff
    assert "Retrieval Latency" in diff
    assert "Compression Ratio" in diff


def test_compare_snapshots_warns_on_superseded_baseline():
    baseline = run_kpi_monitor(smoke=True)
    baseline["_superseded"] = True
    baseline["_superseded_reason"] = "test fixture"
    current = run_kpi_monitor(smoke=True)
    diff = compare_snapshots(baseline, current)
    assert "WARNING" in diff
    assert "superseded" in diff.lower()


def test_no_hardcoded_metric_literals_in_source():
    """Regression guard for B415's acceptance criteria: the specific
    hardcoded literal *assignments* this card was filed to remove must never
    reappear as code (the numbers themselves are still discussed in the
    module docstring's history section, which is fine -- prose, not code)."""
    source = Path(__file__).resolve().parent.parent.joinpath("benchmarks", "kpi_monitor.py").read_text()
    # Strip the leading module docstring (after the shebang) so
    # historical-context prose (which legitimately names these old numbers)
    # can't produce a false failure.
    start = source.index('"""')
    end = source.index('"""', start + 3) + 3
    code_only = source[end:]
    assert '"daemon_idle_rss_mb": 245.6' not in code_only
    assert '"live_steady_state_rss_mb": 1200.0' not in code_only
    assert '"write_burst_peak_spike_mb": 1100.0' not in code_only
    assert "28.5 if not smoke else 8.5" not in code_only
    assert "CANONICAL_BASELINE_SNAPSHOT" not in code_only
    assert "245.6" not in code_only
    assert "1200.0" not in code_only
    assert "1100.0" not in code_only


def test_kpi_monitor_cli_environment_gate():
    """main() must abort (exit 1, clear stderr message) when run in a
    drifted environment, and succeed normally when the environment is
    clean -- exercised against whichever interpreter runs this test, so the
    assertion adapts to that interpreter's actual drift state rather than
    assuming one or the other."""
    python_bin = sys.executable
    repo_root = Path(__file__).resolve().parent.parent
    drifted = _env_is_drifted()

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "snapshot.json"
        cmd = [python_bin, "benchmarks/kpi_monitor.py", "--smoke", "--out", str(out_file)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(repo_root))

        if drifted:
            assert res.returncode == 1, res.stderr
            assert "ABORT" in res.stderr
            assert not out_file.exists()
            return

        assert res.returncode == 0, res.stderr
        assert out_file.exists()

        with open(out_file) as f:
            saved = json.load(f)
        assert "tier1_resource_footprint" in saved
        assert saved["tier2_speed_economics_graph"]["b289_compression_active_in_ask"] is True

        cmd_compare = [python_bin, "benchmarks/kpi_monitor.py", "--smoke", "--compare", str(out_file)]
        res_comp = subprocess.run(cmd_compare, capture_output=True, text=True, timeout=60, cwd=str(repo_root))
        assert res_comp.returncode == 0
        assert "HippoCampy KPI Delta Comparison" in res_comp.stdout
