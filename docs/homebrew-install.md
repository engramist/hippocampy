# Homebrew Install (macOS)

> **Status: draft, not yet public.** Campy is not yet published to PyPI and
> the `engramist/hippocampy` repository is not yet public (see
> `backlog/B236.md`). There is no public tap yet, and `brew install
> hippocampy` will not work until one exists. This document describes the
> intended flow and how the formula is validated locally today.
>
> **The canonical install path remains `pipx install hippocampy` /
> `curl -fsSL .../bootstrap.sh | bash`** (see the main [README](../README.md)
> Quickstart and `scripts/bootstrap.sh`). Homebrew is an optional, macOS-only
> alternative for users who trust `brew` more than piping a shell script —
> use it once it's public, not instead of the canonical path today.

## What the formula does (and does not do)

The formula lives at [`packaging/homebrew/hippocampy.rb`](../packaging/homebrew/hippocampy.rb).

`brew install hippocampy` will only:

- Install Python 3.12 (via `depends_on "python@3.12"`) if you don't have it.
- Create an isolated virtualenv under the Homebrew keg and install the
  `campy` CLI and its dependencies into it.
- Expose `campy` and `campy-daemon` on your `PATH`.

It will **not**:

- Create `~/.campy` or any user data.
- Start the memory daemon.
- Register with Claude Code, Codex, Gemini CLI, or any other AI client.

Those steps are intentionally left to `campy install` / `campy setup` /
`campy doctor`, run explicitly by you after the package is installed — not
done unattended during `brew install`. This mirrors how `campy install` and
`campy doctor` already behave for the `pipx`/bootstrap install path.

## Install

Once a public tap exists:

```bash
brew tap engramist/campy
brew install hippocampy
```

(or, if/when Campy is accepted into homebrew-core: `brew install hippocampy`
directly, no tap needed.)

## Post-install setup

`brew install` only gets you the CLI. Finish setup with:

```bash
campy install          # full one-command setup: LLM provider, database,
                        # adapters, daemon, per-agent plugin skills
campy setup             # detect and (re-)register with installed AI clients only
campy doctor            # diagnose an existing install
campy doctor --repair   # attempt automatic repair of what doctor finds
```

## Repair

If something looks broken after an upgrade or a partial install:

```bash
campy doctor --repair
```

`campy doctor` is safe to run repeatedly; it only reports and repairs
common problems (missing launchd plist, stale client config, missing skill
files) and never deletes memory data.

## Uninstall

```bash
brew uninstall hippocampy
```

`brew uninstall` only removes the CLI binaries and the virtualenv Homebrew
built for them. It is designed to preserve user memory by default: **it
never touches `~/.campy`** — your memory database (`brain.db`), journals,
and activity log stay in place, exactly like the bootstrap installer's
uninstall path.

To also remove Campy's AI client registrations and/or memory data, run
`campy uninstall` yourself (before or after `brew uninstall`, order doesn't
matter since it only touches `~/.campy` and client config, not the Homebrew
keg):

```bash
campy uninstall --help
campy uninstall                 # removes client registrations, keeps ~/.campy by default
campy uninstall --delete-data   # also deletes ~/.campy memory data — explicit opt-in, not the default
```

## Local validation (no public tap required)

Because there is no public release yet, the formula is validated locally
against a freshly-built sdist instead of a real download:

```bash
bash scripts/validate_homebrew_formula.sh
```

This builds a local sdist, resolves the formula's placeholder `url`/`sha256`
against it in a scratch local tap, then runs `ruby -c`, `brew style`,
`brew audit --strict`, `brew install --build-from-source`, and `brew test`
against the resolved copy. It cleans up (uninstalls the test keg, removes
the scratch tap) when it finishes. Pass `--no-install` to skip the real
install/test steps and only run the static checks. Every step is skipped
gracefully (not a hard failure) if `brew`, `ruby`, or a compatible Python
interpreter isn't available on the machine running it.

### Known limitation: `brew install` linkage warning

`brew install --build-from-source` can exit non-zero with:

```
Error: Failed changing dylib ID of .../site-packages/jiter/jiter.cpython-312-darwin.so
Error: Failed to fix install linkage
```

This is **not a bug in the Campy formula**. `jiter` (a transitive dependency
pulled in by `openai`) ships a Rust/PyO3-compiled `.so` that is ad-hoc-signed
with no Mach-O header padding reserved for Homebrew's post-install step,
which rewrites every keg binary's install name from the build path to the
`opt/` path. Homebrew's own toolchain reserves that padding
(`-headerpad_max_install_names`) when it compiles from source, but a
downloaded PyPI wheel was never compiled by Homebrew, so it has none. The
underlying file (`install_name_tool`) genuinely cannot be patched in place
without relinking it from source — something outside this formula's
control.

In practice this only affects that one rewrite step: the keg still gets
created, linked into `opt/hippocampy` and `bin/campy`, and `campy --help`
(and every other command) works normally — verified directly, both manually
and by `scripts/validate_homebrew_formula.sh`. If you hit this, ignore the
error and confirm the CLI works: `campy --help`. If Homebrew's own upstream
resolves this padding issue for downloaded wheels (or a future `jiter`
release ships more header padding), this note can be removed.
