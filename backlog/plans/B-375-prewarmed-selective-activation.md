# B-375-prewarmed-selective-activation — Pre-Warmed Selective Activation for Anticipatory Retrieval

**Card:** B375 | **Priority:** P1 | **Depends on:** B91, B252, B279, B283, B384  
**Branch:** `feat/b375-prewarmed-selective-activation` | **PR Target:** `main`

---

## 1. Summary

Transform retrieval from a purely reactive pull into an anticipatory state machine using a bounded "warm frontier" data structure. Passive intake (file paths, error messages, branch names) during `notify_turn` pre-activates relevant graph neighborhoods, dropping retrieval compilation latency to <5ms and injecting relevant lessons before agents make errors.

---

## 2. Technical Design

### A. Warm Frontier Data Structure (`campy/brain/temporal_lobe/warm_frontier.py`)
- Bounded set of active node IDs with activation scores `[0.0, 1.0]`.
- Configuration: `max_warm_nodes = 50`, `decay_half_life_turns = 5`.
- **Dense Supernode Safeguard (`performance-and-debugging.md`):** If `degree(node) > 50`, bypass open neighbor expansion; selectively expand strictly the top 5 incident edges sorted by `pathway_strength DESC`.

### B. Passive Ingestion Activation Flow
- On every turn ingested via `notify_turn`, extract recognized entity tokens and paths.
- Perform a lightweight 1-to-2 hop neighbor expansion via `gateway.py`.
- Boost activation scores for connected Decisions, Constraints, and Lessons.
- Bounded execution latency: <5ms.

### C. Thalamic Retrieval Integration
- `bundle_compiler.py` checks the warm frontier during candidate scoring.
- Boost candidate scores: `score *= (1.0 + warm_score * 0.35)`.
- Cold-start fallback: standard scoring preserved when warm frontier is empty.

---

## 3. Concrete File Changes

- Create: `campy/brain/temporal_lobe/warm_frontier.py`
- Modify: `campy/brain/temporal_lobe/loop/step4b_associative.py`
- Modify: `campy/brain/thalamus/bundle_compiler.py`
- Modify: `campy/brain/brainstem/config.py` & `campy.toml`
- Create: `tests/test_warm_frontier.py`

---

## 4. Acceptance Criteria

- [ ] Warm frontier maintains capacity $\le 50$ nodes with temporal decay.
- [ ] Ingestion updates warm frontier in <5ms.
- [ ] Supernodes (>50 degree) capped to top-5 incident edges by pathway strength.
- [ ] Retrieval compilation latency drops to <5ms for pre-warmed queries.
- [ ] 100% test pass on `tests/test_warm_frontier.py`.
