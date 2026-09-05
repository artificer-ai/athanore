#!/usr/bin/env bash
# Rebuild the dev image (docker/dev/Dockerfile).
#
#   ./scripts/build.sh                # rebuild, reusing the layer cache
#   ./scripts/build.sh --pull         # refresh the node/uv base images too
#   ./scripts/build.sh --no-cache     # rebuild every layer from scratch
#   ./scripts/build.sh --reset        # drop the toolchain volumes first
#
# Bumping a pinned version in `.env` (PI_VERSION, CLAUDE_CODE_VERSION, …)
# changes a build arg, so a plain rebuild already picks it up.
#
# Unrecognised flags go straight to `docker compose build`.
source "$(dirname "$0")/_lib.sh"

in_container && die "build from the host: the image is what you are in"

reset=0
args=()
for arg in "$@"; do
  case "$arg" in
    --reset) reset=1 ;;
    *) args+=("$arg") ;;
  esac
done

# The venv, the uv cache, the pnpm store and the browsers are all
# reconstructible; `--reset` is the answer to "my environment is wedged".
# The Claude credentials and the Postgres data are NOT touched — losing
# those means re-authenticating and re-migrating, which is not a cache
# problem. Remove them by name if that is really what you want.
if [ "$reset" = "1" ]; then
  note "removing athanore-venv athanore-uv-cache athanore-pnpm-store athanore-ms-playwright"
  docker volume rm -f \
    athanore-venv \
    athanore-uv-cache \
    athanore-pnpm-store \
    athanore-ms-playwright >/dev/null
fi

ensure_env
compose_exec build "${args[@]}" dev
