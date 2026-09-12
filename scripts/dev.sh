#!/usr/bin/env bash
# Run a command in the dev container — the workhorse of the stack.
#
#   ./scripts/dev.sh "uv run pytest -q tests/test_settings.py"
#   ./scripts/dev.sh uv run ruff check .
#   ./scripts/dev.sh                       # interactive shell
#
# Inside the container it just runs the command, so an agent can call it
# without knowing where it is.
source "$(dirname "$0")/_lib.sh"

if in_container; then
  if [ $# -eq 0 ]; then exec bash -l; fi
  exec bash -lc "$*"
fi

ensure_image
flags=()
mapfile -t flags < <(tree_flags)
if [ $# -eq 0 ]; then
  compose_exec run --rm ${flags[@]+"${flags[@]}"} --entrypoint bash dev -l
fi
compose_exec run --rm ${flags[@]+"${flags[@]}"} dev "$*"
