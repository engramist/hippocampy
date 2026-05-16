#!/usr/bin/env bash
set -euo pipefail

# Campy Private Bootstrap Installer
# Sets up Campy from a source checkout on macOS
# Usage: bash scripts/install.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Campy Private Source Bootstrap Installer ==="
echo "Repository: $REPO_ROOT"
echo ""

# Step 1: Detect OS
echo "Step 1: Detecting OS..."
OS_TYPE=$(uname -s)
if [ "$OS_TYPE" != "Darwin" ]; then
    echo "WARNING:  This script is optimized for macOS. Other systems may require adjustments."
fi
echo "  OS: $OS_TYPE"

# Step 2: Check git
echo ""
echo "Step 2: Checking git..."
if ! command -v git &> /dev/null; then
    echo "ERROR: git not found. Please install git and try again."
    exit 1
fi
GIT_VERSION=$(git --version)
echo "  ok $GIT_VERSION"

# Step 3: Check Python version
echo ""
echo "Step 3: Checking Python version..."
if ! command -v python3.12 &> /dev/null; then
    echo "WARNING:  Python 3.12 not found. Checking system python3..."
    if ! command -v python3 &> /dev/null; then
        echo "ERROR: No Python 3 found. Please install Python 3.12 or later."
        exit 1
    fi
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python3.12"
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo "  Python: $PY_VERSION"

# Check Python version is not 3.14+
PY_MAJOR_MINOR=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$(echo $PY_MAJOR_MINOR | cut -d. -f1)
MINOR=$(echo $PY_MAJOR_MINOR | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 12 ]); then
    echo "ERROR: Python 3.12 or later required. Found: $PY_MAJOR_MINOR"
    exit 1
fi

if [ "$MAJOR" -gt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 14 ]); then
    echo "ERROR: Python 3.14+ not supported yet. Found: $PY_MAJOR_MINOR"
    exit 1
fi

echo "  ok Python version OK: $PY_MAJOR_MINOR"

# Step 4: Create/upgrade venv
echo ""
echo "Step 4: Setting up virtual environment..."
if [ ! -d "$REPO_ROOT/.venv" ]; then
    echo "  Creating new venv..."
    $PYTHON_CMD -m venv "$REPO_ROOT/.venv"
else
    echo "  Upgrading existing venv..."
fi

VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
VENV_PIP="$REPO_ROOT/.venv/bin/pip"

echo "  ok Venv ready: $REPO_ROOT/.venv"

# Step 5: Upgrade pip
echo ""
echo "Step 5: Upgrading pip..."
$VENV_PIP install -U pip setuptools wheel > /dev/null 2>&1
echo "  ok pip upgraded"

# Step 6: Install package in editable mode
echo ""
echo "Step 6: Installing hippocampy in editable mode..."
cd "$REPO_ROOT"
$VENV_PIP install -e . > /dev/null 2>&1
echo "  ok Package installed"

# Step 7: Run setup
echo ""
echo "Step 7: Running campy setup..."
if $VENV_PYTHON -m sidequests.cli.main setup 2>&1 | head -20; then
    echo "  ok Setup completed"
else
    echo "  WARNING:  Setup had warnings. See above for details."
fi

# Step 8: Run doctor
echo ""
echo "Step 8: Running campy doctor..."
$VENV_PYTHON -m sidequests.cli.main doctor --lines 10 || true

# Step 9: Print next steps
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Activate the venv:"
echo "     source .venv/bin/activate"
echo ""
echo "  2. Check status:"
echo "     campy status"
echo ""
echo "  3. View live activity:"
echo "     campy activity --follow"
echo ""
echo "  4. Verify integration:"
echo "     campy doctor"
echo ""
echo "To reinstall/repair, run:"
echo "  bash scripts/install.sh"
echo ""

exit 0
