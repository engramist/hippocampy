# B237 - Hosted One-Line Bootstrap Installer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a public bootstrap script so users can install Campy with one command: `curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash`

**Architecture:** `scripts/bootstrap.sh` detects Python, prefers `pipx` (falls back to managed venv at `~/.campy/venv`), installs the hippocampy package, runs `campy install` + `campy doctor --repair`, and reports what succeeded. Supports `--dry-run`, `--dev-source`, `--no-start`, `--help`.

**Tech Stack:** Bash, pipx/pip, existing `campy install` and `campy doctor` commands

**Key existing files:**
- `scripts/install.sh` — existing source-checkout installer (private, requires repo clone)
- `scripts/release_build.sh` — from B236, builds wheel artifacts
- `campy/cli/install.py` — Python installer with 8-step flow
- `campy/cli/doctor.py` — diagnostic checker with `--repair` flag

---

### Task 1: Create Bootstrap Script

**Files:**
- Create: `scripts/bootstrap.sh`
- Create: `tests/test_bootstrap_script.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap_script.py
"""Test the bootstrap installer script."""
from pathlib import Path
import subprocess

def test_bootstrap_script_exists():
    """Bootstrap script should exist."""
    assert Path("scripts/bootstrap.sh").exists()

def test_bootstrap_script_syntax():
    """Script should pass bash -n syntax check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/bootstrap.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"

def test_bootstrap_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "set -euo pipefail" in content

def test_bootstrap_script_supports_dry_run():
    """Script should support --dry-run flag."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "--dry-run" in content
    assert "DRY_RUN" in content or "dry_run" in content

def test_bootstrap_script_supports_help():
    """Script should support --help flag."""
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout

def test_bootstrap_script_checks_python():
    """Script should check for Python version."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "python" in content.lower()
    assert "3.12" in content or "python3" in content

def test_bootstrap_script_prefers_pipx():
    """Script should check for pipx before falling back."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "pipx" in content

def test_bootstrap_script_never_deletes_brain_db():
    """Script must NEVER delete brain.db."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "rm" not in content or "brain.db" not in content
    # Check no dangerous rm -rf on campy dir
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "rm -rf" in stripped and ".campy" in stripped:
            assert False, f"Dangerous delete found: {stripped}"

def test_bootstrap_script_calls_campy_install():
    """Script should call campy install after package install."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "campy install" in content or "campy setup" in content

def test_bootstrap_script_calls_doctor():
    """Script should call campy doctor for diagnostics."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "campy doctor" in content

def test_bootstrap_dry_run_does_not_install():
    """--dry-run should not actually install anything."""
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True,
        timeout=30
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout or "dry run" in result.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap_script.py::test_bootstrap_script_exists -v`
Expected: FAIL — script doesn't exist

- [ ] **Step 3: Create the bootstrap script**

Create `scripts/bootstrap.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# HippoCampy Bootstrap Installer
# =============================================================================
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash
#
# Inspect first:
#   curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
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

if [ -n "$DEV_SOURCE" ]; then
    # Development mode: install from local source
    log "  Installing from local source: $DEV_SOURCE"
    if $DRY_RUN; then
        ok "Would install from $DEV_SOURCE (dev mode)"
    else
        if command -v pipx &>/dev/null; then
            pipx install "$DEV_SOURCE" --force
        else
            "$PYTHON_CMD" -m venv "$CAMPY_VENV_DIR"
            "$CAMPY_VENV_DIR/bin/pip" install -U pip
            "$CAMPY_VENV_DIR/bin/pip" install "$DEV_SOURCE"
        fi
        ok "Installed from local source"
    fi
elif command -v pipx &>/dev/null; then
    # Preferred: pipx for isolated install
    log "  Using pipx (recommended)..."
    if $DRY_RUN; then
        ok "Would run: pipx install $PACKAGE_NAME"
    else
        pipx install "$PACKAGE_NAME" --force 2>/dev/null || {
            # If PyPI package not published yet, install from GitHub
            warn "PyPI package not found, installing from GitHub..."
            pipx install "git+https://github.com/djs54/hippocampy.git" --force
        }
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
            uv tool install "git+https://github.com/djs54/hippocampy.git"
        }
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
            "$CAMPY_VENV_DIR/bin/pip" install "git+https://github.com/djs54/hippocampy.git"
        }
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
    elif [ -f "$CAMPY_VENV_DIR/bin/campy" ]; then
        export PATH="$CAMPY_VENV_DIR/bin:$PATH"
        ok "campy CLI found at $CAMPY_VENV_DIR/bin/campy"
    else
        err "campy CLI not found in PATH after install"
        err "Try: export PATH=\"$CAMPY_VENV_DIR/bin:\$PATH\""
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
```

- [ ] **Step 4: Make executable**

```bash
chmod +x scripts/bootstrap.sh
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_bootstrap_script.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/bootstrap.sh tests/test_bootstrap_script.py
git commit -m "feat(B237): create hosted one-line bootstrap installer"
```

---

### Task 2: Update README with Install Commands

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README**

Read `README.md` to find the installation section.

- [ ] **Step 2: Add bootstrap install commands**

Find the installation section in `README.md` and add/update it with:

```markdown
## Installation

### Quick Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash
```

### Inspect First

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
bash /tmp/campy-bootstrap.sh --dry-run   # See what it will do
bash /tmp/campy-bootstrap.sh             # Run it
```

### Manual Install

```bash
pipx install hippocampy    # or: pip install hippocampy
campy install              # Detect and register AI agents
campy doctor               # Verify everything works
campy start                # Start the memory daemon
```

### Developer Install

```bash
git clone https://github.com/djs54/hippocampy.git
cd hippocampy
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
campy install
```
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(B237): add bootstrap install commands to README"
```

---

### Task 3: Idempotency Tests

**Files:**
- Create: `tests/test_installer_idempotency.py`

- [ ] **Step 1: Write idempotency tests**

```python
# tests/test_installer_idempotency.py
"""Test that bootstrap and install commands are idempotent."""
from pathlib import Path
import subprocess

def test_bootstrap_dry_run_twice():
    """Running bootstrap --dry-run twice should succeed both times."""
    for _ in range(2):
        result = subprocess.run(
            ["bash", "scripts/bootstrap.sh", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

def test_bootstrap_help_is_stable():
    """--help output should be consistent across runs."""
    results = []
    for _ in range(2):
        result = subprocess.run(
            ["bash", "scripts/bootstrap.sh", "--help"],
            capture_output=True, text=True, timeout=10
        )
        results.append(result.stdout)
    assert results[0] == results[1]

def test_bootstrap_does_not_delete_campy_dir():
    """Bootstrap should never contain rm -rf on .campy directory."""
    content = Path("scripts/bootstrap.sh").read_text()
    # Check that no line does rm -rf on the .campy directory
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            continue
        if "rm -rf" in line and (".campy" in line or "brain.db" in line):
            assert False, f"Dangerous delete: {line}"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_installer_idempotency.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_installer_idempotency.py
git commit -m "test(B237): add bootstrap idempotency tests"
```
