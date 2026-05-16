# Plan for B239 - Homebrew Tap and macOS Native Install Path

## Metadata

- **Card ID**: B239
- **Priority**: P1
- **Dependencies**: B236, B237, B238
- **Risk**: Medium - Homebrew formulas have strict packaging expectations

## Goal

Provide a macOS-native install option for users who prefer Homebrew over `curl | bash`.

## Step 1: Draft Formula

Create `packaging/homebrew/hippocampy.rb`.

The formula should:

- install a published release artifact or PyPI package
- expose the `campy` CLI and keep `sidequests` as a legacy alias
- avoid writing user data at install time
- describe post-install `campy install` and `campy doctor`

## Step 2: Add Validation Helper

Create `scripts/validate_homebrew_formula.sh`.

It should run available checks:

- `brew audit --strict`
- local install smoke if safe
- `campy --help`

Skip gracefully if `brew` is absent.

## Step 3: Docs

Create `docs/homebrew-install.md` with:

- install command
- post-install command
- repair command
- uninstall command
- data preservation note

Update README only after local formula validation passes.

## Step 4: Validate

Run:

```bash
bash -n scripts/validate_homebrew_formula.sh
bash scripts/validate_homebrew_formula.sh
rg -n "Homebrew|brew install|campy doctor|preserve user memory" README.md docs packaging scripts
```

## Completion Notes

Mark B239 complete when the formula has been locally validated or explicitly documented as a draft pending public package publication.
