# B-46 Plan — Benchmark Source Verification and Dataset Pinning

## Goal
Implement backlog card B46 by creating reproducible benchmark source lock artifacts for P11.

## Inputs
- `backlog/B46.md`
- existing `benchmarks/` directory contents
- `requirements.txt`, `pyproject.toml`

## Deliverables
1. `benchmarks/benchmark_sources.md`
- For each benchmark: source URL, citation, release date, license, notes.
- Targets:
  - SWE-CI
  - LoCoBench
  - AMA-Bench
  - MemoryArena (mark experimental if unstable)
  - Autonomous research simulation harness (local/custom)
2. `benchmarks/benchmark_lock.json`
- Pinned refs (`tag` or `commit`), expected task counts, checksum placeholders or concrete checksums where available.
3. `benchmarks/setup_matrix.md`
- Per-benchmark setup requirements (python version, docker, disk, env vars).
4. Update `backlog/B46.md`
- Link produced artifacts.

## Implementation Steps
1. Inspect current benchmark files/config and gather known versions.
2. Build source table with explicit confidence labels where data is uncertain.
3. Generate lock JSON with consistent schema keys for all benchmarks.
4. Mark unavailable/unstable artifacts as `experimental` with fallback plan.

## Constraints
- Documentation + metadata only (no benchmark runner code changes here).
- Do not fabricate versions silently; mark unknown values explicitly.
- Keep JSON machine-readable and stable for future automation.

## Validation
- `python3 -m json.tool benchmarks/benchmark_lock.json >/dev/null`
- Ensure all target benchmarks have entries in all three outputs.

## Definition of Done
- Reproducible source/lock artifacts exist and are linked from B46.
- Unknowns are explicit and actionable, not implicit assumptions.
