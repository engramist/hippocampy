# B236 - Public PyPI and pipx Install Path

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pip install hippocampy` (or `pipx install hippocampy`) work from a built wheel, with a release build script and publish checklist. This is the foundation for the one-line bootstrap (B237).

**Architecture:** Finalize `pyproject.toml` metadata, create `scripts/release_build.sh` that audits + builds + checks artifacts, add a publish checklist doc, extend installed-mode tests. Do NOT publish to real PyPI — validate against TestPyPI or local wheel install only.

**Tech Stack:** Python packaging (setuptools, build, twine), Bash, pytest

**Key existing files:**
- `pyproject.toml` — already has package metadata, needs version/classifier/data cleanup
- `scripts/audit_public_release.sh` — already exists, scans for secrets/private data
- `tests/test_packaging_installed_mode.py` — already exists with venv wheel-install tests
- `tests/test_public_release_manifest.py` — already exists with wheel content checks

---

### Task 1: Finalize pyproject.toml Metadata

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read the current pyproject.toml**

Read `pyproject.toml` to understand current state.

- [ ] **Step 2: Update version and metadata**

Apply these changes to `pyproject.toml`:

```toml
[project]
name = "hippocampy"
version = "0.1.0"
description = "Local AI memory system with gated consolidation loop and graph-native Kùzu database"
readme = "README.md"
license = "Apache-2.0"
authors = [{ name = "HippoCampy", email = "hello@hippocampy.dev" }]
keywords = ["ai", "memory", "graph-database", "mcp", "knowledge-graph", "kuzu"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

requires-python = ">=3.12,<3.15"
```

Key changes:
- Remove `-rc1` from version (release candidates go in the version field only when publishing RCs)
- Add `License` classifier
- Add `Topic` classifier
- Widen Python range to include 3.14 (current system Python)

- [ ] **Step 3: Verify package-data includes plugin skills and campy-memory**

Ensure `[tool.setuptools.package-data]` covers all needed files:

```toml
[tool.setuptools.package-data]
"campy.data" = ["**/*.md", "**/*.py", "**/*.toml"]
"*" = ["campy.toml", "sidequests.toml"]
```

- [ ] **Step 4: Add MANIFEST.in to exclude unwanted files from sdist**

Create `MANIFEST.in`:

```
include LICENSE
include README.md
include pyproject.toml
recursive-include campy *.py *.md *.toml
recursive-include mcp_engine *.py
recursive-include adapters *.py *.sh *.md
recursive-include web *.py *.html *.css *.js
recursive-include plugin *.md *.json
prune backlog
prune InvertorsDocs
prune tests
prune scripts
prune .github
prune ARC*
global-exclude *.pyc
global-exclude __pycache__
global-exclude *.db
global-exclude *.sock
global-exclude *.log
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml MANIFEST.in
git commit -m "feat(B236): finalize package metadata and add MANIFEST.in"
```

---

### Task 2: Create Release Build Script

**Files:**
- Create: `scripts/release_build.sh`
- Test: `tests/test_release_build.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_release_build.py
"""Test the release build script exists and is well-formed."""
from pathlib import Path
import subprocess

def test_release_build_script_exists():
    """Release build script should exist."""
    script = Path("scripts/release_build.sh")
    assert script.exists()

def test_release_build_script_syntax():
    """Script should pass bash -n syntax check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/release_build.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"

def test_release_build_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/release_build.sh").read_text()
    assert "set -euo pipefail" in content

def test_release_build_script_runs_audit():
    """Script should call audit_public_release.sh before building."""
    content = Path("scripts/release_build.sh").read_text()
    assert "audit_public_release" in content

def test_release_build_script_runs_twine_check():
    """Script should run twine check on built artifacts."""
    content = Path("scripts/release_build.sh").read_text()
    assert "twine check" in content

def test_release_build_script_requires_publish_flag():
    """Script should never upload to PyPI without explicit --publish flag."""
    content = Path("scripts/release_build.sh").read_text()
    assert "--publish" in content
    # Should NOT have unconditional twine upload
    lines = content.split("\n")
    for line in lines:
        if "twine upload" in line and "--publish" not in line and "testpypi" not in line.lower():
            # Only OK if it's behind a conditional
            assert False, f"Unconditional twine upload found: {line}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_release_build.py -v`
Expected: FAIL — script doesn't exist

- [ ] **Step 3: Create the release build script**

Create `scripts/release_build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Campy Release Build Script
# Usage:
#   bash scripts/release_build.sh              # Build only (no upload)
#   bash scripts/release_build.sh --testpypi   # Build + upload to TestPyPI
#   bash scripts/release_build.sh --publish    # Build + upload to real PyPI (with confirmation)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ACTION="${1:-build}"

echo "=== Campy Release Build ==="
echo "Repository: $REPO_ROOT"
echo "Action: $ACTION"
echo ""

# Step 1: Clean previous artifacts
echo "Step 1: Cleaning previous build artifacts..."
rm -rf dist build *.egg-info
echo "  ✓ Clean"

# Step 2: Run public release audit
echo ""
echo "Step 2: Running public release audit..."
bash scripts/audit_public_release.sh --release
echo "  ✓ Audit passed"

# Step 3: Build wheel and sdist
echo ""
echo "Step 3: Building wheel and sdist..."
python3 -m build --wheel --sdist
echo "  ✓ Built: $(ls dist/)"

# Step 4: Run twine check
echo ""
echo "Step 4: Running twine check..."
python3 -m twine check dist/*
echo "  ✓ Twine check passed"

# Step 5: Run packaging tests
echo ""
echo "Step 5: Running packaging tests..."
python3 -m pytest tests/test_public_release_manifest.py -q 2>/dev/null || {
    echo "  ⚠ Some packaging tests failed — review before publishing"
}

# Step 6: Upload (only if flag provided)
echo ""
if [ "$ACTION" = "--testpypi" ]; then
    echo "Step 6: Uploading to TestPyPI..."
    python3 -m twine upload --repository testpypi dist/*
    echo "  ✓ Uploaded to TestPyPI"
    echo ""
    echo "Test install with:"
    echo "  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ hippocampy"
elif [ "$ACTION" = "--publish" ]; then
    echo "Step 6: Publishing to PyPI..."
    echo ""
    echo "  ⚠  WARNING: This publishes to the REAL PyPI."
    echo "  ⚠  PyPI releases CANNOT be overwritten — only new versions."
    echo ""
    read -p "  Type 'publish' to confirm: " CONFIRM
    if [ "$CONFIRM" = "publish" ]; then
        python3 -m twine upload dist/*
        echo "  ✓ Published to PyPI"
    else
        echo "  ✗ Cancelled"
        exit 1
    fi
else
    echo "Step 6: Build complete (no upload)."
    echo ""
    echo "Artifacts in dist/:"
    ls -la dist/
    echo ""
    echo "To upload:"
    echo "  bash scripts/release_build.sh --testpypi   # TestPyPI"
    echo "  bash scripts/release_build.sh --publish    # Real PyPI"
fi

echo ""
echo "=== Done ==="
```

- [ ] **Step 4: Make executable and run tests**

```bash
chmod +x scripts/release_build.sh
pytest tests/test_release_build.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/release_build.sh tests/test_release_build.py
git commit -m "feat(B236): add release build script with audit + twine check"
```

---

### Task 3: Create Publish Checklist

**Files:**
- Create: `docs/release-publish-checklist.md`

- [ ] **Step 1: Write the checklist**

Create `docs/release-publish-checklist.md`:

```markdown
# Campy Release Publish Checklist

## Pre-Release

- [ ] Version bumped in `pyproject.toml` (no `-rc` suffix for release)
- [ ] CHANGELOG updated (if maintained)
- [ ] All tests pass: `pytest tests/ -q`
- [ ] Public release audit passes: `bash scripts/audit_public_release.sh --release`
- [ ] No private data in wheel: `pytest tests/test_public_release_manifest.py -v`

## Build

```bash
bash scripts/release_build.sh
```

This cleans `dist/`, runs the audit, builds wheel+sdist, and runs `twine check`.

## TestPyPI Dry Run

```bash
bash scripts/release_build.sh --testpypi
```

Then test install from TestPyPI:

```bash
python -m venv /tmp/campy-test
/tmp/campy-test/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ hippocampy
/tmp/campy-test/bin/campy --help
/tmp/campy-test/bin/campy doctor --help
```

## Publish to PyPI

```bash
bash scripts/release_build.sh --publish
```

Requires typing "publish" to confirm. **PyPI releases cannot be overwritten** — if something is wrong, publish a new version.

## Post-Publish Verification

```bash
pip install hippocampy
campy --help
campy doctor
```

## Rollback

PyPI does not allow overwriting files. If a bad release is published:
1. Yank the release: `pip install twine && twine yank hippocampy==X.Y.Z`
2. Publish a fixed version with incremented patch number
3. Yanked versions still install with `pip install hippocampy==X.Y.Z` but won't be the default

## Patent-Pending Notice

Ensure `README.md` and package description include patent-pending notice per B233 guidelines.
```

- [ ] **Step 2: Commit**

```bash
git add docs/release-publish-checklist.md
git commit -m "docs(B236): add release publish checklist"
```

---

### Task 4: Extend Installed-Mode Tests

**Files:**
- Modify: `tests/test_packaging_installed_mode.py`

- [ ] **Step 1: Read current test file**

Read `tests/test_packaging_installed_mode.py` fully to understand existing tests.

- [ ] **Step 2: Add new installed-mode CLI tests**

Add these tests to `tests/test_packaging_installed_mode.py` (after existing tests):

```python
class TestInstalledCLICommands:
    """Test CLI commands work from installed package."""

    def test_campy_help(self, temp_venv, wheel_path):
        """campy --help should work from installed wheel."""
        pip = temp_venv / "bin" / "pip"
        campy = temp_venv / "bin" / "campy"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run([str(campy), "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "Usage" in result.stdout or "usage" in result.stdout

    def test_campy_doctor_help(self, temp_venv, wheel_path):
        """campy doctor --help should work from installed wheel."""
        pip = temp_venv / "bin" / "pip"
        campy = temp_venv / "bin" / "campy"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run([str(campy), "doctor", "--help"], capture_output=True, text=True)
        assert result.returncode == 0

    def test_campy_install_help(self, temp_venv, wheel_path):
        """campy install --help should work from installed wheel."""
        pip = temp_venv / "bin" / "pip"
        campy = temp_venv / "bin" / "campy"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run([str(campy), "install", "--help"], capture_output=True, text=True)
        assert result.returncode == 0

    def test_campy_recall_help(self, temp_venv, wheel_path):
        """campy recall --help should work from installed wheel."""
        pip = temp_venv / "bin" / "pip"
        campy = temp_venv / "bin" / "campy"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run([str(campy), "recall", "--help"], capture_output=True, text=True)
        assert result.returncode == 0

    def test_campy_activity_help(self, temp_venv, wheel_path):
        """campy activity --help should work from installed wheel."""
        pip = temp_venv / "bin" / "pip"
        campy = temp_venv / "bin" / "campy"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run([str(campy), "activity", "--help"], capture_output=True, text=True)
        assert result.returncode == 0


class TestPackageDataAccess:
    """Test that package data is accessible from installed package."""

    def test_memory_skill_accessible(self, temp_venv, wheel_path):
        """campy-memory skill should be accessible from installed package."""
        pip = temp_venv / "bin" / "pip"
        python = temp_venv / "bin" / "python"
        subprocess.run([str(pip), "install", str(wheel_path)], check=True, capture_output=True)
        result = subprocess.run(
            [str(python), "-c", "from importlib import resources; print(resources.files('campy.data').joinpath('campy-memory', 'SKILL.md').read_text()[:50])"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) > 0
```

- [ ] **Step 3: Run tests (requires wheel in dist/)**

```bash
python3 -m build --wheel --sdist
pytest tests/test_packaging_installed_mode.py -v
```
Expected: PASS (or SKIP if wheel missing)

- [ ] **Step 4: Commit**

```bash
git add tests/test_packaging_installed_mode.py
git commit -m "test(B236): extend installed-mode tests for all CLI commands"
```

---

### Task 5: Local Wheel Install Validation

- [ ] **Step 1: Build the wheel**

```bash
rm -rf dist build *.egg-info
python3 -m build --wheel --sdist
```

- [ ] **Step 2: Run twine check**

```bash
python3 -m twine check dist/*
```
Expected: PASSED

- [ ] **Step 3: Test wheel install in fresh venv**

```bash
python3 -m venv /tmp/campy-wheel-test
/tmp/campy-wheel-test/bin/python -m pip install -U pip
/tmp/campy-wheel-test/bin/python -m pip install dist/hippocampy-*.whl
/tmp/campy-wheel-test/bin/campy --help
/tmp/campy-wheel-test/bin/campy doctor --help
rm -rf /tmp/campy-wheel-test
```
Expected: All commands output help text without errors

- [ ] **Step 4: Test pipx install (if available)**

```bash
if command -v pipx &>/dev/null; then
    pipx install dist/hippocampy-*.whl --force
    campy --help
    pipx uninstall hippocampy
fi
```
Expected: PASS or skip if pipx not available

- [ ] **Step 5: Run full packaging test suite**

```bash
pytest tests/test_public_release_manifest.py tests/test_packaging_installed_mode.py tests/test_release_build.py -v
```
Expected: PASS

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(B236): complete — package install path validated"
```
