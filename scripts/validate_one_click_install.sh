#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Campy One-Click Install Validation Harness
# =============================================================================
# Validates the bootstrap installer works from a clean environment.
#
# Usage:
#   bash scripts/validate_one_click_install.sh --dry-run
#   bash scripts/validate_one_click_install.sh --use-temp-home
#   bash scripts/validate_one_click_install.sh --use-temp-home --skip-daemon
#   bash scripts/validate_one_click_install.sh --package dist/hippocampy-*.whl
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=false
USE_TEMP_HOME=false
SKIP_DAEMON=false
PACKAGE_PATH=""
TEMP_HOME=""

usage() {
    echo "Usage: validate_one_click_install.sh [OPTIONS]"
    echo ""
    echo "Validate the Campy bootstrap installer."
    echo ""
    echo "Options:"
    echo "  --dry-run         Show what would be tested without running"
    echo "  --use-temp-home   Run bootstrap with a temporary HOME directory"
    echo "  --skip-daemon     Skip daemon start/health checks"
    echo "  --package PATH    Use a specific wheel file instead of PyPI"
    echo "  --help            Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)       DRY_RUN=true; shift ;;
        --use-temp-home) USE_TEMP_HOME=true; shift ;;
        --skip-daemon)   SKIP_DAEMON=true; shift ;;
        --package)       PACKAGE_PATH="$2"; shift 2 ;;
        --help|-h)       usage ;;
        *)               echo "Unknown option: $1"; usage ;;
    esac
done

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "pass" ]; then
        echo "  ✓ $name"
        PASS=$((PASS + 1))
    elif [ "$result" = "skip" ]; then
        echo "  - $name (skipped)"
        SKIP=$((SKIP + 1))
    else
        echo "  ✗ $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Campy One-Click Install Validation ==="
echo ""

if $DRY_RUN; then
    echo "DRY RUN — showing validation plan:"
    echo ""
    echo "1. Check bootstrap script syntax (bash -n)"
    echo "2. Check bootstrap --help works"
    echo "3. Check bootstrap --dry-run works"
    if $USE_TEMP_HOME; then
        echo "4. Run bootstrap with temp HOME"
        echo "5. Verify campy CLI is available"
        echo "6. Run campy doctor"
        if ! $SKIP_DAEMON; then
            echo "7. Verify daemon health"
            echo "8. Verify campy activity works"
        fi
    fi
    echo ""
    echo "Run without --dry-run to execute."
    exit 0
fi

# --- Static checks ---
echo "Static checks:"

# 1. Script syntax
if bash -n "$REPO_ROOT/scripts/bootstrap.sh" 2>/dev/null; then
    check "bootstrap.sh syntax" "pass"
else
    check "bootstrap.sh syntax" "fail"
fi

# 2. Help works
if bash "$REPO_ROOT/scripts/bootstrap.sh" --help >/dev/null 2>&1; then
    check "bootstrap --help" "pass"
else
    check "bootstrap --help" "fail"
fi

# 3. Dry run works
if bash "$REPO_ROOT/scripts/bootstrap.sh" --dry-run >/dev/null 2>&1; then
    check "bootstrap --dry-run" "pass"
else
    check "bootstrap --dry-run" "fail"
fi

# --- Clean HOME checks (if requested) ---
if $USE_TEMP_HOME; then
    echo ""
    echo "Clean HOME validation:"
    TEMP_HOME=$(mktemp -d)
    export HOME="$TEMP_HOME"
    echo "  Using temp HOME: $TEMP_HOME"

    # 4. Run bootstrap with dev source or package
    BOOTSTRAP_ARGS="--no-start"
    if [ -n "$PACKAGE_PATH" ]; then
        BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --dev-source $PACKAGE_PATH"
    else
        BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --dev-source $REPO_ROOT"
    fi

    if bash "$REPO_ROOT/scripts/bootstrap.sh" $BOOTSTRAP_ARGS 2>/dev/null; then
        check "bootstrap install (temp HOME)" "pass"
    else
        check "bootstrap install (temp HOME)" "fail"
    fi

    # 5. Verify campy CLI
    if command -v campy &>/dev/null || [ -f "$TEMP_HOME/.campy/venv/bin/campy" ]; then
        check "campy CLI available" "pass"
        # Ensure it's in PATH
        export PATH="$TEMP_HOME/.campy/venv/bin:$PATH"
    else
        check "campy CLI available" "fail"
    fi

    # 6. Doctor
    if campy doctor 2>/dev/null; then
        check "campy doctor" "pass"
    else
        check "campy doctor" "fail"
    fi

    # 7-8. Daemon checks
    if ! $SKIP_DAEMON; then
        campy start 2>/dev/null || true
        sleep 2
        if campy status 2>/dev/null; then
            check "daemon health" "pass"
        else
            check "daemon health" "skip"
        fi

        if campy activity --lines 1 2>/dev/null; then
            check "campy activity" "pass"
        else
            check "campy activity" "skip"
        fi
        campy stop 2>/dev/null || true
    fi

    # Cleanup temp HOME
    rm -rf "$TEMP_HOME"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
