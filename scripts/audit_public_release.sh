#!/usr/bin/env bash
set -euo pipefail

# Campy Public Release Audit Script
# Scans repository and distribution artifacts for private data, secrets, and unintended content
# Usage: bash scripts/audit_public_release.sh [--release]

RELEASE_MODE="${1:-}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Campy Public Release Audit ==="
echo "Repository: $REPO_ROOT"
echo "Release Mode: $RELEASE_MODE"
echo ""

# Define high-risk patterns
BLOCKED_PATTERNS=(
    "sk-[A-Za-z0-9]{20,}"  # OpenAI API keys
    "OPENAI_API_KEY"
    "ANTHROPIC_API_KEY"
    "GOOGLE_API_KEY"
    "BEGIN RSA PRIVATE KEY"
    "BEGIN PRIVATE KEY"
    "/Users/djshelton"
    "Desktop/GitProjects"
    "/Users/.*@"  # Personal email paths
)

HIGH_RISK_PATTERNS=(
    "brain\.db"
    "brain\.sock"
    "submission_results"
    "agent_execution_trace"
    "master_timeline\.json"
)

echo "Step 1: Scanning git-tracked files for high-risk patterns..."
echo ""

# Scan tracked files plus untracked, non-ignored release candidates. This catches
# newly-created files before they are committed.
TRACKED_FILES=$(git -C "$REPO_ROOT" ls-files --cached --others --exclude-standard 2>/dev/null || echo "")

FINDINGS_BLOCKED=0
FINDINGS_HIGH_RISK=0

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    echo -n "Checking for: $pattern ... "
    if echo "$TRACKED_FILES" | xargs -I {} grep -r "$pattern" "$REPO_ROOT/{}" 2>/dev/null | grep -v "docs/public-release-audit.md" | grep -v "scripts/audit_public_release.sh" > /dev/null 2>&1; then
        count=$(echo "$TRACKED_FILES" | xargs -I {} grep -r "$pattern" "$REPO_ROOT/{}" 2>/dev/null | grep -v "docs/public-release-audit.md" | grep -v "scripts/audit_public_release.sh" | wc -l)
        echo "FOUND ($count instances)"
        FINDINGS_BLOCKED=$((FINDINGS_BLOCKED + 1))
    else
        echo "ok"
    fi
done

echo ""
echo "Step 2: Scanning for high-risk artifacts..."
echo ""

for pattern in "${HIGH_RISK_PATTERNS[@]}"; do
    echo -n "Checking for: $pattern ... "
    if echo "$TRACKED_FILES" | xargs -I {} grep -r "$pattern" "$REPO_ROOT/{}" 2>/dev/null | grep -v "docs/public-release-audit.md" > /dev/null 2>&1; then
        count=$(echo "$TRACKED_FILES" | xargs -I {} grep -r "$pattern" "$REPO_ROOT/{}" 2>/dev/null | grep -v "docs/public-release-audit.md" | wc -l)
        echo "FOUND ($count instances)"
        FINDINGS_HIGH_RISK=$((FINDINGS_HIGH_RISK + 1))
    else
        echo "ok"
    fi
done

echo ""
echo "Step 3: Checking for generated artifacts..."
echo ""

GENERATED_ARTIFACTS=(
    ".campy"
    ".sidequests"
    "brain.db"
    "brain.sock"
    "*.sock"
    "*.log"
)

for artifact in "${GENERATED_ARTIFACTS[@]}"; do
    if find "$REPO_ROOT" -name "$artifact" -type f 2>/dev/null | grep -v ".git" | head -1 > /dev/null; then
        echo "WARNING: Generated artifact found: $artifact"
    fi
done

echo ""
echo "Step 4: Checking distribution artifacts (if present)..."
echo ""

if [ -d "$REPO_ROOT/dist" ]; then
    echo "Found dist/ directory. Checking wheel and sdist contents..."
    
    for whl in "$REPO_ROOT"/dist/*.whl; do
        if [ -f "$whl" ]; then
            echo "Checking wheel: $(basename "$whl")"
            # Check if sensitive paths are in wheel
            if python3 -c "import zipfile; z=zipfile.ZipFile('$whl'); names='\\n'.join(z.namelist()); print('FOUND' if any(s in names for s in ['.campy', '.sidequests', 'brain.db', 'submission_results', 'agent_execution_trace', 'master_timeline']) else 'ok')" 2>/dev/null | grep -q "FOUND"; then
                echo "WARNING: Potentially sensitive content in wheel"
                FINDINGS_BLOCKED=$((FINDINGS_BLOCKED + 1))
            else
                echo "  ok Wheel content clean"
            fi
        fi
    done
    
    for sdist in "$REPO_ROOT"/dist/*.tar.gz; do
        if [ -f "$sdist" ]; then
            echo "Checking sdist: $(basename "$sdist")"
            if python3 -c "import tarfile; t=tarfile.open('$sdist'); names='\\n'.join(t.getnames()); print('FOUND' if any(s in names for s in ['.campy', '.sidequests', 'brain.db', 'submission_results', 'agent_execution_trace', 'master_timeline']) else 'ok')" 2>/dev/null | grep -q "FOUND"; then
                echo "WARNING: Potentially sensitive content in sdist"
                FINDINGS_BLOCKED=$((FINDINGS_BLOCKED + 1))
            else
                echo "  ok Sdist content clean"
            fi
        fi
    done
else
    echo "dist/ directory not found. Run: python -m build --wheel --sdist"
    if [ "$RELEASE_MODE" == "--release" ]; then
        echo "ERROR: Release mode requires dist artifacts to be present"
        exit 1
    fi
fi

echo ""
echo "========== AUDIT SUMMARY =========="
echo "Blocked patterns found: $FINDINGS_BLOCKED"
echo "High-risk artifacts: $FINDINGS_HIGH_RISK"
echo ""

if [ $FINDINGS_BLOCKED -gt 0 ]; then
    echo "ERROR: AUDIT FAILED: Blocked patterns detected"
    if [ "$RELEASE_MODE" == "--release" ]; then
        exit 1
    else
        echo "Note: Run with --release to enforce strict mode"
        exit 0
    fi
elif [ $FINDINGS_HIGH_RISK -gt 0 ]; then
    echo "WARNING:  AUDIT WARNING: High-risk artifacts detected"
    echo "Review findings above and update docs/public-release-audit.md with decisions"
    exit 0
else
    echo "OK: AUDIT PASSED: No high-risk patterns detected"
    exit 0
fi
