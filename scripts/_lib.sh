# Shared helpers for scripts/. Sourced, never executed.
#
# Every script here runs in two places: on the host, where it hands the
# work to the dev stack, and inside the container, where it does the
# work. `ATHANORE_IN_CONTAINER=1` is baked into docker/dev/Dockerfile and
# is the only thing that tells them apart.
# shellcheck shell=bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

in_container() { [ "${ATHANORE_IN_CONTAINER:-0}" = "1" ]; }

die() { printf '%s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*" >&2; }

# `.env` holds only paths and ids, all derivable from the machine, so
# write it rather than making the first run a chore. Never secrets.
ensure_env() {
  local docker_gid
  if [ ! -f "$ROOT/.env" ]; then
    docker_gid="$(getent group docker | cut -d: -f3)"
    {
      echo "# Written by scripts/_lib.sh. See .env.example for every key."
      echo "WORKSPACE=$ROOT"
      echo "HOST_HOME=$HOME"
      echo "UID=$(id -u)"
      echo "GID=$(id -g)"
      echo "DOCKER_GID=${docker_gid:-999}"
    } > "$ROOT/.env"
    note "wrote $ROOT/.env"
  fi
  # Bind-mount sources have to exist, or docker creates them as
  # root-owned directories.
  mkdir -p "$HOME/.pi/agent/sessions"
  [ -e "$HOME/.gitconfig" ] || touch "$HOME/.gitconfig"
}

compose() {
  ensure_env
  command -v docker >/dev/null || die "docker is not installed"
  docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" "$@"
}

# Same, but replaces this shell, so signals reach docker directly — which
# matters for `run.sh` (Ctrl-C) and for `agent.sh` (the engine terminates
# the agent subprocess it spawned).
compose_exec() {
  ensure_env
  command -v docker >/dev/null || die "docker is not installed"
  exec docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" "$@"
}

# Build once, on demand. Rebuilding is `docker compose build`.
ensure_image() {
  docker image inspect athanore/dev:latest >/dev/null 2>&1 && return 0
  note "building athanore/dev (first run)"
  compose build dev
}

# Run one shell command in the dev container.
dev_run() {
  ensure_image
  compose run --rm dev "$*"
}

# Bring the project environment up to the lockfile. uv logs to stderr, so
# this is safe ahead of anything that owns stdout.
sync_python() {
  uv sync --all-groups --all-extras
}

have_py() {
  uv run --no-sync python -c \
    "import importlib.util as u, sys; sys.exit(0 if u.find_spec('$1') else 1)" \
    2>/dev/null
}
