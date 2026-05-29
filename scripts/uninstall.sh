#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/campy" ]]; then
  exec "$ROOT_DIR/.venv/bin/campy" uninstall --force "$@"
fi

if command -v campy >/dev/null 2>&1; then
  exec campy uninstall --force "$@"
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  exec "$ROOT_DIR/.venv/bin/python" -m campy.cli.main uninstall --force "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m campy.cli.main uninstall --force "$@"
fi

echo "Unable to find a Campy executable or Python environment to run uninstall." >&2
exit 1