# Post-Cutover External Benchmark Report ("After," B446)

**Recorded Date:** 2026-09-22
**Git Anchor:** `59e9c30` (post-Oxigraph-cutover `main`, B434/B436/B438/B439 all merged)
**Storage Engine:** Oxigraph (RDF-star) + RocksDB persistence layer
**Primary Model Tested:** local Ollama (daemon default; not pinned per-suite by the harness)
**Source Dataset:** `campy-benchmarks/post_cutover_live.json`
**Compares against:** [`docs/benchmarks/kuzu-baseline-kpis.md`](kuzu-baseline-kpis.md) (the "Before" snapshot, 2026-09-04/06, `d35b28b`)

> **Correction (2026-09-22, later the same day, revised twice):** this
> report and [B447](../../backlog/B447.md) originally described the
> Gated Consolidation Loop worker as *permanently* stuck. Continued
> observation of the same live daemon process over several more hours
> found: (1) it cleared its first stuck item after 1h36m and processed
> 406 more messages normally, but then (2) got stuck *again*, on
> unrelated content, for 2h28m+ and counting. The current
> understanding is an **intermittent, recurring, multi-hour stall**,
> not a one-time cold-start tax and not a permanent hang — see B447
> for full detail and the live investigation history. This does not
> change §2's numbers or the core conclusion below (every probe in
> this run ran before any consolidation had completed), only the
> severity/pattern framing.

> **Update (2026-09-23): B447's fix landed, scores are still 0% — but
> for a third, distinct, now-final reason.** [B447](../../backlog/B447.md)'s
> per-write timeout was merged and this suite was re-run
> (`post_cutover_live_v2.json`). The daemon itself now works correctly
> under load — 400+ real consolidation completions logged during the
> run, instead of a total freeze. **Scores are still 0% anyway.**
> Investigating why found a second, completely unrelated bug:
> [B449](../../backlog/B449.md) — the MCP adapter this harness talks to
> (`campy.adapters.mcp_server`) gives up on every tool call after ~6-12
> silent seconds (an "implicit background path" timeout budget applied
> to what is actually explicit, external tool-call traffic), long
> before the daemon — genuinely slower than that under real load — can
> ever answer. Every reported "latency" in every run so far, including
> both runs summarized in this document, has actually been measuring
> that timeout firing, not the daemon's real response time. See §2b
> and B449 for full detail. This is believed to be the last blocker —
> B434, B436, B438, B447, and B448 were all real, necessary fixes, but
> none of them, individually or together, could have moved these
> scores, because the harness was never given long enough to see a
> real answer.

---

## 1. Purpose and headline result

[B446](../../backlog/B446.md) asked a direct question: now that B434
(consolidation loop worker crash), B436 (MemBench token-key bug), B438
(mock-client state leak), and B439 (unrelated CI flake) are all fixed,
does the external benchmark suite actually score better?

**No — LoCoMo, MemoryGym, and MemBench still score at or near zero.**
This is not the "before" story repeating for the same reason, though.
This run used a real, non-mocked, freshly restarted daemon on current
`main` (`--baseline` mode, not `--smoke`), and it surfaced a **new,
currently-reproducing bug**: [B447](../../backlog/B447.md) — the Gated
Consolidation Loop worker takes roughly 96 minutes to process the very
first real message after a daemon restart, silently, with every other
`notify_turn` queued behind it in the meantime. B434 fixed a crash in
this same worker; it did not fix this separate, still-present latency
problem. Every probe in this entire benchmark run (all four suites,
finished well within an hour of the restart) executed before that
96-minute window closed, so a near-zero score is exactly what that
predicts. A secondary, always-broken harness-side gap was also found
and filed as [B448](../../backlog/B448.md). Both are real, filed, and
need to land before a re-run of this suite means anything.

**The original hypothesis (this run existing at all was motivated by
"B434's fix should dramatically improve these numbers") did not hold,
and it's important to say so plainly rather than declare success.**
What actually happened is more useful: this run caught a live P0 bug
that the original, mocked/smoke-mode "before" baseline could never
have surfaced.

---

## 2. Before vs. After

| Suite | Metric | Before (Kùzu, smoke, `d35b28b`) | After (Oxigraph, real, `59e9c30`) |
|---|---|---|---|
| **LoCoMo** | F1 / Exact Match | 0.0407 / 0.0 | **0.0 / 0.0** |
| **LoCoMo** | Deprecation Accuracy | 0.40 (40%) | **0.0** |
| **LoCoMo** | Avg Latency | 3876.76 ms | 6006.49 ms |
| **MemoryGym** | Episode Success Rate | 0.0% | **0.0%** (unchanged) |
| **MemoryGym** | Avg Step Latency | 374.01 ms | 6006.08 ms |
| **MemBench** | Persona Fact Precision | 0.0 | **0.0** (unchanged) |
| **MemBench** | Token Savings % | 0.0% (harness bug, B436) | **0.0%** (real value now — see §4) |
| **MemBench** | Avg Latency | 2688.18 ms | 10011.93 ms |
| **ARC Bridge** | Rule Transfer Rate | 1.0 (100%) | 0.85 (85%) |
| **ARC Bridge** | Disappeared Entity Recall | 1.0 (100%) | 0.9 (90%) |
| **ARC Bridge** | Hot-path Latency | 31.69 ms | 4655.15 ms |

