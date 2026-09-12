# Shared helpers for scripts/. Sourced, never executed.
#
# Every script here runs in two places: on the host, where it hands the
# work to the dev stack, and inside the container, where it does the
# work. `ATHANORE_IN_CONTAINER=1` is baked into docker/dev/Dockerfile and
# is the only thing that tells them apart.
# shellcheck shell=bash

set -euo pipefail

# Two directories, usually the same one. `ROOT` is the checkout that owns
# the dev stack: `.env`, the compose project, the named volumes. `TREE`
# is the tree the work happens in. They differ inside a git worktree
# (`git worktree add .worktrees/<name>`): a second tree of the same
# repository, on its own branch, that shares the main checkout's `.git`
# — and, through it, the stack. A worktree therefore never gets a second
# `.env` or a second compose project; it gets its own working directory
# in the container (the checkout is mounted at its own path, so a path
# under it is the same path on both sides) and its own uv environment,
# so two trees can run the gate at once without rewriting each other's
# venv. `TREE` is the tree the caller is standing in when that is a
# worktree of this repository, else the tree these scripts live in.
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_common_dir() { git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true; }
_common="$(_common_dir "$SCRIPT_ROOT")"
ROOT="${_common:+$(dirname "$_common")}"
ROOT="${ROOT:-$SCRIPT_ROOT}"
TREE="$SCRIPT_ROOT"
if _top="$(git rev-parse --show-toplevel 2>/dev/null)" \
   && [ -n "$_common" ] && [ "$(_common_dir "$_top")" = "$_common" ]; then
  TREE="$_top"
fi
unset _common _top

in_container() { [ "${ATHANORE_IN_CONTAINER:-0}" = "1" ]; }

# `docker compose run` flags that put the work in `$TREE`: the working
# directory, and a uv environment of the worktree's own under the
# `athanore-venvs` volume. Empty in the main checkout, whose environment
# is `/home/agent/venv` as the image says. Read with `mapfile -t`.
tree_flags() {
  [ "$TREE" = "$ROOT" ] && return 0
  printf -- '-w\n%s\n-e\nUV_PROJECT_ENVIRONMENT=/home/agent/venvs/%s\n' \
    "$TREE" "$(basename "$TREE")"
}

die() { printf '%s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*" >&2; }

# Append a key only when it is missing, so a hand-edited `.env` survives
# and a new key does not need a wipe.
_env_default() {
  grep -q "^$1=" "$ROOT/.env" 2>/dev/null && return 0
  printf '%s=%s\n' "$1" "$2" >> "$ROOT/.env"
}

# `.env` holds only paths and ids, all derivable from the machine, so
# write it rather than making the first run a chore. Never secrets.
ensure_env() {
  local docker_gid
  if [ ! -f "$ROOT/.env" ]; then
    echo "# Written by scripts/_lib.sh. See .env.example for every key." \
      > "$ROOT/.env"
    note "wrote $ROOT/.env"
  fi
  # No docker group at all on rootless Docker, Docker Desktop, or inside
  # a container. `getent` exits 2 there, which pipefail would make fatal.
  docker_gid="$(getent group docker 2>/dev/null | cut -d: -f3 || true)"
  _env_default WORKSPACE "$ROOT"
  _env_default HOST_HOME "$HOME"
  _env_default UID "$(id -u)"
  _env_default GID "$(id -g)"
  _env_default DOCKER_GID "${docker_gid:-999}"
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

# Run one shell command in the dev container, in `$TREE`.
dev_run() {
  local flags=()
  mapfile -t flags < <(tree_flags)
  ensure_image
  compose run --rm ${flags[@]+"${flags[@]}"} dev "$*"
}

# Bring the project environment up to the lockfile. uv logs to stderr, so
# this is safe ahead of anything that owns stdout.
sync_python() {
  uv sync --all-packages --all-groups --all-extras
}
