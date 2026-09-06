# T075 — Port `gamedev`, `msgtest`, `projects`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T075`.
**Specs.** `docs/v1/09-plugins.md` §Declarations (the showcase gamedev
implements).
**Reference.** v0's `workflow/` and `tests/test_gamedev.py`.

## What this task is

Three more examples, one of which doubles as the plugin system's
showcase — the worked example a plugin author copies.

## What this task is not

- No new plugin capability. If the showcase needs something T049–T071
  did not build, that is a finding.
- `msgtest` stays small: it is what the E2E suite and the smoke tests
  drive.

## Steps

1. `gamedev`, `msgtest`, `projects`, written fresh as in T074.
2. `gamedev` additionally declares the plugin panel and action from
   09 §Declarations: the `/words` route, the `override` action, and the
   `Words` table pane.
3. `tests/test_gamedev.py` becomes `examples/tests/test_gamedev.py`.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q examples"
ATHANORE_AGENT_COMMAND=<fake> ./scripts/dev.sh "uv run python -m examples"   # then submit gamedev
```

Run `gamedev` on `FakeACPAgent` and open its `Words` pane — a showcase
nobody has looked at is not a showcase.

## Done

- `examples/tests` green; ledger row for `test_gamedev.py` ticked.
- `**Status.** Done.` on `### T075`, in the same commit.

## Files

```
examples/{gamedev,msgtest,projects}/**
examples/tests/test_gamedev.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
