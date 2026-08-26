# Response to VibeGuide's Agent Review

**Date:** 2026-08-25
**Scope:** Every finding raised across `campy-evaluation (1).md`, `campy-evaluation-round2.md`, and `campy-disclosure-note.md`.

Thanks for the review — it caught real gaps, and this note walks through what changed in response,
with file/PR evidence for each claim rather than just a status label. Nothing here is "trust us";
every item below points at a merged PR, a test, or an explicit documented decision you can check
against the current `main` branch.

---

## Critical findings — all fixed, with test coverage

### 1. Unauthenticated route table (16 of 18 routes had no auth)

Fixed via a global FastAPI middleware (`@app.middleware("http")` in `web/server.py`) applied to
every route except `/health`, replacing the old per-route opt-in pattern that left most routes
unprotected. Backed by `LocalSingleUserResolver` (local-only, full scopes) and
`IAMPrincipalResolver` (SigV4/STS-verified, restricted default scopes). A dedicated config flag
(`[server] dashboard_enabled`) can additionally strip the router down to just
`/health`/`/mcp`/`/sse` for minimal deployments.

Dedicated regression coverage in `tests/test_route_auth.py`: unauthenticated requests to every
non-health route are rejected when auth is enabled, `auth=none` mode keeps local routes open as
intended, and the three destructive routes you specifically named are parametrized to assert 401
when unauthenticated.

