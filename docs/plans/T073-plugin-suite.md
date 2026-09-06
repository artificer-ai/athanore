# T073 — Plugin test workflow and the plugin suite

**Task.** `docs/v1/17-serial-task-plan.md` § `### T073`.
**Specs.** `docs/v1/09-plugins.md` (the whole document — this suite is
its acceptance test).

## What this task is

One fixture workflow that uses **every** declaration the plugin system
offers, and the suite that exercises it. If a declaration cannot be
expressed here, the vocabulary has a hole.

## What this task is not

- No production code. If the suite finds a gap, report it — the fix
  belongs to T049/T049a/T070/T071.
- Not a toy: the fixture is the reference example a plugin author reads.

## Steps

1. `tests/plugins/fixture_wf.py`: one `route`, one `action` with a
   **nested** model, one panel of every kind, a `node`-slot panel, an
   `on` handler, and an `assets` directory with one `.js`.
2. `tests/plugins/test_suite.py`:
   - the manifest is complete;
   - the route and the action 404 on a foreign run;
   - node liveness flips with task state (the node-slot panel appears
     and disappears);
   - `on` fires **after commit**;
   - the asset is served with the CSP header.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/plugins --cov=athanore/plugins --cov-report=term-missing"
```

Coverage of `athanore/plugins` ≥ 90 %; read which branches are missed.

## Done

- Tests pass; plugin coverage ≥ 90 %.
- `**Status.** Done.` on `### T073`, in the same commit.

## Files

```
tests/plugins/fixture_wf.py
tests/plugins/assets/*.js
tests/plugins/test_suite.py
docs/v1/17-serial-task-plan.md
```
