# Principles

<!-- Single source. Imported by CLAUDE.md and GEMINI.md (@PRINCIPLES.md); copied verbatim between the principles markers in AGENTS.md and .github/copilot-instructions.md (tests/test_principles_in_sync.py keeps the copies identical). Edit here, then update the copies. -->

These bind every agent working here. If a change cannot say which principle it serves, stop and ask.

1. **The benchmark score is the measure.** Every change to retrieval or answering names its target and reports its gate result on the published metric (LoCoMo categories 1-4, LongMemEval overall, DMR accuracy). Receipts and paperwork are not progress.
2. **Graph first.** The graph store (Oxigraph today) is the single source of truth; no shadow stores (the detailed rule is under Sources Of Truth). The graph holds the knowledge, and answers that can be computed from it (count, sum, latest, list, exists, before/after) are computed by a query anchored on the subject; Python never counts, filters or joins what a query could. Load `skills/campy-graph/SKILL.md` before capture, retrieval or answering work.
3. **The model advises; rules decide.** Retrieved evidence stays linked to its source turn; anything a model writes into memory is a candidate until a rule or an independent source confirms it.
4. **Generalise, don't memorise.** No rule fitted to one benchmark question or dataset; a fix names the general construction and must hold on held-out conversations.
5. **Fix the structure, not the wording.** Prefer retrieval and structural changes over prompt rewording; wording changes swing results by noise alone.
6. **Measure correctly before believing.** Every result records what ran (commits, flags, prompts); doubt the scorer and the answer key before the pipeline.
7. **Small, reversible, one lever per PR.** Ship behind a flag, gate it, then flip the default.
8. **Subjects are the backbone.** Every fact hangs off its subject entity by a typed relation to an object entity, or is flagged unanchored. If an answer needs an edge that capture does not write, fix capture first; never approximate the missing edge in Python.

### Signs of drift

- A week of commits with no gate result.
- New docs, receipts or process files that no score depends on.
- A fix that matches one question rather than a general construction.
- Prompt rewording as the main change.
- Persistent data held outside the graph.
- Answer logic in Python over text or rows that a graph query could compute.
- A gate that holds too few of the lever's target questions to see it move.
- A PR that cannot say which principle it serves.

Run `python scripts/drift_report.py` to check for these; CI (`pr-score-effect`) requires a `## Score effect` section on PRs that touch retrieval, answering or config code.
