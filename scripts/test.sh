#!/usr/bin/env bash
# Run the gate. This script is the definition of green (D74): it runs
# each step whose config exists and names the ones it skipped.
#
#   ./scripts/test.sh                      # everything
#   ./scripts/test.sh -k settings          # arguments go to pytest
source "$(dirname "$0")/_lib.sh"

if ! in_container; then
  ensure_image
  compose_exec run --rm dev "./scripts/test.sh $*"
fi

cd "$ROOT"

# A local `scripts/gate.sh` wins if you drop one in; the plan does not
# create one (D74).
if [ -x ./scripts/gate.sh ] && [ $# -eq 0 ]; then
  exec ./scripts/gate.sh
fi

failed=()
skipped=()

step() {  # step <name> <configured?> <command...>
  local name="$1" configured="$2"; shift 2
  if [ "$configured" != "yes" ]; then skipped+=("$name"); return 0; fi
  printf '\n\033[1m── %s\033[0m\n' "$name" >&2
  "$@" || failed+=("$name")
}

configured() {  # configured <toml-table>
  grep -q "^\[$1\]" pyproject.toml 2>/dev/null && echo yes || echo no
}

# Is there a browser for the Playwright suite to drive? The dev image
# ships one (WITH_BROWSERS=1, D68) and CI installs one, so this is `yes`
# wherever the gate is meant to run; a checkout with neither skips the
# step by name rather than spending a download on it mid-gate.
browsers() {
  local at="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
  compgen -G "$at/chromium*" >/dev/null 2>&1 && echo yes || echo no
}

sync_python

step pytest        "$([ -d tests ] && echo yes || echo no)" \
  uv run --no-sync pytest -q "$@"
step ruff          "$(configured tool.ruff)" \
  bash -c 'uv run --no-sync ruff check . && uv run --no-sync ruff format --check .'
step pyright       "$(configured tool.pyright)" \
  uv run --no-sync pyright
step lint-imports  "$(configured tool.importlinter)" \
  uv run --no-sync lint-imports

if [ -f web/package.json ]; then
  pnpm -C web install --frozen-lockfile
  step "web typecheck" yes pnpm -C web typecheck
  step "web lint"      yes pnpm -C web lint
  step "web test"      yes pnpm -C web test
  step "web build"     yes pnpm -C web build
  # The E2E suite drives the SPA the step above just built, served by a
  # real `athanore serve` with FakeACPAgent behind every agent (T068a),
  # so it comes last and after the build that produced its subject.
  step "web e2e"       "$(browsers)" pnpm -C web exec playwright test
  # The Phase 4 checkpoint (T069): `uv build`, then the wheel's contents,
  # then a clean `pip install` of it serving `/` out of a temporary
  # directory. It runs here and not only on a runner for D178's reason —
  # this repository has no runner, so a check only `.github/workflows/
  # ci.yml` performs is a check that never runs. It needs the build
  # above, which is why it is after it.
  step "package"       yes uv run --no-sync python scripts/check_wheel.py
else
  skipped+=("web (no web/ yet — T007)")
fi

echo >&2
if [ ${#skipped[@]} -gt 0 ]; then note "skipped: ${skipped[*]}"; fi
if [ ${#failed[@]} -gt 0 ]; then
  printf '\033[31mFAILED: %s\033[0m\n' "${failed[*]}" >&2
  exit 1
fi
printf '\033[32mgreen\033[0m\n' >&2
