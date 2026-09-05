#!/usr/bin/env bash
# Speak ACP with an agent inside the container. JSON-RPC on stdin/stdout:
# this script must never write to stdout.
#
#   ./scripts/agent.sh pi
#   ./scripts/agent.sh claude
#
# It is also the agent *command* to configure on an ACPAgent subclass, so
# a workflow running on the host dispatches into the container:
#
#   class Builder(ACPAgent):
#       command = ["./scripts/agent.sh", "pi"]
#
# When the workflow itself runs in the container (`./scripts/run.sh`),
# the same line spawns the adapter in-process instead of a sibling.
source "$(dirname "$0")/_lib.sh"

kind="${1:-pi}"; shift || true

case "$kind" in
  pi)     bin=pi-acp;           service=agent-pi ;;
  claude) bin=claude-agent-acp; service=agent-claude ;;
  *) die "usage: $0 <pi|claude> [args...]" ;;
esac

if in_container; then
  exec "$bin" "$@"
fi

ensure_image
# -T: no TTY on the JSON wire.
compose_exec run --rm -T "$service" "$@"
