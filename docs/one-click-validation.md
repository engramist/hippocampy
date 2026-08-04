# One-Click Install Validation

How to verify `scripts/bootstrap.sh` actually works — both with an automated
harness and with a manual checklist for a real work computer. See
[backlog/B237.md](../backlog/B237.md) and [backlog/B238.md](../backlog/B238.md)
for the bugs this process exists to catch.

## Automated Validation

### Static checks (fast, no install)

```bash
bash scripts/validate_one_click_install.sh --dry-run
```

Runs `bash -n` syntax checks and `bootstrap.sh --help`/`--dry-run` only.
Safe to run anywhere, anytime.

### Full validation with an isolated temp HOME

```bash
# Skip the daemon start/status/activity checks (faster, still validates install+doctor)
bash scripts/validate_one_click_install.sh --use-temp-home --skip-daemon

# Full validation including daemon start
bash scripts/validate_one_click_install.sh --use-temp-home

# Against a specific built wheel instead of the repo checkout
bash scripts/validate_one_click_install.sh --use-temp-home --package dist/hippocampy-*.whl
```

`--use-temp-home` isolates **both** `$HOME` and `$PATH` before installing —
isolating `$HOME` alone is not enough to simulate a clean machine. A
pre-existing `campy` anywhere on the invoking shell's `$PATH` (e.g. a stale
install from a previous attempt) will silently shadow whatever the fresh
install just did, and every downstream check (`doctor`, `status`, `activity`)
will run against the wrong binary while still reporting success. This
exact failure mode was reproduced and confirmed during the B238
re-verification — the harness reported "6 passed, 0 failed" while every
check ran against a stale, unsupported-Python install instead of the one it
had just created in the isolated temp `HOME`.

### pytest suite

```bash
.venv/bin/pytest -q tests/test_bootstrap_script.py tests/test_bootstrap_clean_home.py \
    tests/test_bootstrap_installer_real.py tests/test_validation_script.py \
    tests/test_validation_harness_real.py tests/test_installer_idempotency.py \
    tests/test_doctor_cli.py
```

`tests/test_bootstrap_installer_real.py` and `tests/test_validation_harness_real.py`
run real (non-dry-run) installs via a real `pipx`, using a minimal
zero-dependency fixture package (`tests/fixtures/fake_campy_pkg`) instead of
the real `hippocampy` package, so they don't need to install
sentence-transformers/spacy/kuzu on every test run. They prove the
install/verify *mechanics* (PATH resolution, temp-HOME/PATH isolation) work
correctly. They cannot prove real `campy doctor`/`campy tool list`/daemon
behavior, since the fixture doesn't implement those subcommands meaningfully
— see "Known gaps" below.

## Manual Work-Computer Checklist

For installing on a new machine (e.g., a work computer) where a full real
install is worth doing by hand:

### Pre-Install

- [ ] macOS or Linux
- [ ] Python 3.12+ installed: `python3 --version`
- [ ] Internet access to github.com/pypi.org
- [ ] Terminal with bash or zsh
- [ ] No pre-existing `campy` on `PATH` from an earlier attempt (`command -v campy`) — if there is one, note it before proceeding so you can tell whether checks below are hitting the old or new install.

### Install

Inspect first (recommended — this installs a daemon that reads your AI
conversations):

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
bash /tmp/campy-bootstrap.sh --dry-run
bash /tmp/campy-bootstrap.sh
```

Or the one-liner directly:

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh | bash
```

### Post-Install Verification

- [ ] `campy --help` shows usage
- [ ] `which campy` (or `command -v campy`) resolves to the path the install just reported in Step 4's output — not a different, older path
- [ ] `campy doctor` passes (or shows only expected warnings for clients you don't have installed)
- [ ] `campy status` shows daemon running
- [ ] `campy activity --lines 5` shows recent activity (may be empty on a fresh install)
- [ ] `campy tool list` shows 30+ tools including `memory_decision`, `compile_context`
- [ ] `campy recall "test"` returns results (or empty if no data yet)

### Agent Registration Check

- [ ] Claude Code: `campy doctor` shows Claude Code registered (if installed)
- [ ] Codex: `~/.codex/skills/campy-memory/SKILL.md` exists (if Codex installed)
- [ ] VS Code: MCP config at `~/Library/Application Support/Code/User/mcp.json` has a campy entry (if VS Code installed)
- [ ] Gemini CLI: `GEMINI.md` has a Campy section (if Gemini CLI installed)

### Idempotency Check (run the installer a second time)

```bash
bash /tmp/campy-bootstrap.sh
```

- [ ] No duplicate entries appear in Codex/Claude/VS Code config files
- [ ] No duplicate launchd plist
- [ ] `~/.campy/brain.db` is unchanged (same size/mtime before vs. after, modulo normal daemon activity if it was running)

### Rollback

If something goes wrong:

```bash
campy uninstall --keep-data   # Remove registrations, keep memory data
# Or: pipx uninstall hippocampy
```

## Known Gaps (as of 2026-08-04)

- **Idempotency of real installs is not automated.** Testing this meaningfully needs the real `campy install` config-writing logic (which needs the real package's heavy dependencies). Only `--dry-run` idempotency is automated (`tests/test_installer_idempotency.py`). Covered by the manual checklist above instead.
- **`campy tool list` content is not verified by the automated fixture-based tests**, only checked (leniently — recorded as `skip`, not `fail`, when the tool doesn't understand the subcommand) by `scripts/validate_one_click_install.sh` itself when run against a *real* package. The lightweight test fixture (`tests/fixtures/fake_campy_pkg`) doesn't implement subcommands, so it can't provide real evidence either way.
- **No CI workflow.** Deliberately not added in this pass. The main `tests.yml` workflow already runs the full pytest suite (including the bootstrap/validation tests above) via `pip install -e .` on every push/PR, and `security-gate.yml` covers static analysis. A separate `installer-smoke.yml` (building an actual distribution wheel and installing from *that*, rather than editable dev-mode) would add real coverage of the distribution path specifically — but adding a new GitHub Actions workflow changes what runs automatically on every future push to this repo, which is a decision the repo owner should make explicitly rather than one that arrives silently inside an unrelated bug-fix change. Revisit if/when that tradeoff is explicitly wanted.
