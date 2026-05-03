#!/usr/bin/env bash
set -euo pipefail

DEFAULT_DB="${HOME}/.sidequests/brain.db"

usage() {
  cat <<'EOF'
Usage:
  bash tools/graph_viewer/open_kuzu_explorer.sh [path/to/sidequests.db]

Defaults to ~/.sidequests/brain.db.

The script copies the selected database into a temporary snapshot directory and launches archived
Kuzu Explorer in read-only mode at http://localhost:8000.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but was not found on PATH." >&2
  exit 1
fi

DB_PATH="${1:-$DEFAULT_DB}"
if [[ ! -f "$DB_PATH" ]]; then
  echo "Database file not found: $DB_PATH" >&2
  echo "Pass the absolute path to a SideQuests .db file, or create ~/.sidequests/brain.db." >&2
  exit 1
fi

DB_FILE="$(basename "$DB_PATH")"
SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidequests-kuzu-explorer.XXXXXX")"

cleanup() {
  rm -rf "$SNAPSHOT_DIR"
}
trap cleanup EXIT INT TERM

cp "$DB_PATH" "$SNAPSHOT_DIR/$DB_FILE"

echo "Launching archived Kuzu Explorer in read-only mode."
echo "Database source: $DB_PATH"
echo "Snapshot mount:  $SNAPSHOT_DIR"
echo "UI:             http://localhost:8000"
echo

exec docker run -p 8000:8000 \
  -v "$SNAPSHOT_DIR:/database" \
  -e KUZU_FILE="$DB_FILE" \
  -e MODE=READ_ONLY \
  --rm kuzudb/explorer:latest
