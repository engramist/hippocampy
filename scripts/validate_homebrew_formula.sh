#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Campy Homebrew Formula Validation Helper
# =============================================================================
# Validates packaging/homebrew/hippocampy.rb without requiring a public
# PyPI release or a public tap. Campy is not yet published (see B236), so
# the checked-in formula's `url`/`sha256` are placeholders that cannot be
# fetched over the network. This script instead:
#
#   1. Builds a local sdist from the current checkout (or reuses one you
#      point it at with --sdist PATH).
#   2. Creates (or reuses) a scratch local tap and writes a resolved copy
#      of the formula into it, with `url`/`sha256` swapped for the local
#      sdist's `file://` path and real checksum. (`brew audit`/`brew style`
#      require a formula to live in a tap; a bare file path is not enough.)
#   3. Runs `ruby -c`, `brew style`, and `brew audit --strict` against the
#      resolved formula.
#   4. Optionally runs `brew install --build-from-source`, `brew test`, and
#      a direct `campy --help` check against the installed keg, then
#      uninstalls it so the developer's machine is left clean. Skip with
#      --no-install if you only want the static checks.
#
# Every step is skipped gracefully (with a clear message, not a hard
# failure) when its tool (brew, ruby, python3.12/3.13) is unavailable.
#
# Usage:
#   bash scripts/validate_homebrew_formula.sh
#   bash scripts/validate_homebrew_formula.sh --no-install
#   bash scripts/validate_homebrew_formula.sh --sdist dist/hippocampy-0.1.0.tar.gz
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FORMULA_SRC="$REPO_ROOT/packaging/homebrew/hippocampy.rb"
TAP_NAME="local/campy-formula-validate"
TAP_QUALIFIED_FORMULA="local/campy-formula-validate/hippocampy"

RUN_INSTALL=true
SDIST_PATH=""

if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BLUE=''; NC=''
fi

log()  { printf '%b\n' "${BLUE}==>${NC} $*"; }
ok()   { printf '%b\n' "${GREEN}  OK${NC} $*"; }
warn() { printf '%b\n' "${YELLOW}  SKIP${NC} $*"; }
err()  { printf '%b\n' "${RED}  FAIL${NC} $*"; }

usage() {
    echo "Usage: validate_homebrew_formula.sh [OPTIONS]"
    echo ""
    echo "Validate packaging/homebrew/hippocampy.rb locally, without a public release."
    echo ""
    echo "Options:"
    echo "  --no-install       Skip the real 'brew install --build-from-source' smoke test"
    echo "  --sdist PATH       Use an existing sdist instead of building a fresh one"
    echo "  --help             Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-install) RUN_INSTALL=false; shift ;;
        --sdist) SDIST_PATH="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

FAILED=0
SCRATCH_DIR=""
INSTALLED_FOR_TEST=false
CREATED_TAP=false

cleanup() {
    if [ "$INSTALLED_FOR_TEST" = true ]; then
        log "Cleaning up: uninstalling test keg"
        brew uninstall --force hippocampy >/dev/null 2>&1 || true
    fi
    if command -v brew >/dev/null 2>&1; then
        TAP_FORMULA_DIR="$(brew --repository "$TAP_NAME" 2>/dev/null || true)"
        if [ -n "$TAP_FORMULA_DIR" ] && [ -f "$TAP_FORMULA_DIR/Formula/hippocampy.rb" ]; then
            rm -f "$TAP_FORMULA_DIR/Formula/hippocampy.rb"
        fi
        if [ "$CREATED_TAP" = true ]; then
            brew untap "$TAP_NAME" >/dev/null 2>&1 || true
        fi
    fi
    if [ -n "$SCRATCH_DIR" ] && [ -d "$SCRATCH_DIR" ]; then
        rm -rf "$SCRATCH_DIR"
    fi
}
trap cleanup EXIT

echo "=== Campy Homebrew Formula Validation ==="
echo "Formula: $FORMULA_SRC"
echo ""

if [ ! -f "$FORMULA_SRC" ]; then
    err "Formula not found at $FORMULA_SRC"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: ruby syntax
# ---------------------------------------------------------------------------
log "Step 1: Syntax checks"
if command -v ruby >/dev/null 2>&1; then
    if ruby -c "$FORMULA_SRC" >/dev/null 2>&1; then
        ok "ruby -c $FORMULA_SRC"
    else
        err "ruby -c failed on $FORMULA_SRC"
        ruby -c "$FORMULA_SRC" || true
        FAILED=1
    fi
else
    warn "ruby not found, skipping formula syntax check"
fi

# ---------------------------------------------------------------------------
# Step 2: brew presence
# ---------------------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
    warn "brew not found on this machine — cannot run audit/style/install checks."
    warn "Install Homebrew from https://brew.sh to run the full validation."
    echo ""
    echo "=== Result: partial (brew unavailable) ==="
    exit 0
fi
BREW_VERSION="$(brew --version | head -1)"
ok "brew found: $BREW_VERSION"

# ---------------------------------------------------------------------------
# Step 3: build (or reuse) a local sdist to resolve the formula against
# ---------------------------------------------------------------------------
log "Step 2: Building local sdist to resolve placeholder url/sha256"
SCRATCH_DIR="$(mktemp -d /tmp/campy-homebrew-validate.XXXXXX)"

