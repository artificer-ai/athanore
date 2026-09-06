# T077 — Live smoke scripts

**Task.** `docs/v1/17-serial-task-plan.md` § `### T077`.
**Specs.** `docs/v1/13-testing.md` §Live smoke (document the procedure
there).

## What this task is

Two tests that talk to real agents, gated off by default — the only
place in the suite where a model is actually called.

## What this task is not

- **Never in CI.** `FakeACPAgent` is the only agent CI runs
  (`AGENTS.md` §Stack). These are skipped unless `ATHANORE_SMOKE=1`.
- No assertions on model output. The assertion is that a **stats line
  with real token counts** exists — that is what a live run proves and
  a fake cannot.

## Steps

1. `tests/smoke/test_pi.py` and `tests/smoke/test_claude.py`, each
   gated on `ATHANORE_SMOKE=1`: start a `Server`, submit `msgtest`,
   wait for completion, and assert a stats line carrying real token
   counts.
2. Document in 13 §Live smoke how to run them, including which
   credentials each needs.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/smoke"                    # skipped
ATHANORE_SMOKE=1 ./scripts/dev.sh "uv run pytest -q tests/smoke"   # real
```

The second needs `OPENROUTER_API_KEY` (pi) or Claude credentials in the
shell that started compose. If a credential is missing, the test must
**skip with a message naming it**, not fail with a transport error.

## Done

- Skipped in CI; passing locally against installed adapters, or skipped
  with a clear reason.
- `**Status.** Done.` on `### T077`, in the same commit.

## Files

```
tests/smoke/{test_pi.py,test_claude.py}
docs/v1/13-testing.md
docs/v1/17-serial-task-plan.md
```
