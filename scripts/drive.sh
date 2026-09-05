#!/usr/bin/env bash
# Drive the v1 plan with athanore v0.
#
#   ./scripts/drive.sh up                    # start the orchestrator + TUI
#   ./scripts/drive.sh submit --dry-run      # list what would be queued
#   ./scripts/drive.sh submit --only T003
#   ./scripts/drive.sh submit --from T003 --to T010
#   ./scripts/drive.sh logs                  # follow it
#   ./scripts/drive.sh down
#
# v0 runs in its own container and its own venv — it is the same
# distribution name as v1 and the two must never meet in one environment
# (D67). It dispatches each task to `athanore/dev` over ACP, runs the
# gate in the same image, and shows progress in the v0 browser TUI.
source "$(dirname "$0")/_lib.sh"

in_container && die "drive from the host: the orchestrator spawns sibling containers"

cmd="${1:-up}"; shift || true

case "$cmd" in
  up)
    ensure_env
    # The sandbox image is what the agents actually run in.
    ensure_image
    compose --profile drive up -d --build orchestrator
    port="$(grep -m1 '^BUILDER_WEB_PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2)"
    note "TUI: http://127.0.0.1:${port:-2424}   API: http://127.0.0.1:${BUILDER_PORT:-4102}"
    ;;
  down)  compose --profile drive down ;;
  logs)  compose_exec --profile drive logs -f orchestrator ;;
  submit)
    compose_exec --profile drive exec orchestrator bash -lc \
      "cd \"\$WORKSPACE/driver\" && uv run python -m athanore_build.submit_plan $*"
    ;;
  *) die "usage: $0 <up|down|logs|submit> [args...]" ;;
esac
