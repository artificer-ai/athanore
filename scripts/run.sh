#!/usr/bin/env bash
# Run the app.
#
#   ./scripts/run.sh                       # http://127.0.0.1:4002
#   ./scripts/run.sh --workers 4
#   ./scripts/run.sh examples/feature_build:wf
#
# Extra arguments go straight to `athanore serve` (11 §Server).
source "$(dirname "$0")/_lib.sh"

if ! in_container; then
  ensure_image
  compose_exec run --rm app "./scripts/run.sh $*"
fi

cd "$ROOT"
sync_python

host="${ATHANORE_HOST:-127.0.0.1}"
port="${ATHANORE_PORT:-4002}"

if have_py athanore.cli; then
  exec uv run --no-sync athanore serve --host "$host" --port "$port" "$@"
fi

# T003 creates the package and T028 the CLI. Until then there is nothing
# to serve, and saying so beats a stack trace.
note "no athanore.cli yet (arrives in T028) — running the placeholder"
exec uv run --no-sync python main.py
