# Freeze, drift controls and PR clean-up (2026-10-20)

## R68: #318 observation expansion, on top of Observations

Re-gated on main with Observations on (cat 1–4): conv-42 5 gained / 5 lost, conv-30
0 / 1, adversarial 53 → 50 /77. Stopped after two conversations: with Observations
on, the expansion adds nothing, and #318 had already used its fix attempt. #318
stays closed. Its earlier gain (R59, Observations off) came from the observations
themselves.

## The machine froze during LongMemEval (R61)

A fresh-ingest LongMemEval s run (~500 turns per question, observation extraction
on) froze the Mac; the owner had to hard-reboot. No crash or jetsam report, disk
had 376 GB free, Ollama answered normally until a minute before. Cause not
confirmed; most likely memory: the answer model (~9 GB) and the judge (~17 GB)
resident in Ollama, plus the benchmark daemon and the personal daemon both
extracting observations. Replay gates had run 30+ hours without trouble.

Changes:
- `~/campy-lead/memguard.sh` runs alongside the queue: logs free memory, swap and
  the top processes every 30 s; stops the running job's process tree if free memory
  stays under 12% for three checks.
- During long fresh-ingest runs the personal daemon's observation extraction is
  paused with `launchctl setenv CAMPY_OBSERVATIONS_ENABLED 0` (clears on reboot).
  The benchmark job sets `CAMPY_OBSERVATIONS_ENABLED=1` for its own daemon so the
  run still measures main as shipped. Note: the personal daemon reads the repo's
  `campy.toml` (launchd working directory), not `~/.campy/config.toml`.
- With both in place R61 restarted; free memory has stayed at 32% or more.

## Drift controls (B495, #335)

Lessons from a related knowledge-graph project: agents drift toward their own
defaults (paperwork, rule-tweaking, prompt rewording) unless short principles sit
in the one file every agent reads and tooling enforces them. Seven principles now
head `AGENTS.md`; the PR template requires Principle / Lever and target / Score
effect; CI fails a PR that touches retrieval, answering or config code without a
Score effect; `scripts/drift_report.py` reports commits by kind, gate mentions and
PRs without a score (run daily by the lead's loop). The lead's loop gained a
stopping rule: stop when the queue is empty and nothing waits for a gate.

## Old PRs cleared (first drift report)

- #224 (B427 batch 4: ARC/wiki read queries that silently returned nothing) —
  6 of its 8 bugs were still on main; merged.
- #260 — duplicate of #259; closed.
- #281 — a second B466 implementation. Its tests found 4 cases main got wrong,
  two of which wrote false supersessions ("Do not replace Memcached with Redis"
  recorded Redis REPLACES Memcached). Ported as B496 (#336); closed.
- #265 — a 40-file save-gate draft, never landed, card numbers colliding with
  merged cards. Closed at the owner's request; reusable parts recorded in
  `backlog/B492.md` (#337).
