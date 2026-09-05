"""
tests/test_kpi_monitor.py — Tests for 4-Tier Local KPI Monitor (B381).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from benchmarks.kpi_monitor import (
    CANONICAL_BASELINE_SNAPSHOT,
    measure_tier1_resource_footprint,
    measure_tier2_speed_economics_graph,
    measure_tier3_cognitive_retention,
    measure_tier4_model_handoff,
    run_kpi_monitor,
    format_markdown_table,
    compare_snapshots,
)


def test_tier1_resource_footprint():
    t1 = measure_tier1_resource_footprint(smoke=True)
    assert "current_process_rss_mb" in t1
    assert t1["current_process_rss_mb"] > 0
    assert t1["daemon_idle_rss_baseline_mb"] == 245.6
    assert t1["live_steady_state_rss_baseline_mb"] == 1200.0
    assert t1["target_rss_mb"] == 80.0
    assert t1["allocation_delta_per_100_turns_mb"] >= 0


def test_tier2_speed_economics_graph():
    t2 = measure_tier2_speed_economics_graph(smoke=True)
    assert t2["b289_compression_active_in_ask"] is True
    assert t2["compression_ratio_over_budget_pct"] >= 40.0
    assert t2["compression_bypass_sub_budget_pct"] == 100.0
    assert t2["graph_hop_latency_2hops_ms"] < 10.0
    assert t2["dense_supernode_degree_cap"] == 15
    assert t2["dense_supernode_top5_incident_cap"] == 5
    assert t2["query_plan_bounded"] is True
    assert t2["query_plan_regression_detected"] is False
    assert t2["target_retrieval_latency_ms"] == 10.0
    assert t2["target_llm_generation_latency_s"] == 1.0


def test_tier3_cognitive_retention():
    t3 = measure_tier3_cognitive_retention()
    assert t3["ask_eval_overall"] == 0.69
    assert t3["target_ask_eval_overall"] == 0.90
    assert t3["identifier_accuracy"] == 1.00
    assert t3["paraphrase_accuracy"] == 0.25
    assert t3["negative_control_score"] == 1.00


def test_tier4_model_handoff():
    t4 = measure_tier4_model_handoff()
    assert t4["handoff_constraint_violations"] == 0
    assert t4["target_constraint_violations"] == 0
    assert t4["handoff_overhead_ms"] < 500.0


def test_run_kpi_monitor():
    data = run_kpi_monitor(smoke=True)
    assert "tier1_resource_footprint" in data
    assert "tier2_speed_economics_graph" in data
    assert "tier3_cognitive_retention" in data
    assert "tier4_model_handoff" in data
    assert data["mode"] == "smoke"


def test_format_markdown_table():
    data = run_kpi_monitor(smoke=True)
    md = format_markdown_table(data)
    assert "# HippoCampy 4-Tier Local KPI Benchmark Report (B381)" in md
    assert "Tier 1: Resource & Footprint KPIs" in md
    assert "Tier 2: Token Economics, Speed & Graph Traversal KPIs" in md
    assert "Tier 3: Cognitive Retention & Deprecation KPIs" in md
    assert "Tier 4: Model Handoff Fidelity KPIs" in md
    assert "B289 Compression in ask.py" in md


def test_compare_snapshots():
    baseline = run_kpi_monitor(smoke=True)
    current = run_kpi_monitor(smoke=True)
    diff = compare_snapshots(baseline, current)
    assert "# HippoCampy KPI Delta Comparison (B381)" in diff
    assert "Process RSS" in diff
    assert "Retrieval Latency" in diff
    assert "Compression Ratio" in diff


def test_kpi_monitor_cli():
    python_bin = sys.executable
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "snapshot.json"
        cmd = [python_bin, "benchmarks/kpi_monitor.py", "--smoke", "--out", str(out_file)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert res.returncode == 0
        assert out_file.exists()

        with open(out_file) as f:
            saved = json.load(f)
        assert "tier1_resource_footprint" in saved
        assert saved["tier2_speed_economics_graph"]["b289_compression_active_in_ask"] is True

        # Test compare CLI
        cmd_compare = [python_bin, "benchmarks/kpi_monitor.py", "--compare", str(out_file)]
        res_comp = subprocess.run(cmd_compare, capture_output=True, text=True, timeout=15)
        assert res_comp.returncode == 0
        assert "HippoCampy KPI Delta Comparison" in res_comp.stdout