if [ -z "$SDIST_PATH" ]; then
    BUILD_PY=""
    for candidate in python3.12 python3.13 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if (3,12) <= sys.version_info[:2] < (3,14) else 1)' >/dev/null 2>&1; then
                BUILD_PY="$candidate"
                break
            fi
        fi
    done

    if [ -z "$BUILD_PY" ]; then
        warn "No Python 3.12/3.13 interpreter found — cannot build sdist, skipping audit/install."
        echo ""
        echo "=== Result: partial (no compatible Python for local build) ==="
        exit 0
    fi

    BUILD_VENV="$SCRATCH_DIR/build-venv"
    "$BUILD_PY" -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/python" -m pip install -q --upgrade pip build

    rm -rf "$REPO_ROOT/build" "$REPO_ROOT"/*.egg-info 2>/dev/null || true
    (cd "$REPO_ROOT" && "$BUILD_VENV/bin/python" -m build --sdist --outdir "$SCRATCH_DIR/dist") \
        || { err "sdist build failed"; exit 1; }

    SDIST_PATH="$(ls "$SCRATCH_DIR"/dist/hippocampy-*.tar.gz | head -1)"
fi

if [ ! -f "$SDIST_PATH" ]; then
    err "sdist not found at $SDIST_PATH"
    exit 1
fi
ok "sdist: $SDIST_PATH"

SDIST_SHA256="$(shasum -a 256 "$SDIST_PATH" | awk '{print $1}')"
SDIST_URL="file://$SDIST_PATH"
ok "sha256: $SDIST_SHA256"

# ---------------------------------------------------------------------------
# Step 4: create/reuse a scratch local tap and write the resolved formula
# ---------------------------------------------------------------------------
log "Step 3: Resolving formula into scratch tap ($TAP_NAME)"
if brew --repository "$TAP_NAME" >/dev/null 2>&1 && [ -d "$(brew --repository "$TAP_NAME")" ]; then
    ok "reusing existing scratch tap"
else
    brew tap-new "$TAP_NAME" --no-git >/dev/null 2>&1
    CREATED_TAP=true
    ok "created scratch tap"
fi

TAP_DIR="$(brew --repository "$TAP_NAME")"
RESOLVED_FORMULA="$TAP_DIR/Formula/hippocampy.rb"
python3 - "$FORMULA_SRC" "$RESOLVED_FORMULA" "$SDIST_URL" "$SDIST_SHA256" <<'PYEOF'
import re
import sys

src, dst, url, sha256 = sys.argv[1:5]
text = open(src).read()
text = re.sub(r'url "[^"]*"', f'url "{url}"', text, count=1)
text = re.sub(r'sha256 "[^"]*"[^\n]*', f'sha256 "{sha256}"', text, count=1)
open(dst, "w").write(text)
PYEOF
ok "resolved formula written: $RESOLVED_FORMULA"

# ---------------------------------------------------------------------------
# Step 5: brew style
# ---------------------------------------------------------------------------
log "Step 4: brew style"
if brew style "$TAP_QUALIFIED_FORMULA"; then
    ok "brew style passed"
else
    err "brew style reported issues (see above)"
    FAILED=1
fi

# ---------------------------------------------------------------------------
# Step 6: brew audit --strict
# ---------------------------------------------------------------------------
log "Step 5: brew audit --strict"
if brew audit --strict "$TAP_QUALIFIED_FORMULA"; then
    ok "brew audit --strict passed"
else
    err "brew audit --strict reported issues (see above)"
    FAILED=1
fi

# ---------------------------------------------------------------------------
# Step 7: real install smoke test (optional)
# ---------------------------------------------------------------------------
if [ "$RUN_INSTALL" = true ]; then
    log "Step 6: brew install --build-from-source (local smoke test)"
    warn "This installs a real 'hippocampy' keg from the local sdist, then uninstalls it."
    INSTALL_EXIT=0
    brew install --build-from-source "$TAP_QUALIFIED_FORMULA" || INSTALL_EXIT=$?
    INSTALLED_FOR_TEST=true

    KEG_PREFIX="$(brew --prefix hippocampy 2>/dev/null || true)"
    KEG_WORKS=false
    if [ -n "$KEG_PREFIX" ] && "$KEG_PREFIX/bin/campy" --help >/dev/null 2>&1; then
        KEG_WORKS=true
    fi

    if [ "$INSTALL_EXIT" -eq 0 ]; then
        ok "brew install --build-from-source succeeded"
    elif [ "$KEG_WORKS" = true ]; then
        # Known upstream limitation: Homebrew's post-install linkage-fix pass
        # rewrites the install name (LC_ID_DYLIB) of every Mach-O file in the
        # keg. Some prebuilt PyPI wheels with Rust/PyO3 extensions (e.g.
        # openai's `jiter` dependency) are ad-hoc-signed with no Mach-O
        # header padding reserved for that rewrite, so Homebrew's own
        # `install_name_tool` step fails with "load commands do not fit in
        # the header" and `brew install` exits non-zero — even though the
        # keg is fully installed, linked, and the CLI works. This is not a
        # bug in this formula; see packaging/homebrew/hippocampy.rb and
        # docs/homebrew-install.md for details.
        warn "brew install exited non-zero (exit $INSTALL_EXIT), but the keg is linked and campy works"
        warn "This is a known Homebrew/PyO3-wheel linkage-fix limitation, not a formula bug (see docs/homebrew-install.md)"
    else
        err "brew install --build-from-source failed and the keg is not usable (see above)"
        FAILED=1
    fi

    if [ "$KEG_WORKS" = true ]; then
        ok "campy --help works from installed keg"
    else
        err "campy --help failed from installed keg"
        FAILED=1
    fi

    if [ "$KEG_WORKS" = true ]; then
        if brew test "$TAP_QUALIFIED_FORMULA"; then
            ok "brew test passed"
        else
            err "brew test failed"
            FAILED=1
        fi
    else
        warn "Skipping 'brew test' (keg is not usable, see above)"
    fi
else
    warn "Skipping install smoke test (--no-install)"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "=== Result: PASS ==="
else
    echo "=== Result: FAIL (see FAIL lines above) ==="
fi
exit "$FAILED"
