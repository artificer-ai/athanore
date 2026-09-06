# T068 — Vitest suites and coverage

**Task.** `docs/v1/17-serial-task-plan.md` § `### T068`.
**Specs.** `docs/v1/13-testing.md` §Frontend.

## What this task is

Filling in the unit suites earlier SPA tasks left thin, and turning the
coverage gate on.

## What this task is not

- No production code changes. If a test cannot be written without
  changing a component, that is a finding — say so rather than
  reshaping the component to be testable in a way the design did not
  ask for.
- No E2E — T068a.

## Steps

Cover, at least:

1. every renderer kind (T062a, T063a–e);
2. `ActionForm` round-tripping **nested schemas and arrays** — arrays are
   where RJSF themes usually break;
3. the invalidation table's precedence and coalescing (T060);
4. the SSE wrapper's reconnect and `resync`;
5. keymap scoping (T067).

Then a `vitest --coverage` gate of ≥ 80 % on `web/src`, wired into CI.

## Verification

```sh
./scripts/dev.sh "pnpm -C web test --run"
./scripts/dev.sh "pnpm -C web test --run --coverage"
```

Read which files are under-covered rather than only the total: an 80 %
average with an untested realtime layer is worse than it looks.

## Done

- `pnpm test --run` green; the coverage gate enforced in CI.
- `**Status.** Done.` on `### T068`, in the same commit.

## Files

```
web/src/**/__tests__/**
web/vitest.config.ts
.github/workflows/ci.yml
docs/v1/17-serial-task-plan.md
```
