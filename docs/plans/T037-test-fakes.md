# T037 — `FakeACPAgent`, `MockAgent`, `StatsMockAgent`, `FakeStatsProvider`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T037`.
**Specs.** `docs/v1/13-testing.md` §Fakes (the JSON scenario vocabulary —
every key, exhaustively); `docs/v1/19-agent-prompts.md` (the blocks the
fake parses).
**Reference.** v0's `tests/fake_acp.py`.

## What this task is

The only agent CI ever runs. Everything downstream — the ACP lifecycle
tests, the API tests, the E2E suite — is only as trustworthy as this
fake, so its scenario vocabulary is a contract, not a convenience.

## What this task is not

- **Not a shortcut.** `AGENTS.md`: "`FakeACPAgent` is a test fixture, not
  a shortcut." It lives in `athanore/testing/`, ships with the package,
  and is held to the same bar as the rest.
- No vendor adapters. pi and Claude live in `examples/`.
- **Unknown scenario keys are an error**, not ignored — a typo in a
  scenario must fail loudly rather than silently testing nothing.

## Steps

1. `athanore/testing/fake_acp.py` — port v0's fake to 13's vocabulary:
   every key listed there, including `log` and `submit` against the task
   API, and per-node selection via `ATHANORE_FAKE_SCENARIOS`.
2. `athanore/testing/scenarios.py`: `scenario(**kwargs) -> list[str]`
   returning the `command` for `ACPAgent(command=…)`.
3. `athanore/testing/mock.py`:
   - `MockAgent(output=None, submit=None, log=None, stream=None,
     fail=None)` — no subprocess. `submit=` posts to `ctx.api_base` with
     the task token via httpx **once the API exists in T045**; until
     then it calls `services.submissions.accept` directly behind a flag.
     Leave that flag obvious and short-lived — T045's job is to remove
     it, and it should be a `# T045` marker, not a permanent branch;
   - `StatsMockAgent(stats=…, fail=False)` calling `record_entry`;
   - `FakeStatsProvider(stats=…, stop_reason=…)`.
4. `athanore/testing/__init__.py` exports them.

## Verification

`tests/testing/test_fake_acp.py`, driving the fake with a **raw ACP
client** rather than through `ACPAgent` (which does not exist until
T039):

- it speaks `initialize`, `session/new`, `session/prompt`;
- each scenario key does what 13 says;
- an unknown key raises.

## Done

- Tests pass; every key in 13 §Fakes is exercised by at least one test.
- `**Status.** Done.` on `### T037`, in the same commit.

## Files

```
athanore/testing/{fake_acp.py,scenarios.py,mock.py,__init__.py}
tests/testing/test_fake_acp.py
docs/v1/17-serial-task-plan.md
```