**PR:** [#55](https://github.com/engramist/hippocampy/pull/55) — B328/B330.

### 2. npm installer executing remote code via `curl | sh`-style `postinstall`

`postinstall.js` (the script npm actually auto-runs) now does nothing but print a message that no
remote code executes during install. `install.js` became a passive, opt-in CLI helper
(`npx hippocampy-install`) that the user invokes explicitly — matching the standard
auto-run-vs-explicit-invocation boundary npm itself expects installers to respect.

**PR:** [#56](https://github.com/engramist/hippocampy/pull/56) — B329.

### 3. Client-supplied header could override the server's own workspace/scope mapping

`IAMPrincipalResolver.resolve()` now treats the operator's `workspace_map`/`principal_scope_map` as
authoritative: a header that mismatches the operator's mapping raises `IAMConfigError` (hard
rejection) instead of being used as a fallback ranking, and an unmapped caller can no longer widen
its own scopes via a header. Default runtime scopes were also narrowed from "all scopes" to
`{memory.read, memory.write}` unless explicitly granted — only `LocalSingleUserResolver` (genuinely
local, single-user) gets the full scope set by default.

**PR:** [#55](https://github.com/engramist/hippocampy/pull/55) — B328/B330 (same PR as #1; both are
`campy/brain/auth.py`/`web/server.py` changes).

---

## Benchmark integrity — fixed

Findings about benchmark results implying execution of named external datasets (ARC-3, LoCoBench,
AMA-Bench, MemoryArena, SWE-CI) when only in-repo synthetic generators were actually run:

- `benchmarks/results/arc3.json` rewritten to an honest retraction (`"status": "unverified — see
  backlog/B332.md"`) rather than presenting fabricated-looking metrics.
- `benchmarks/benchmark_sources.md` now states explicitly, per synthetic benchmark, that it "does
  not run the published [X] dataset," with a dedicated closing section separating "cited as design
  inspiration" from "directly executed here." The placeholder arXiv ID implying a real linked paper
  was removed from the SWE-CI entry.
- `benchmarks/causal/__init__.py`'s docstring corrected to describe in-repo synthetic generators,
  not an implied external dataset.

**PR:** [#57](https://github.com/engramist/hippocampy/pull/57) — B331-B335.

---

## Hermes adapter calling non-existent REST endpoints — fixed

`campy/brain/brainstem/rest_api.py` now implements the exact four routes the adapter calls
(`/api/v1/recall`, `/api/v1/bundle`, `/api/v1/decide`, `/api/v1/notify`), wired into `web/server.py`.
`tests/adapters/test_hermes_adapter.py` asserts the adapter constructs correct URLs against these
real routes.

**PR:** [#58](https://github.com/engramist/hippocampy/pull/58) — B336.

---

## Content-level secret scrubbing (stored `text_raw` was unprotected, only telemetry was redacted) — fixed

`scrub_before_ingest()` (`campy/brain/brainstem/secret_scrubber.py`) now runs before content is
persisted — wired into `campy/brain/thalamus/tools/capture.py` ahead of the write, not just applied
to OTel spans/logs.

**PR:** [#62](https://github.com/engramist/hippocampy/pull/62) — B338.

---

## Cypher-usage ratchet had a scope gap (`web/` wasn't scanned) — fixed

`scripts/check_cypher_ratchet.py`'s `SCANNED_PREFIXES` now includes `web/`, so raw Cypher in
`web/server.py` is no longer invisible to the enforcement gate.

**PR:** [#57](https://github.com/engramist/hippocampy/pull/57) — bundled with the B331-B335 disclosure
fixes above.

---

## transformers CVE — eliminated (side effect of the fastembed migration)

The embedding backend migrated from `sentence-transformers`/PyTorch to `fastembed`/ONNX Runtime
(same model, verified cosine similarity 1.000000 across 200 real test sentences). `fastembed` does
not depend on the `transformers` package at all, so the CVE the old pin was stuck with no longer
applies. Also cut fresh-start daemon memory footprint from ~1.2GB to ~60-80MB for the embedding
component.

**PR:** [#93](https://github.com/engramist/hippocampy/pull/93) — B355.

---

## The four items from your latest round, in the order you raised them

### 1. `pyproject.toml` floats deps while `requirements.txt` pins exact versions — was still open, now fixed

The gap had moved from `torch`/`sentence-transformers` to `fastembed` (`pyproject.toml` had
`fastembed>=0.8.0`, `requirements.txt` had `==0.8.0`). Exact-pinned in `pyproject.toml` now, matching
`requirements.txt` and following the same precedent already set for `kuzu==0.11.3` — `fastembed` is
deliberately exact-pinned (not floated like most deps) because output parity was verified against
that specific version, and embedding vectors are schema-load-bearing.

**PR:** [#117](https://github.com/engramist/hippocampy/pull/117).

### 2. HuggingFace fetch at startup fails closed in egress-locked environments — re-investigated, confirmed this is a deliberate, already-shipped decision, not a partial fix

Re-checked `campy/brain/hippocampus/graph/embeddings.py` and `backlog/B341.md` directly rather than
assuming. Offline mode defaults to `False` (online, cache-populating) **on purpose** —
B341's own acceptance criteria explicitly require "no regression to the default (online) behavior
when offline mode is not set." When offline mode *is* enabled and the model isn't pre-cached, it
fails closed with an actionable error message telling the operator exactly how to fix it
(pre-bake the cache, or unset the offline flag/env vars).

We're standing by the default here rather than changing it: most installs run this as a local
daemon on an open-egress machine, where auto-downloading a ~60-80MB model on first run is the
correct zero-config behavior. Flipping the default to offline would break that common case to
harden a narrower one (locked-down sandboxes) that already gets clear, fail-closed behavior today.

### 3. Prompt-injection surface unmitigated by design — partially stale finding; real gap found and fixed, plus a documentation correction

Two things came out of re-checking this:

- **B339 (merged before this review round) already ships a real mitigation** we don't think you had
  visibility into: `campy/brain/thalamus/memory_formatter.py` wraps all memory content fed into
  `ask`'s LLM-facing prompt in HTML-escaped `<retrieved_memory source="..."
  trust="stored_data">...</retrieved_memory>` boundary tags, with an explicit system instruction
  that tagged content is data, not directives — the same data/instruction boundary pattern used to
  handle untrusted tool-result content generally.
- **A real gap did exist underneath that**, which we found and fixed this round:
  `anomaly_detection.py` flags content that contradicts a high-confidence constraint
  (`flagged_for_review = true`), but nothing at recall time ever consulted that flag — a flagged node
  could still be matched into the same LLM-facing prompt, unlabeled. `bundle_compiler.py`'s
  exact-fact, semantic, and graph-traversal recall stages now exclude flagged nodes, with a
  regression test (`test_excludes_nodes_flagged_for_review`) proving it.
- We also corrected `docs/ARCHITECTURE.md`'s previous framing, which overstated the Anomaly/Security
  sense as detecting "prompt injection or goal hijacking" — it's a contradiction-vs-existing-belief
  check, not an injection detector; a genuinely novel injected instruction with nothing to contradict
  isn't caught by it. The doc now states plainly what's mitigated (the `ask` prompt path, via B339),
  what isn't (a dedicated adversarial-content classifier — not built, and we think not currently
  justified — see threat model below), and the actual threat model.

**Threat model, stated explicitly since it changes how severe this is:** Campy defaults to
`LocalSingleUserResolver` — single local user, no live multi-tenant ingestion path. Ingestion is the
user's own agent-session turns or documents they explicitly point at. The realistic risk is
self-poisoning (a scraped page or malicious doc the user themselves pulls in), not third-party
attack. We think a dedicated ML injection classifier or quarantine workflow would be
over-engineering for that profile today; we'd reconsider if/when the multi-tenant `Principal` path
(scaffolded in B315 but not live) is actually turned on for untrusted external parties.

**PR:** [#118](https://github.com/engramist/hippocampy/pull/118).

### 4. No encryption at rest — confirmed as a deliberate, now-documented decision

We're not building application-level encryption for the primary KuzuDB store. This was a genuine
disclosure gap before — the only existing statement was narrowly scoped to backup snapshots — so
we've now added an explicit statement to `docs/ARCHITECTURE.md`'s Security Constraints section:
Campy is a local single-user tool, the filesystem is the trust boundary, and protection against
data-at-rest exposure (lost/stolen device, disk imaging) is expected to come from OS-level full-disk
encryption (FileVault/BitLocker/LUKS) rather than a duplicate application-layer mechanism. KuzuDB has
no native encryption support, so building transparent DB-level encryption would be substantial new
scope (key management, performance impact, backup/restore compatibility) — we don't think that
trade-off is justified for this tool's actual deployment profile, but we wanted to be explicit that
this is a considered decision, not an oversight.

**PR:** [#119](https://github.com/engramist/hippocampy/pull/119).

---

## One item you didn't raise, found independently

While your review was being closed out, we ran two live cross-agent smoke episodes against the
brain daemon under real concurrent multi-client load (a peer session's ARC-AGI-3 client, 10-step and
60-step live puzzle runs) specifically to sanity-check daemon behavior beyond unit tests. That
surfaced a real, previously-unnoticed robustness gap: `brain_daemon.py`'s `_handle_connection`
doesn't catch `ConnectionResetError`/`BrokenPipeError` when a client disconnects mid-response,
producing unhandled tracebacks instead of clean handling. No data corruption or malformed writes
resulted (confirmed against `activity.log` across both live runs — every write in the window
completed cleanly), and daemon memory was flat-to-decreasing over the runs, not growing. Filed as
`backlog/B362.md` and being fixed now as a follow-up.

We're noting it here in the interest of the same standard we're holding your findings to: report
what's actually still open, not just what's already fixed.

---

## Summary

| # | Finding | Status |
|---|---|---|
| — | Unauthenticated route table | Fixed, tested |
| — | npm `curl \| sh`-style installer | Fixed |
| — | Header outranks operator's auth map, no scope tiering | Fixed |
| — | Benchmark result/dataset conflation | Fixed |
| — | Hermes adapter calling missing routes | Fixed, tested |
| — | Content-level secret scrubbing gap | Fixed |
| — | Cypher ratchet scope gap | Fixed |
| — | transformers CVE | Eliminated (side effect of B355) |
| 1 | pyproject/requirements pin mismatch | Fixed |
| 2 | HuggingFace offline default | Confirmed working as designed (B341), not changed |
| 3 | Prompt-injection surface | Real mitigation already existed (B339); real gap found+fixed; docs corrected |
| 4 | No encryption at rest | Documented as a deliberate decision |
| — | Daemon connection-reset robustness (B362) | Found independently; fix in progress |

Happy to walk through any of this in more detail, or to have you re-verify directly against `main`.