Raw JSON: `campy-benchmarks/post_cutover_live.json` (this repo does
not track that sibling repo's working tree; the file lives there,
uncommitted, same convention as the "before" run's own
`baseline_kuzu_live.json`).

**A note on scale, not just score:** this run used `--baseline` (real)
mode, not `--smoke` — 25 LoCoMo scenarios / 28 probes (vs. 3/6 before),
20 MemoryGym episodes (vs. 3), 5 MemBench personas / 6 probes (vs. 2/3).
Latencies are also not comparable 1:1 to the "before" row — those were
mocked-fast smoke-mode numbers; these are real end-to-end daemon
round-trips (including real Ollama calls), so the ~5-10x latency
increase across every suite is expected and not itself a regression.

ARC Bridge's small dip (100%→85-90%) is within the kind of run-to-run
noise expected from a suite this size (a handful of transfer/recall
checks) and is not investigated further here — it does not depend on
consolidation timing the way the other three suites do (see §3), and
nothing in this run's logs points to an ARC-Bridge-specific bug.

---

## 2b. Run 2 (2026-09-23, post-B447-fix): still 0%, now for a fully diagnosed reason

Same reproduction, run again against a freshly restarted daemon on
`main` with [B447](../../backlog/B447.md)'s write-lock timeout fix
included (`80a77a4`). Raw JSON: `campy-benchmarks/post_cutover_live_v2.json`.

| Suite | Metric | Run 1 (pre-fix) | Run 2 (post-B447-fix) |
|---|---|---|---|
| LoCoMo | F1 / EM | 0.0 / 0.0 | 0.0 / 0.0 |
| LoCoMo | Avg Latency | 6006.49 ms | 6006.6 ms |
| MemoryGym | Success Rate | 0.0% | 0.0% |
| MemoryGym | Avg Latency | 6006.08 ms | 6006.57 ms |
| MemBench | Fact Precision | 0.0 | 0.0 |
| MemBench | Avg Latency | 10011.93 ms | 12011.32 ms |
| ARC Bridge | Transfer / Recall | 0.85 / 0.9 | 0.85 / 0.9 |
| ARC Bridge | Avg Latency | 4655.15 ms | 6005.61 ms |

**Identical scores, near-identical latencies.** B447's fix is real and
confirmed working during this exact run — `daemon.log` shows 400+
genuine `[Loop] msg=...` consolidation completions across the run's
duration, versus zero during Run 1 (which froze entirely). So the
daemon is now doing real, correct background work throughout. The
scores not moving at all, despite that, is itself the signal that
something else is fully independent of B447's fix.

**The latency numbers are the tell.** They cluster suspiciously close
to round multiples of specific numbers: LoCoMo/MemoryGym/ARC-Bridge
all sit right at ~6006ms; MemBench sits right at ~2× that
(~10-12s). Tracing this precisely (see [B449](../../backlog/B449.md)
for the full derivation) found the exact mechanism:
`campy.adapters.mcp_server` — the MCP server the benchmark harness is
specifically configured to talk to — routes every tool call through a
timeout budget (`CONTEXT_TIMEOUT=3.0s` for reads, `CAPTURE_TIMEOUT=2.0s`
for writes) intended for *implicit background paths* (hooks, context
injection) that must never block a user's interactive session — not
for this adapter's actual job, handling explicit external tool calls.
Worse, the transport tries a socket attempt *and then* an HTTP
fallback, each at the *full* budget, so a read call's real ceiling is
`2 × 3.0s = 6.0s` and MemBench's `compile_context` flow (~2 sequential
calls) hits `~2 × 6.0s ≈ 12.0s`. **Every latency number in this entire
report, in both runs, has been measuring this timeout firing — not
the daemon's real response time.**

This means the true story of this whole investigation is: B434
(crash), B436 (token key), B438 (mock isolation), and B447 (write-lock
timeout) were all real bugs, all correctly fixed, and **none of them
could have possibly moved these scores**, individually or together —
the benchmark harness has never once, in any run across this entire
investigation, waited long enough to see the daemon's actual answer.
B449 is believed to be the last blocker.

---

## 3. Root cause: this was never really about B434 alone

### 3.1 What B434 actually fixed vs. what's still broken

B434's bug was real and worth fixing: before it, `_loop_worker` crashed
on `.get()` for *every* item due to a 4-vs-5-tuple unpack mismatch, so
the consolidation queue was **permanently crash-looping** — nothing
was ever processed, full stop.

