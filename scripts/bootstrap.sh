#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# HippoCampy Bootstrap Installer
# =============================================================================
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh | bash
#
# Inspect first:
#   curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
#   bash /tmp/campy-bootstrap.sh --dry-run
#   bash /tmp/campy-bootstrap.sh
# =============================================================================

VERSION="0.1.0"
PACKAGE_NAME="hippocampy"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12
CAMPY_VENV_DIR="$HOME/.campy/venv"

# Defaults
DRY_RUN=false
DEV_SOURCE=""
NO_START=false
NO_REGISTER=false

# Colors (if terminal supports it)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BLUE='' NC=''
fi

usage() {
    echo "Usage: bootstrap.sh [OPTIONS]"
    echo ""
    echo "Install HippoCampy AI memory system."
    echo ""
    echo "Options:"
    echo "  --dry-run           Show what would be done without making changes"
    echo "  --dev-source PATH   Install from local source checkout instead of PyPI"
    echo "  --version VERSION   Install specific version (default: latest)"
    echo "  --no-start          Don't start the daemon after install"
    echo "  --no-register       Don't register with detected AI agents"
    echo "  --help              Show this help message"
    exit 0
}

log() { echo -e "${BLUE}==>${NC} $*"; }
ok()  { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
err() { echo -e "${RED}  ✗${NC} $*"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)    DRY_RUN=true; shift ;;
        --dev-source) DEV_SOURCE="$2"; shift 2 ;;
        --version)    VERSION="$2"; shift 2 ;;
        --no-start)   NO_START=true; shift ;;
        --no-register) NO_REGISTER=true; shift ;;
        --help|-h)    usage ;;
        *)            err "Unknown option: $1"; usage ;;
    esac
done

echo ""
echo "=== HippoCampy Bootstrap Installer ==="
echo ""

if $DRY_RUN; then
    warn "DRY RUN — no changes will be made"
    echo ""
fi

# -------------------------------------------------------------------------
# Step 1: Check OS
# -------------------------------------------------------------------------
log "Step 1: Checking OS..."
OS_TYPE=$(uname -s)
if [ "$OS_TYPE" = "Darwin" ]; then
    ok "macOS detected"
elif [ "$OS_TYPE" = "Linux" ]; then
    ok "Linux detected"
else
    warn "$OS_TYPE detected — some features may require manual setup"
fi

