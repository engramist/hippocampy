# One-Click Install Release Gate

**Status as of this document: GO for promoting the one-click command as the
canonical/primary install path.** `hippocampy` 0.1.0 published to PyPI on
2026-08-18 (https://pypi.org/project/hippocampy/0.1.0/; see
[B327](backlog/B327.md)) — the literal Quickstart command now works for a
real user.

This is the final go/no-go checklist for Campy's one-click install story
(B236 package path, B237 hosted bootstrap script, B238 clean-machine
validation harness, B239 Homebrew tap). It exists so a maintainer can look
at one document, run a short list of commands, and decide whether it is
honest to tell users "just run this one command" as the *primary*,
first-recommended way to install Campy.

See also: [`docs/troubleshooting-install.md`](troubleshooting-install.md),
[`docs/one-click-validation.md`](one-click-validation.md),
[`docs/homebrew-install.md`](homebrew-install.md),
[`docs/public-release-audit.md`](public-release-audit.md).

## Go/No-Go Decision Record

| Question | Answer |
|---|---|
| Is `bootstrap.sh` itself correct and validated? | **Yes** (B237, B238 — see below). |
| Does `pipx install hippocampy` (the thing `bootstrap.sh` runs by default) work today, for a real user, right now? | **Yes.** `hippocampy` 0.1.0 was published to PyPI on 2026-08-18 (https://pypi.org/project/hippocampy/0.1.0/). Verified in a clean venv: `pip install hippocampy`, then `campy --help` and `campy doctor --help` both run cleanly. |
| Is the gap disclosed anywhere a user would see it before running the one-liner? | N/A — the gap is closed. `README.md`'s Quickstart and Install sections present `pipx install hippocampy` as the recommended path without caveat. |
| Verdict | **GO** on calling the one-click command *canonical*. |

**Why this was NO-GO until 2026-08-18.** B236's own re-verification
(`backlog/B236.md`, "Re-verification Notes (2026-08-03)") recorded two
acceptance criteria as genuinely unmet, not stylistic nitpicks:

1. **README did not label the install command's publish status, and the
   literal top command did not work.** `pipx install hippocampy` failed
   (`ERROR: No matching distribution found for hippocampy`) because
   the package had never been published to PyPI.
2. **No TestPyPI dry-run completion or skip record existed.** The publish
   *procedure* is documented (`docs/release-publish-checklist.md`), but no
   one had run it against TestPyPI, and no one had written down a reasoned
   decision to skip it.

Both are now closed. (1): `hippocampy` 0.1.0 was published to real PyPI on
2026-08-18 (B327), and README's Install section now presents
`pipx install hippocampy` as the single recommended path. (2): the TestPyPI
dry run was explicitly skipped — no separate TestPyPI account/token existed,
and build/`twine check`/audit/packaging tests had already passed repeatedly
against the real artifacts (see B236's closure notes) — a reasoned,
documented decision rather than a silent gap. Source install remains
available as an alternative that works regardless of PyPI status.

**What flipped this to GO:** `hippocampy` was published to PyPI on
2026-08-18 (B327), so the literal Quickstart command now works for a real
user.

## Supported Platforms

| Platform | Support | Notes |
|---|---|---|
| macOS (Apple Silicon, arm64) | **Supported** | Primary development/validation platform for B237/B238/B239. |
| macOS (Intel, x86_64) | **Supported, less tested** | Same code paths as Apple Silicon; no Intel-specific validation run recorded. |
| Linux (x86_64, glibc, e.g. Ubuntu 22.04/24.04) | **Supported** | `bootstrap.sh` and `scripts/install.sh` are POSIX/bash; daemon uses `systemd`-independent polling, no launchd dependency. Validated in this card's own sandbox re-run (Linux x86_64, Python 3.12). |
| Linux (musl/Alpine) | **Unsupported / unverified** | Not tested against musl libc; some ML dependencies (kuzu, sentence-transformers, spacy) ship manylinux wheels that may not resolve on musl. |
| Windows (native, no WSL) | **Unsupported** | `bootstrap.sh`/`install.sh` are bash scripts; no `.ps1`/`.bat` equivalent exists. `launchd` checks are macOS-only and silently pass as "not macOS" elsewhere, but there is no Windows service-manager integration at all. |
| Windows (WSL2) | **Untested, likely works** | Should behave like Linux inside the WSL2 distro, but no one has run the validation harness there. Treat as unsupported until someone does. |
| Python < 3.12 or >= 3.14 | **Unsupported, rejected explicitly** | `bootstrap.sh` Step 2 exits 1 with an actionable message; `campy doctor`'s Python Version check fails outside 3.12–3.13. |

Homebrew (B239) is macOS-only and explicitly optional/non-canonical — see
"Package Path Status" below.

## Required Validation Commands and Expected Results

Every command below was actually run for this card in a Linux x86_64
sandbox (Python 3.12.3, fresh `.venv`). Exact captured output is in this
card's completion report; this table records the pass/fail bar each command
must clear.

| # | Command | Expected result |
|---|---|---|
| 1 | `rg -n "one-click\|bootstrap.sh\|doctor --repair\|activity --follow\|~/.campy\|uninstall\|Codex\|Claude\|VS Code" README.md Instalation_Instructions.md docs` | Non-empty matches across README and `docs/`; confirms the required topics are actually documented, not just claimed. (`Instalation_Instructions.md` does not exist — see "Known Limitations" below — so it contributes no matches; that is expected, not a failure.) |
| 2 | `bash scripts/audit_public_release.sh --release` | Exits 0, prints `AUDIT PASSED: No high-risk patterns detected`, with `dist/` wheel+sdist built first (`python -m build --wheel --sdist`) since `--release` mode requires artifacts to exist. |
| 3 | `.venv/bin/campy doctor` | Non-zero count of individual checks pass; on a fresh sandbox with no daemon running, `Daemon` and `Launchd`/`MCP Clients` checks are *expected* to fail (nothing installed system-wide yet) — that is normal for a dev checkout, not a release blocker. What matters is that the command runs without crashing and reports real, legible status per check. |
| 4 | `.venv/bin/pytest -q tests/test_public_release_manifest.py tests/test_packaging_installed_mode.py tests/test_bootstrap_script.py tests/test_bootstrap_clean_home.py` | All non-skipped tests pass. `test_public_release_manifest.py` / `test_packaging_installed_mode.py` tests skip individually if `dist/` isn't present when pytest runs standalone — build `dist/` first (see command 2) for full coverage. |

Additional commands validated by the prerequisite cards, re-listed here so
this is a complete gate rather than a pointer to four other documents:

| # | Command (from B236/B237/B238/B239) | Expected result |
|---|---|---|
| 5 | `python -m build --wheel --sdist` | Wheel + sdist produced, zero errors. |
| 6 | `python -m twine check dist/*` | `PASSED` for both artifacts. |
| 7 | `bash -n scripts/bootstrap.sh` | Clean (no syntax errors). |
| 8 | `bash scripts/bootstrap.sh --dry-run` | Exits 0, prints planned actions, creates no files. |
| 9 | `bash -n scripts/validate_one_click_install.sh` | Clean. |
| 10 | `bash scripts/validate_one_click_install.sh --use-temp-home --skip-daemon` | Isolates `$HOME` and `$PATH`, resolves the freshly-installed binary (not a stale one), ends `N passed, 0 failed`. |
| 11 | `brew audit --strict packaging/homebrew/hippocampy.rb` | Exits 0 against a local/scratch tap (macOS only; not run in this Linux sandbox — carried forward from B239's own validation). |

## npm Wrapper Install Behavior

The npm wrapper no longer executes remote installer code during `npm install`.
It prints an instruction message and requires explicit opt-in via:

```bash
npx hippocampy-install
```

The installer script fetch is pinned to an immutable Git ref and checksum-
verified before execution.

## Package Path Status (B236)

**complete-with-caveats.** Build, twine check, audit, pipx install, uv
install, and venv install all independently re-verified with real command
execution (32/32 real, non-mocked pytest at the time of B236's
re-verification). Two acceptance criteria remain genuinely unmet:

1. TestPyPI dry-run never executed or explicitly skipped-with-reason.
2. README did not label the `pipx install hippocampy` command's actual
   publish status (fixed by this card — see README's Install section).

`hippocampy` is confirmed **not yet on PyPI**
(`pip index versions hippocampy` → no matching distribution).

## Bootstrap Status (B237)

**complete.** The original Step-4 bug (pipx bin directory never resolved,
so a fresh pipx install was invisible to the script's own verification
step, either hard-failing or silently falling through to a stale
pre-existing `campy` on `PATH`) is fixed and independently re-verified with
a real, non-mocked pipx install against an isolated `$HOME`/`$PATH`. One
acceptance criterion remains genuinely unautomated: idempotency of a real
(non-dev-source, full-dependency) install run twice — needs `hippocampy`'s
real heavy dependencies, which the lightweight test fixture deliberately
avoids. Documented as a known gap, not silently dropped.

## Clean-Machine Status (B238)

**complete.** `docs/one-click-validation.md` exists (132 lines) with an
automated-validation section, a manual work-computer checklist, and a
"Known Gaps" section. The harness's own PATH-isolation bug (found during
B238's own re-verification) is fixed and confirmed via real execution on a
machine that still carries the exact stale-binary confound the bug
depended on. Idempotent-repeat, partial-install repair, daemon-socket, and
activity-log checks remain genuinely unautomated for the same
real-dependency reason as B237 — covered by the manual checklist instead.

## Homebrew Status (B239, optional)

**complete**, explicitly optional and explicitly not canonical. The formula
is validated locally (`brew audit --strict`, `brew install
--build-from-source` against a scratch tap) but its `url`/`sha256` still
point at placeholder coordinates — they were never updated to the real
PyPI release now that one exists (B327); that update is tracked as a
separate follow-up, not part of this card. `docs/homebrew-install.md`
states: *"brew install hippocampy will not work until [a public tap]
exists... The canonical install path remains pipx install hippocampy /
curl ... bootstrap.sh"* — consistent with this gate's verdict above, since
`pipx install hippocampy` is now the canonical path and Homebrew stays
macOS-only and secondary regardless.

## Known Limitations

- **The repo (`engramist/hippocampy`) is not confirmed public.** The
  `curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/...`
  URLs in README/bootstrap docs assume a public GitHub repo at that path;
  this has not been independently re-confirmed as part of this card.
- **`Instalation_Instructions.md` does not exist in this repository.**
  It was deliberately deleted by B297 (recorded in
  `docs/public-disclosure-boundary.md`, "Documentation & User Guides"
  table: *"Stale test-machine Q&A that contradicted the README's install
  story; typo'd filename... Deleted — README's Install section is the
  updated version this row called for"*). B240's own card and plan still
  list it as MODIFY, inherited unchanged from before B297 ran. Recreating a
  file a prior card explicitly removed as stale/duplicative — without a
  fresh, explicit decision to reverse that — would reintroduce the exact
  problem B297 fixed. This card instead puts the required user-facing
  quickstart/troubleshooting content in `README.md`'s Install section (already
  the designated replacement per B297) and in the new
  `docs/troubleshooting-install.md`. If a maintainer wants the file back
  under that exact name, that is a product decision to make explicitly, not
  a side effect of running this card's validation commands.
- **Real (non-fixture) idempotency, partial-install repair, and
  daemon/activity checks are not automated** — see B237/B238 status above.
  Covered by `docs/one-click-validation.md`'s manual checklist.
- **Windows has no native support.** See Supported Platforms.
- **`campy doctor` on a fresh dev sandbox reports expected failures**
  (no daemon running, no client configs present) — this is normal, not a
  regression; see command 3's expected result above and this card's
  completion report for the actual captured output.

## Re-Gating This Document

Re-run this gate (all 11 commands above) whenever any of B236/B237/B238/B239
change, or before any change to README's install framing (canonical vs.
recommended vs. pending). Update the Go/No-Go Decision Record and Known
Limitations sections honestly — do not flip to GO without re-checking
whether `hippocampy` has actually been published to PyPI in the interim.