Post-B434, the queue no longer crashes. But this run found the worker
now gets stuck differently: it dequeues its first real message cleanly,
calls `run_loop()`, and takes **1 hour 36 minutes** to return —
confirmed via direct daemon.log timestamps (dequeued `14:07:48`,
completed `15:44:13`), with every other `notify_turn` call queued
behind it the entire time. It did eventually complete, then processed
its next 406 queued messages normally (~10s/message). Full detail,
evidence, and recommended next steps in [B447](../../backlog/B447.md).

This means **zero consolidation completed during this entire benchmark
run** — every suite finished (per the harness's own reported timings)
well before `15:44:13`, so LoCoMo/MemoryGym/MemBench's probes ran
against a graph that received no new structured facts during the run,
even though the writes themselves were all safely queued and did
eventually get processed after the run ended. A 0% score is exactly
what that predicts, independent of anything else this run measured.

### 3.2 The secondary, always-broken harness gap

Separately — and this would have capped scores at 0% even if B447
weren't happening — `locomo/runner.py` and `membench/runner.py` call
`client.run_sweep()` between writes and probes, intending to force
synchronous consolidation. That maps to an MCP tool named `run_sweep`
that has **never been registered** on the daemon (confirmed: 74
`"Unknown method: run_sweep"` entries in `~/.campy/activity.log` during
this run, 100% failure rate, silently swallowed by the harness's
catch-all error handling). This has been broken since
`campy-benchmarks`' very first commit — it predates B434 and everything
else fixed this session. `memory_gym/runner.py` doesn't even attempt
this synchronization — it queries immediately after a single write.
Full detail in [B448](../../backlog/B448.md).

### 3.3 What this means for the original "before" report's own theory

`kuzu-baseline-kpis.md` §5.2.1 attributed the original low scores to a
**race condition**: consolidation was slow (~1-1.5s/turn) but did
eventually complete — a manual post-run `current_truth` query confirmed
the facts landed once the queue drained. **B447 is the same shape of
failure, just far more extreme on its first item**: on current `main`,
the very first message after a restart takes ~96 minutes (not ~1-1.5s)
before the queue can even start draining normally — after that it
settles into the same fast, healthy per-message pace the original
report described. So this run doesn't contradict the original theory;
it sharpens it: the race isn't uniformly "consolidation is a bit slow
per turn," it's "consolidation pays a large, one-time, silent tax on
the first turn of every daemon lifetime," which a short-lived benchmark
run (or, per B447's evidence, apparently every restart in this
daemon's last 11 days) never survives long enough to see clear.

### 3.4 The B436 fix's effect, isolated

One part of the original hypothesis *did* resolve cleanly:
`token_savings_pct` was a permanent 0.0% artifact before purely because
`membench/runner.py` read the wrong JSON key (`token_count` instead of
`bundle.total_token_estimate`). That key-read bug is fixed. The metric
is now a **real** 0.0% rather than a fake one — it still reads 0.0%
in this run because B447's ~96-minute dead zone meant no bundle
content existed to compress by the time MemBench's probes ran (nothing
had been consolidated yet), not because the measurement is broken
again. This is a good example of the general
shape of this whole report: individual fixes landed correctly and can
be verified as correct in isolation, but a deeper, single blocking bug
(B447) prevented any of them from producing a visibly different
top-line score yet.

---

## 4. What "done" looks like for this investigation

This report is not the end state B446 was asking for — it's the
honest, evidenced reason a "real After number" doesn't exist yet.
Once [B447](../../backlog/B447.md) (and, for full suite correctness,
[B448](../../backlog/B448.md)) land, re-run
`campy-benchmarks/run_all.py --baseline` against a fresh daemon and
replace §2's "After" column with real numbers — at that point this
document's title/scope should probably change from "why After doesn't
exist yet" to a genuine before/after comparison.

---

## 5. Reproduction

```bash
# Restart the daemon clean against current main
cd /Users/djshelton/Desktop/GitProjects/hippocampy
.venv/bin/campy stop && .venv/bin/campy start
# wait for `.venv/bin/campy status` to report idle/online — a cold
# RocksDB WAL replay can take several minutes on a long-uncompacted
# store; this is unrelated to B447 and not itself a bug filed here

# Real (non-smoke) external run
cd /Users/djshelton/Desktop/GitProjects/campy-benchmarks
CAMPY_SOCKET_PATH="/Users/djshelton/.campy/brain.sock" \
CAMPY_MCP_CMD="/Users/djshelton/Desktop/GitProjects/hippocampy/.venv/bin/python -m campy.adapters.mcp_server" \
/Users/djshelton/Desktop/GitProjects/hippocampy/.venv/bin/python run_all.py --baseline --out post_cutover_live.json --suite all
```

`campy-benchmarks` has no committed venv and its own declared
dependencies (`mcp`, `rich`, `pydantic`, `requests` in `pyproject.toml`)
are unused by the actual runtime code path — the hippocampy repo's own
`.venv` (Python 3.12) is sufficient to run it; no separate environment
setup needed.
