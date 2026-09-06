# T056 — Phase 3 checkpoint

**Task.** `docs/v1/17-serial-task-plan.md` § `### T056`.
**Specs.** `docs/v1/13-testing.md` §Coverage.

## What this task is

The Phase 3 checkpoint: the API, CLI and plugin system are in; turn the
coverage gates on and make 08 and 09 match what was built.

## What this task is not

- No new code, no fixes. A defect found here is reported.
- Do not lower a coverage threshold to make the gate pass. If
  `graph`/`engine`/`requests` cannot reach 95 %, the missing tests are
  the finding.

## Steps

1. Full suite: `./scripts/test.sh`.
2. Enable the coverage gates **in CI**: `graph`, `engine` and `requests`
   ≥ 95 %; overall ≥ 85 %.
3. Update `docs/v1/08-api.md` and `docs/v1/09-plugins.md` with the
   details Phase 3 settled implicitly:
   - the `state` precedence rules in `/graph` (T044a);
   - the `_builtin` manifest workflow and its ordering (T050);
   - `payload_too_large` (T042, D53).
4. Run the examples on `FakeACPAgent` (13 §Running examples on the
   fake), the phase-gate check.

## Verification

```sh
./scripts/test.sh
./scripts/dev.sh "uv run pytest -q --cov=athanore --cov-report=term-missing"
./scripts/dev.sh "uv run pytest -q examples"
```

Read the coverage report rather than the summary line: which branches
are uncovered in `engine` says more about the suite than the percentage
does.

## Done

- Gate green; coverage gates enabled and passing in CI; 08 and 09
  accurate.
- `**Status.** Done.` on `### T056`, in the same commit.

## Files

```
.github/workflows/ci.yml
pyproject.toml
docs/v1/{08-api.md,09-plugins.md}
docs/v1/17-serial-task-plan.md
```
