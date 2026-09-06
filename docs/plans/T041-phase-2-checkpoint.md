# T041 — Phase 2 checkpoint

**Task.** `docs/v1/17-serial-task-plan.md` § `### T041`.
**Specs.** `docs/v1/13-testing.md` §Definition of done.

## What this task is

The Phase 2 checkpoint: prove requests and agents hold together, and
write down the implementation details the phase decided.

## What this task is not

- No new code. A defect found here is reported, not fixed — the fix is a
  task of its own, and hiding it in a checkpoint loses which task
  shipped it.

## Steps

1. Full gate: `./scripts/test.sh`.
2. `pyright` clean on the strict paths (`graph`, `engine`, `store`).
3. Update `docs/v1/05-agents.md` and `docs/v1/06-requests.md` with the
   details Phase 2 settled:
   - the **stderr cap** (64 KiB) on the agent subprocess pump;
   - the **kill grace period** (terminate, then kill after 5 s);
   - the empty-list return being terminal (if 04's update from T029 left
     05/06 inconsistent, fix the inconsistency here).
4. Run the examples on `FakeACPAgent` through `ATHANORE_AGENT_COMMAND`
   as 13 §Running examples on the fake describes — the phase-gate check
   the plan's working rules require from T037 onward.

## Verification

```sh
./scripts/test.sh
./scripts/dev.sh "uv run pyright"
./scripts/dev.sh "uv run pytest -q examples"
```

Then read 05 and 06 against `athanore/agents/acp.py` and
`athanore/requests/` — the checkpoint's real work.

## Done

- Gate green; docs match the code; examples run on the fake.
- Anything questionable written up rather than fixed.
- `**Status.** Done.` on `### T041`, in the same commit.

## Files

```
docs/v1/05-agents.md
docs/v1/06-requests.md
docs/v1/17-serial-task-plan.md
```
