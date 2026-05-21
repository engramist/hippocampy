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
