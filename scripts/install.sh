#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_banner() {
    printf '%b\n' "${BLUE}====================================${NC}"
    printf '%b\n' "${BLUE}Installing HippoCampy Memory${NC}"
    printf '%b\n' "${BLUE}====================================${NC}"
    printf '\n'
}

fail() {
    printf '%b\n' "${RED}$1${NC}" >&2
    exit 1
}

info() {
    printf '%b\n' "${YELLOW}$1${NC}"
}

ok() {
    printf '%b\n' "${GREEN}$1${NC}"
}

python_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1
}

find_python() {
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && python_supported "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

run_pipx() {
    if command -v pipx >/dev/null 2>&1; then
        pipx "$@"
    else
        "$PYTHON_CMD" -m pipx "$@"
    fi
}

print_banner

OS_TYPE="$(uname -s)"
if [ "$OS_TYPE" != "Darwin" ] && [ "$OS_TYPE" != "Linux" ]; then
    fail "Unsupported OS: $OS_TYPE. Campy supports macOS and Linux."
fi

ARCH_TYPE="$(uname -m)"
printf 'OS: %s\n' "$OS_TYPE"
printf 'Arch: %s\n\n' "$ARCH_TYPE"

info "[1/5] Checking Python 3.12+..."
PYTHON_CMD="$(find_python || true)"
if [ -z "$PYTHON_CMD" ]; then
    if [ "$OS_TYPE" = "Darwin" ]; then
        info "Python 3.12+ not found. Installing python@3.12 with Homebrew..."
        if ! command -v brew >/dev/null 2>&1; then
            fail "Homebrew is not installed. Install it from https://brew.sh and re-run this script."
        fi
        brew install python@3.12
        PYTHON_CMD="$(brew --prefix python@3.12)/bin/python3.12"
        python_supported "$PYTHON_CMD" || fail "Installed python@3.12 but could not execute a supported Python interpreter."
    else
        fail "Python 3.12 or 3.13 is required. Install it with your package manager and re-run this script."
    fi
fi
ok "Found $($PYTHON_CMD --version 2>&1)"

info "[2/5] Checking build dependencies (cmake)..."
if ! command -v cmake >/dev/null 2>&1; then
    if [ "$OS_TYPE" = "Darwin" ]; then
        info "cmake not found. Installing via Homebrew (required to build KuzuDB)..."
        if ! command -v brew >/dev/null 2>&1; then
            fail "Homebrew is not installed. Install it from https://brew.sh and re-run this script."
        fi
        brew install cmake
    else
        fail "cmake is required to build KuzuDB. Install it with your package manager (e.g. 'sudo apt install cmake') and re-run."
    fi
fi
ok "cmake available ($(cmake --version | head -1))"

info "[3/5] Checking pipx..."
if ! command -v pipx >/dev/null 2>&1; then
    info "Installing pipx into user space..."
    "$PYTHON_CMD" -m ensurepip --upgrade >/dev/null 2>&1 || true
    "$PYTHON_CMD" -m pip install --user --upgrade pip pipx
    "$PYTHON_CMD" -m pipx ensurepath >/dev/null 2>&1 || true
fi

USER_BASE_BIN="$($PYTHON_CMD -c 'import site; print(site.USER_BASE)')/bin"
export PATH="$HOME/.local/bin:$USER_BASE_BIN:$PATH"
if ! run_pipx --version >/dev/null 2>&1; then
    fail "pipx is installed but not runnable. Open a new shell and try again."
fi
ok "pipx available"

info "[4/5] Installing HippoCampy via pipx..."
if run_pipx list 2>/dev/null | grep -q "package hippocampy"; then
    info "Existing HippoCampy installation detected. Upgrading..."
    run_pipx upgrade hippocampy || run_pipx install hippocampy --force
else
    run_pipx install hippocampy
fi
ok "HippoCampy installed"

if command -v campy >/dev/null 2>&1; then
    CAMPY_BIN="$(command -v campy)"
elif [ -x "$HOME/.local/bin/campy" ]; then
    CAMPY_BIN="$HOME/.local/bin/campy"
elif [ -x "$USER_BASE_BIN/campy" ]; then
    CAMPY_BIN="$USER_BASE_BIN/campy"
else
    fail "Installed hippocampy, but could not find the 'campy' command on PATH. Open a new shell and run 'campy setup'."
fi

info "[5/5] Running campy setup..."
"$CAMPY_BIN" setup
ok "Campy setup completed"

printf '\n'
printf '%b\n' "${GREEN}HippoCampy installed successfully.${NC}"
printf '%s\n' "Commands:"
printf '%s\n' "  campy status     Check daemon health"
printf '%s\n' "  campy start      Start the brain daemon"
printf '%s\n' "  campy setup      Re-register AI agent integrations"