# -------------------------------------------------------------------------
# Step 2: Check Python
# -------------------------------------------------------------------------
log "Step 2: Checking Python..."
PYTHON_CMD=""
for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" &>/dev/null; then
        PY_VERSION=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        PY_MAJOR=$("$candidate" -c "import sys; print(sys.version_info.major)")
        PY_MINOR=$("$candidate" -c "import sys; print(sys.version_info.minor)")
        if [ "$PY_MAJOR" -ge "$MIN_PYTHON_MAJOR" ] && [ "$PY_MINOR" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON_CMD="$candidate"
            ok "Found $candidate ($PY_VERSION)"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR not found."
    err "Install Python 3.12+ from https://python.org and try again."
    exit 1
fi

# -------------------------------------------------------------------------
# Step 3: Install package
# -------------------------------------------------------------------------
log "Step 3: Installing HippoCampy package..."

# B237: which bin directory Step 4 should check depends on which branch
# below actually ran - pipx and uv each install into their OWN isolated bin
# dir (usually ~/.local/bin, but resolved properly rather than assumed),
# never $CAMPY_VENV_DIR. Populated by every branch so Step 4 has a single,
# correct place to look regardless of which install method was used.
INSTALL_BIN_DIR=""

if [ -n "$DEV_SOURCE" ]; then
    # Development mode: install from local source
    log "  Installing from local source: $DEV_SOURCE"
    if $DRY_RUN; then
        ok "Would install from $DEV_SOURCE (dev mode)"
    else
        if command -v pipx &>/dev/null; then
            pipx install "$DEV_SOURCE" --force --python "$PYTHON_CMD"
            INSTALL_BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
            pipx ensurepath --quiet 2>/dev/null || true
        else
            "$PYTHON_CMD" -m venv "$CAMPY_VENV_DIR"
            "$CAMPY_VENV_DIR/bin/pip" install -U pip
            "$CAMPY_VENV_DIR/bin/pip" install "$DEV_SOURCE"
            INSTALL_BIN_DIR="$CAMPY_VENV_DIR/bin"
        fi
        ok "Installed from local source"
    fi
elif command -v pipx &>/dev/null; then
    # Preferred: pipx for isolated install
    log "  Using pipx (recommended)..."
    if $DRY_RUN; then
        ok "Would run: pipx install $PACKAGE_NAME"
    else
        pipx install "$PACKAGE_NAME" --force --python "$PYTHON_CMD" 2>/dev/null || {
            # If PyPI package not published yet, install from GitHub
            warn "PyPI package not found, installing from GitHub..."
            pipx install "git+https://github.com/engramist/hippocampy.git" --force --python "$PYTHON_CMD"
        }
        INSTALL_BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
        # Persist the PATH fix for future shells too, not just this run -
        # pipx's own post-install message tells the user to do exactly
        # this; do it for them rather than leaving Step 4 to paper over it
        # every single run.
        pipx ensurepath --quiet 2>/dev/null || true
        ok "Installed via pipx"
    fi
elif command -v uv &>/dev/null; then
    # Alternative: uv tool
    log "  Using uv tool..."
    if $DRY_RUN; then
        ok "Would run: uv tool install $PACKAGE_NAME"
    else
        uv tool install "$PACKAGE_NAME" 2>/dev/null || {
            warn "PyPI package not found, installing from GitHub..."
            uv tool install "git+https://github.com/engramist/hippocampy.git"
        }
        INSTALL_BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
        uv tool update-shell &>/dev/null || true
        ok "Installed via uv"
    fi
else
    # Fallback: managed venv
    log "  No pipx/uv found, using managed venv at $CAMPY_VENV_DIR..."
    if $DRY_RUN; then
        ok "Would create venv at $CAMPY_VENV_DIR and install $PACKAGE_NAME"
    else
        "$PYTHON_CMD" -m venv "$CAMPY_VENV_DIR"
        "$CAMPY_VENV_DIR/bin/pip" install -U pip
        "$CAMPY_VENV_DIR/bin/pip" install "$PACKAGE_NAME" 2>/dev/null || {
            warn "PyPI package not found, installing from GitHub..."
            "$CAMPY_VENV_DIR/bin/pip" install "git+https://github.com/engramist/hippocampy.git"
        }
        INSTALL_BIN_DIR="$CAMPY_VENV_DIR/bin"
        # Add to PATH hint
        ok "Installed to $CAMPY_VENV_DIR"
        warn "Add to your PATH: export PATH=\"$CAMPY_VENV_DIR/bin:\$PATH\""
    fi
fi

# -------------------------------------------------------------------------
# Step 4: Verify campy CLI is available
# -------------------------------------------------------------------------
log "Step 4: Verifying campy CLI..."
if $DRY_RUN; then
    ok "Would verify: campy --help"
else
    if command -v campy &>/dev/null; then
        ok "campy CLI found: $(which campy)"
    elif [ -n "$INSTALL_BIN_DIR" ] && [ -f "$INSTALL_BIN_DIR/campy" ]; then
        export PATH="$INSTALL_BIN_DIR:$PATH"
        ok "campy CLI found at $INSTALL_BIN_DIR/campy"
        warn "Add to your PATH for future shells: export PATH=\"$INSTALL_BIN_DIR:\$PATH\""
    else
        err "campy CLI not found in PATH after install"
        err "Try: export PATH=\"${INSTALL_BIN_DIR:-$CAMPY_VENV_DIR/bin}:\$PATH\""
        exit 1
    fi
fi

# -------------------------------------------------------------------------
# Step 5: Run campy install (agent registration + daemon setup)
# -------------------------------------------------------------------------
if ! $NO_REGISTER; then
    log "Step 5: Running campy install (agent detection + registration)..."
    if $DRY_RUN; then
        ok "Would run: campy install"
    else
        campy install || {
            warn "campy install had warnings — running doctor for diagnosis"
        }
        ok "Agent registration complete"
    fi
else
    log "Step 5: Skipping agent registration (--no-register)"
fi

# -------------------------------------------------------------------------
# Step 6: Run campy doctor
# -------------------------------------------------------------------------
log "Step 6: Running diagnostics..."
if $DRY_RUN; then
    ok "Would run: campy doctor --repair"
else
    campy doctor --repair || {
        warn "Some doctor checks failed — review output above"
    }
fi

# -------------------------------------------------------------------------
# Step 7: Start daemon
# -------------------------------------------------------------------------
if ! $NO_START; then
    log "Step 7: Starting daemon..."
    if $DRY_RUN; then
        ok "Would run: campy start"
    else
        campy start || {
            warn "Daemon start had issues — check: campy status"
        }
    fi
else
    log "Step 7: Skipping daemon start (--no-start)"
    echo "  Start manually with: campy start"
fi

# -------------------------------------------------------------------------
# Done
# -------------------------------------------------------------------------
echo ""
echo "=== Installation Complete ==="
echo ""
echo "Quick commands:"
echo "  campy status          — check daemon health"
echo "  campy doctor          — run diagnostics"
echo "  campy recall <query>  — search memory"
echo "  campy activity -f     — watch live memory activity"
echo ""
if $DRY_RUN; then
    echo "(This was a dry run — no changes were made)"
fi
