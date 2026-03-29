# B-47-benchmark-infrastructure — Local Benchmark Runner Infrastructure (Unified Harness)

**Card:** B47 | **Priority:** P11 | **Depends on:** None (harness foundation)

## Summary
Build unified local benchmark runner infrastructure. Enables systematic evaluation of SideQuests across multiple benchmarks without repetitive setup.

## Technical Approach

### Harness Structure
```
benchmarks/harness.py:
  - Harness base class
  - Benchmark discovery and registration
  - Common setup/teardown (model load, daemon init)
  - Run controller (batch execution)

benchmarks/config.yaml:
  - LLM provider settings
  - Memory/CPU limits
  - Timeout policies
  - Result output format
```

### Benchmark Interface
Each benchmark (`arc3/`, `longcontext/`, etc.) implements:
- `HarnessConfig` — benchmark-specific parameters
- `run_benchmark()` — entry point
- `parse_results()` — standardized output
- `validate_outputs()` — compliance check

### Common Layer
- Model initialization with resource checks
- Session management
- Logging/telemetry
- Results aggregation

## Files to Create/Modify

- `benchmarks/__init__.py`
- `benchmarks/harness.py` — base harness class
- `benchmarks/config.yaml` — unified config schema
- `benchmarks/runner.py` — main entry point
- `tests/test_harness.py` — harness behavior

## Acceptance Criteria

1. Single harness that loads and runs multiple benchmarks
2. Common setup (model, memory checks) is run once per session
3. Each benchmark can be run individually or as batch
4. Results are aggregated in standardized format
5. Resource monitoring (CPU, memory, disk) is included
6. Timeout/resource limit enforcement works

## Notes

- Foundation for B48-B57 benchmark cards
- Must support async/parallel execution for efficiency
