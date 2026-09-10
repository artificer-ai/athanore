#!/usr/bin/env bash
# Serve or build the documentation site (`docs/site/`, D214).
#
#   ./scripts/docs.sh                      # http://127.0.0.1:8000, live reload
#   ./scripts/docs.sh build                # build into docs/site/build
#   ./scripts/docs.sh serve -a 127.0.0.1:9000
#
# Every service uses host networking, so the served site is reachable at
# `127.0.0.1:8000` from the host whichever side this is run from — which
# is why the docs site has no compose service of its own.
#
# Extra arguments go straight to mkdocs, after the ones set here, so a
# second `-a` moves the bind. `build` is the gate's build, `--strict` and
# all, so what passes here passes there.
source "$(dirname "$0")/_lib.sh"

if ! in_container; then
  ensure_image
  compose_exec run --rm dev "./scripts/docs.sh $*"
fi

cd "$ROOT"

config=docs/site/mkdocs.yml
[ -f "$config" ] || die "no docs site here: $config is missing"

verb="${1:-serve}"
[ $# -gt 0 ] && shift

case "$verb" in
  serve)
    sync_python
    exec uv run --no-sync mkdocs serve -f "$config" -a 127.0.0.1:8000 "$@"
    ;;
  build)
    sync_python
    exec uv run --no-sync mkdocs build --strict -f "$config" "$@"
    ;;
  *)
    die "usage: $0 [serve|build] [mkdocs args...]"
    ;;
esac
