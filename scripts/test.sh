#!/usr/bin/env bash
# Run the tests. From T005 this is a thin wrapper over the gate; until
# then it runs whatever of the gate is already configured and says which
# steps it skipped.
#
#   ./scripts/test.sh                      # everything
#   ./scripts/test.sh -k settings          # arguments go to pytest
source "$(dirname "$0")/_lib.sh"

if ! in_container; then
  ensure_image
  compose_exec run --rm dev "./scripts/test.sh $*"
fi

cd "$ROOT"

# T005 adds the real gate; once it exists it is the only definition of
# green, and this script stops having an opinion.
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
