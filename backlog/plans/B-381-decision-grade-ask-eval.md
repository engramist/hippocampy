# B-381-decision-grade-ask-eval — Decision-Grade Agent Memory Benchmark Suite & Sibling Harness

**Card:** B381 | **Priority:** P1 | **Depends on:** B304, B307, B374, B384  
**Branch:** `feat/b381-decision-grade-ask-eval` | **PR Target:** `main`  
**Sibling Consumer Repo:** `/Users/djshelton/Desktop/GitProjects/campy-benchmarks`

---

## 1. Summary

Establish a rigorous, decision-grade evaluation framework for HippoCampy. To preserve Campy's `<80 MB` featherweight engine constraint (B384) and honor `docs/ecosystem-rules.md` (no consumer imports inside `campy/`), external benchmark dependencies (Pygame, Gymnasium, HuggingFace datasets) are strictly quarantined into a dedicated sibling repository: `campy-benchmarks`. 

The harness evaluates Campy strictly as an external client over standard MCP (`CAMPY_MCP_CMD`), mirroring how Claude Code, Codex, and ARC-AGI interact with the daemon in production.

---

## 2. Architecture & Ecosystem Separation

```
┌─────────────────────────────────────────────────────────────┐
│ HippoCampy Core Engine Repo (/GitProjects/hippocampy)       │
│                                                             │
│ - Brain Daemon (FastAPI / Unix domain sockets / stdio MCP)  │
│ - Gated Consolidation Loop & Thalamus Context Assembler     │
│ - In-tree Ask-Eval smoke harness (benchmarks/ask_eval/)      │
│ - Pure dependencies: pyoxigraph, sqlite-vec, fastembed      │
└──────────────────────────────▲──────────────────────────────┘
                               │
                               │ MCP stdio / HTTP
                               │ (CAMPY_MCP_CMD)
┌──────────────────────────────┴──────────────────────────────┐
│ Sibling Harness Repo (/GitProjects/campy-benchmarks)        │
│                                                             │
│ ├── locomo/       # Long-context conversational memory      │
│ ├── memory_gym/   # 2D Grid RL/spatial persistence          │
│ ├── membench/     # Multi-session persona & belief updates  │
│ ├── arc_bridge/   # Bridges sibling ARC_AGI memory metrics  │
│ └── run_all.py    # Unified scorecard & baseline comparator │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Approach

### A. Sibling Repository (`campy-benchmarks`) Setup
- Standalone Python 3.12 project with its own `.venv` and `pyproject.toml`.
- Dependencies isolated to benchmark needs (`gymnasium`, `memory-gym`, `datasets`, `pandas`, `rich`).
- Communicates with Campy solely via the standard MCP protocol:
  `export CAMPY_MCP_CMD="/Users/djshelton/Desktop/GitProjects/hippocampy/.venv/bin/python -m campy.adapters.mcp_server"`

### B. Benchmark Suite Implementations

#### 1. LoCoMo Adapter (`campy-benchmarks/locomo/`)
- Ingests multi-session dialogue turns sequentially via `notify_turn`.
- Simulates passage of time with intermediate `run_sweep()` calls.
- Evaluates probe questions:
  - Single-hop factual recall.
  - Multi-hop temporal reasoning.
  - **Dynamic Constraint Updates (Deprecation):** Verifies that updated constraints supersede older ones via `[DEPRECATED_BY]` without prompt pollution.
- Outputs: Exact Match (EM), F1, and Deprecation Accuracy %.

#### 2. MemoryGym Adapter (`campy-benchmarks/memory_gym/`)
- Evaluates `MysteryPath-v0` and `MortarMayhem-v0`.
- Observations flashed at Step 0 are written into Campy via `record_transition` / `notify_turn`.
- At each navigation step, the agent invokes `current_truth` or `ask` to retrieve the active path.
- Outputs: Success Rate %, Step Efficiency, and Retention vs. Episode Length (up to 500 steps).

#### 3. MemBench / MSC Adapter (`campy-benchmarks/membench/`)
- Ingests PersonaChat / Multi-Session Chat transcripts across 5 distinct sessions.
- In Session 5, evaluates personal fact retention and contradictory preference resolution.
- Compares token consumption under Campy's `[LOADED]` demotion against raw transcript stuffing.
- Outputs: Fact Precision/Recall, Contradiction Score, and Token Savings %.

#### 4. Sibling ARC-AGI Bridge (`campy-benchmarks/arc_bridge/`)
- Integrates with `/Users/djshelton/Desktop/GitProjects/ARC_AGI`.
- Runs memory unit suites (`test_a059_memory_hot_path_latency`, `test_a084_mechanic_memory_transfer_diagnostics`, `test_a221_disappearance_graph_write`).
- Outputs: MCP Tool Latency (<5ms cached, <50ms fresh), Rule Transfer Rate %, Disappeared Entity Recall %.

### C. Unified Scorecard & Baseline Tooling
- `run_all.py`:
  - `--baseline`: Captures the 2026-09-04 starting metrics and saves `baseline_snapshot.json`.
  - `--compare`: Runs against the live daemon and prints a side-by-side Markdown delta table.
  - Automatically exports results ready to paste into PR descriptions.

---

## 4. Concrete File Changes

### In `hippocampy`:
- Modify: `backlog/B381.md` (record sibling architecture and baseline numbers).
- Modify: `backlog/masterBacklogTracker.md` (track plan link).
- Modify: `benchmarks/ask_eval/runner.py` (lightweight in-tree smoke runner).
- Modify: `benchmarks/RESULTS.md` (record canonical baseline snapshot).

### In `campy-benchmarks` (Sibling Repo):
- Create: `pyproject.toml`, `.gitignore`, `README.md`.
- Create: `mcp_client.py` (lightweight stdio MCP client wrapper).
- Create: `locomo/runner.py`, `locomo/dataset.py`.
- Create: `memory_gym/runner.py`, `memory_gym/env_wrapper.py`.
- Create: `membench/runner.py`, `membench/msc_dataset.py`.
- Create: `arc_bridge/runner.py`.
- Create: `run_all.py`.

---

## 5. Acceptance Criteria

- [ ] Sibling repository `/Users/djshelton/Desktop/GitProjects/campy-benchmarks` initialized with isolated virtual environment.
- [ ] Zero benchmark dependencies (Gymnasium, Pygame, datasets) added to `hippocampy/pyproject.toml`.
- [ ] All benchmark suites communicate with Campy strictly over stdio/HTTP MCP via `CAMPY_MCP_CMD`.
- [ ] LoCoMo runner executes 25 multi-session scenarios and reports Deprecation Accuracy and F1.
- [ ] MemoryGym runner executes 20 episodes on `MysteryPath-v0` and reports Success Rate %.
- [ ] MemBench runner executes 5-session persona tests and reports Token Savings %.
- [ ] ARC-AGI bridge executes and records rule transfer diagnostics.
- [ ] `run_all.py --compare` prints formatted Markdown comparison tables showing deltas against the 2026-09-04 baseline.

---

## 6. Validation Commands

```bash
# In campy-benchmarks
cd /Users/djshelton/Desktop/GitProjects/campy-benchmarks
export CAMPY_MCP_CMD="/Users/djshelton/Desktop/GitProjects/hippocampy/.venv/bin/python -m campy.adapters.mcp_server"

# Run smoke test across all suites
python run_all.py --smoke

# Run full baseline snapshot
python run_all.py --baseline --out baseline_snapshot.json

# Run comparison after implementing a P0 card
python run_all.py --compare baseline_snapshot.json
```

---

## 7. Risks & Constraints

- **Execution Cost:** Running multi-session benchmarks against cloud models (Claude 3.7 / GPT-4o) incurs API costs. The harness must default to local Ollama (`llama3.1:8b`) with opt-in flags for cloud models.
- **MCP Timeout:** High-step environments like MemoryGym must bound per-step tool latency (<50ms) to avoid timeout cascades.
- **License Boundary:** `campy-benchmarks` is an internal test harness; any datasets bundled must respect their upstream non-commercial or academic research licenses without contaminating `hippocampy`'s Apache 2.0 code.
