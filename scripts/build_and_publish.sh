#!/usr/bin/env bash
# Build the release artifacts and upload them to PyPI.
#
#   ./scripts/build_and_publish.sh pypi-AgEIcHl…      # the real thing
#   ./scripts/build_and_publish.sh --dry-run          # build and verify only
#   ./scripts/build_and_publish.sh --test pypi-…      # rehearse on TestPyPI
#   ./scripts/build_and_publish.sh --all-packages …   # + athanore-examples
#   UV_PUBLISH_TOKEN=pypi-… ./scripts/build_and_publish.sh --yes
#
# The token may be an argument or `UV_PUBLISH_TOKEN` in the environment;
# either way it reaches `uv publish` as that variable and never as an
# argv the process table can show. It is a secret, so it never goes in
# `.env` (AGENTS.md §Commands).
#
# What this does, in order: refuse a dirty checkout, build the SPA, empty
# `dist/`, then hand the build to `scripts/check_wheel.py` — which runs
# `uv build` itself and refuses to when the SPA is not built (D180), then
# installs the wheel into a clean venv and serves `/` out of it. Only a
# wheel that passed that is uploaded. `pnpm build` before `uv build` is
# the load-bearing order (D79): the SPA is git-ignored and reaches the
# wheel as a `[tool.hatch.build] artifacts` entry, so a wheel built over
# a stale `dist/` ships `assets/` with no `index.html`.
#
# By default only `athanore` is built and uploaded. `athanore-examples`
# is the same workspace and the same release (D191), but has never been
# on PyPI; `--all-packages` includes it.
#
# PyPI is a one-way door: a version, once uploaded, cannot be reused even
# after a delete. Hence the summary and the prompt. `--yes` skips it.
source "$(dirname "$0")/_lib.sh"

allow_dirty=0
dry_run=0
assume_yes=0
all_packages=0
test_index=0
token=""

for arg in "$@"; do
  case "$arg" in
    --allow-dirty)   allow_dirty=1 ;;
    --dry-run)       dry_run=1 ;;
    -y|--yes)        assume_yes=1 ;;
    --all-packages)  all_packages=1 ;;
    --test)          test_index=1 ;;
    -h|--help)       awk 'NR>1 && !/^#/ {exit} NR>1 {print substr($0, 3)}' "$0"
                     exit 0 ;;
    -*)              die "unknown flag: $arg (see --help)" ;;
    *)               if [ -n "$token" ]; then
                       die "more than one token given"
                     fi
                     token="$arg" ;;
  esac
done

# The token is moved out of the argument list here, on whichever side we
# are, so the command string handed to the container never carries it.
if [ -n "$token" ]; then
  export UV_PUBLISH_TOKEN="$token"
fi

flags=()
if [ "$allow_dirty"  = "1" ]; then flags+=(--allow-dirty);  fi
if [ "$dry_run"      = "1" ]; then flags+=(--dry-run);      fi
if [ "$assume_yes"   = "1" ]; then flags+=(--yes);          fi
if [ "$all_packages" = "1" ]; then flags+=(--all-packages); fi
if [ "$test_index"   = "1" ]; then flags+=(--test);         fi

if [ "$dry_run" = "0" ] && [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
  die "no token: pass it as an argument, set UV_PUBLISH_TOKEN, or --dry-run"
fi

# Same two-sided shape as the rest of scripts/: on the host this hands
# the work to the dev container, which is where the toolchain and the
# gate live. `-e UV_PUBLISH_TOKEN` forwards the value without naming it.
if ! in_container; then
  ensure_image
  compose_exec run --rm -e UV_PUBLISH_TOKEN dev \
    "./scripts/build_and_publish.sh ${flags[*]:-}"
fi

cd "$ROOT"

# A release must be a commit. `dist/` and the SPA's build output are
# git-ignored, so this stays true after the build below (D79).
if [ "$allow_dirty" = "0" ] && [ -n "$(git status --porcelain)" ]; then
  git status --short >&2
  die "the checkout is dirty: commit first, or pass --allow-dirty"
fi

version="$(uv run --no-sync python -c \
  'import tomllib,pathlib;print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
branch="$(git rev-parse --abbrev-ref HEAD)"
sha="$(git rev-parse --short HEAD)"

sync_python

printf '\n\033[1m── SPA\033[0m\n' >&2
pnpm -C web install --frozen-lockfile
pnpm -C web build

printf '\n\033[1m── dist\033[0m\n' >&2
rm -rf dist

# Builds the sdist and the wheel *from* it, checks the wheel carries the
# document and every asset it references, then pip-installs it into a
# fresh venv and serves it. This is the gate's `package` step (D180).
printf '\n\033[1m── package\033[0m\n' >&2
uv run --no-sync python scripts/check_wheel.py

if [ "$all_packages" = "1" ]; then
  printf '\n\033[1m── athanore-examples\033[0m\n' >&2
  uv build --all-packages
fi

publish=(uv publish)
index="PyPI"
if [ "$test_index" = "1" ]; then
  publish+=(--publish-url https://test.pypi.org/legacy/)
  index="TestPyPI"
fi

printf '\n\033[1m── publish\033[0m\n' >&2
note "version $version   branch $branch   $sha   → $index"
ls -1 dist >&2

if [ "$dry_run" = "1" ]; then
  note "--dry-run: built and verified, nothing uploaded"
  exit 0
fi

if [ "$assume_yes" = "0" ]; then
  printf 'upload the above to %s? this cannot be undone [y/N] ' "$index" >&2
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) die "aborted" ;;
  esac
fi

"${publish[@]}"
printf '\033[32mpublished %s to %s\033[0m\n' "$version" "$index" >&2
