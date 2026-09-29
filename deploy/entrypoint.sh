#!/bin/sh
# B385: container entrypoint. Seeds $CAMPY_HOME/config.toml from the image's
# default on first start (an existing file on the volume -- e.g. one you put
# on EFS -- is never overwritten), then runs the daemon in the foreground.
# Environment overrides (CAMPY_SERVER_*, CAMPY_IAM_*, CAMPY_WEB_PORT) win
# over the file; see campy/brain/brainstem/config.py::ENV_OVERRIDES.
set -eu
: "${CAMPY_HOME:?CAMPY_HOME must be set}"
mkdir -p "$CAMPY_HOME" "$(dirname "${CAMPY_SOCKET_PATH:-/tmp/campy/brain.sock}")"
DEFAULT_CONFIG="${CAMPY_DEFAULT_CONFIG:-/app/deploy/campy.container.toml}"
if [ ! -f "$CAMPY_HOME/config.toml" ]; then
  cp "$DEFAULT_CONFIG" "$CAMPY_HOME/config.toml"
  echo "entrypoint: seeded $CAMPY_HOME/config.toml from the image default"
fi
# Fail fast rather than boot a daemon whose every LLM call will fail.
if [ -z "${CAMPY_LLM_MODEL:-}" ] && grep -q 'SET-CAMPY_LLM_MODEL' "$CAMPY_HOME/config.toml"; then
  echo "entrypoint: no LLM model configured -- set CAMPY_LLM_MODEL (or [llm].model in $CAMPY_HOME/config.toml)" >&2
  exit 64
fi
exec python -m campy.brain_daemon "$@"
