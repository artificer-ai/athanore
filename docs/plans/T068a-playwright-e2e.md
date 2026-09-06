# T068a — Playwright E2E and the a11y gate

**Task.** `docs/v1/17-serial-task-plan.md` § `### T068a`.
**Specs.** `docs/v1/13-testing.md` §E2E; `docs/v1/10-frontend.md`
§Accessibility.

## What this task is

The suite that drives the real app against a real server with a fake
agent — the only tests that prove the SPA, the API and the engine work
together.

## What this task is not

- No vendor agents. `ATHANORE_AGENT_COMMAND` points at `FakeACPAgent`;
  CI never talks to a model.
- No dev-stack work: `WITH_BROWSERS` already defaults to 1 and the image
  ships chromium (D68), because the driver's `qa` node needed it. The
  task's **Dev stack** step is already done — confirm it rather than
  redoing it.

## Steps

1. `web/e2e/` with a Playwright config starting `athanore serve` with
   `examples/msgtest` and a scenario workflow on `FakeACPAgent` — free
   port, tmp database, `ATHANORE_AGENT_COMMAND`.
2. Specs:
   - submit → the graph shows progress → allow a permission → answer a
     `human_input` → completed;
   - reorder via `position`;
   - pause and resume;
   - the server-down banner (kill the server, restart it, watch it
     recover);
   - shortcuts;
   - the inbox with no run selected;
   - a fan-out closed by a join rendering `k of n`.
3. `@axe-core/playwright` with an a11y score ≥ 95 on the dashboard.
4. The CI `web` job runs Playwright, Chromium only.

## Verification

```sh
./scripts/dev.sh "pnpm -C web exec playwright test"
```

The server-down spec is the flaky one if written carelessly: wait for
the banner's state, never a fixed sleep.

## Done

- The suite passes locally in the container; the CI `web` job runs it.
- `**Status.** Done.` on `### T068a`, in the same commit.

## Files

```
web/e2e/**
web/playwright.config.ts
.github/workflows/ci.yml
docs/v1/17-serial-task-plan.md
```
