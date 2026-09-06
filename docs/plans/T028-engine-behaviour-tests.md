# T028 — Port the engine behaviour tests

**Task.** `docs/v1/17-serial-task-plan.md` § `### T028`.
**Specs.** `docs/v1/13-testing.md` §Pyramid and §Fixtures.
**Reference.** v0's `test_deterministic.py`, `test_fanout.py`,
`test_priority.py`, `test_worker_pools.py`, `test_qa_gate.py` — the five
files this task covers, ledger rows ticked here.

## What this task is

The end-to-end engine suite, driven through a real `Engine` rather than
the stub the runner tests use. This is the task that proves the pieces
of Phase 1 compose.

## What this task is not

- No new engine behaviour. If a ported test fails, the engine is wrong
  or the test encoded a v0 quirk — decide which, and say so in the
  report rather than editing the assertion to match.
- No API-level assertions (T044a) and no agents (Phase 2).

## Steps

1. `tests/conftest.py`: an `engine` fixture — tmp SQLite, migrated,
   `Engine` started and stopped per test — and a
   `run_to_completion(run_id)` helper awaiting `run.completed` or
   `run.failed` on the bus. Awaiting the bus rather than polling is what
   keeps this suite fast and non-flaky.
2. `tests/engine/test_behaviours.py`, porting:
   - `test_deterministic.py`;
   - `test_fanout.py` — a run completes when the last branch lands;
     branches carry payloads;
   - `test_priority.py` — dispatch order observed through `task.started`
     order;
   - `test_worker_pools.py` — dedicated vs shared vs zero-capacity
     pools, and the registration errors;
   - `test_qa_gate.py` — the loop-back.
3. New cases: a loop-back payload dropped vs carried; `queued` visible
   before the first claim; a `feature_build`-shaped fan-out closed by a
   join.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/engine tests/store tests/graph"
./scripts/dev.sh "uv run pytest -q --cov=athanore/graph --cov=athanore/engine --cov-report=term-missing"
```

Coverage of `graph` and `engine` must be ≥ 95 %, enforced by
`--cov-fail-under` on those paths in CI — add that to the CI job, not
just to a local invocation.

## Done

- Suite passes; coverage gate green and wired into CI.
- The five ledger rows ticked.
- `**Status.** Done.` on `### T028`, in the same commit.

## Files

```
tests/conftest.py
tests/engine/test_behaviours.py
.github/workflows/ci.yml
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
