# T039a — `ACPAgent.run()`: repair loop, outcome mapping, cleanup, stats once

**Task.** `docs/v1/17-serial-task-plan.md` § `### T039a`.
**Specs.** `docs/v1/05-agents.md` §Outcomes and §Repair;
`docs/v1/19-agent-prompts.md` §Repair block.
**Reference.** v0's `test_submissions.py`, `test_acp_stats.py`,
`test_agents.py` (the subprocess-dependent parts).

## What this task is

The rest of `run()`: keep asking for a valid submission up to a limit,
map how the turn ended onto an `AgentResult`, and clean up the child
process exactly once, recording stats exactly once.

## What this task is not

- No engine retries. Rule 3: a failed agent raises and the **engine**
  decides. Never retry the agent call inside the node body's behalf
  (`AGENTS.md`).
- No new prompt text — 19 owns the repair block.

## Steps

1. Repair loop: while `needs_repair`, send `repair_prompt` **on the same
   session** up to `max_repair_turns`, emitting `submission.repair` and
   a `notice` chunk each time.
2. Outcome mapping:
   - `refusal` / `cancelled` → a **failed result with a reason**, not an
     exception (a refusal is an answer, and the node body routes on it);
   - provider `final_stop_reason == "length"` on the final turn → failed
     with `truncated`;
   - otherwise `attach`.
3. `finally`: `stream.close()`, close the connection, `terminate()` then
   `kill()` after 5 s, and `record_entry` **exactly once** with
   `duration_s`, `tool_calls`, `repair_turns`, `denied_permissions`.
4. Raise `AgentError` (reason `timeout` / `transport` / `no_submission`)
   **after** recording stats — the tokens were spent whether or not the
   turn succeeded, and losing them on the failure path is exactly when
   you most want them.

## Verification

`tests/agents/test_acp_outcomes.py`, on `FakeACPAgent`:

- the repair loop stops at `max_repair_turns`, and the second submission
  wins;
- a refusal returns a failed result and does **not** raise;
- truncation detected through `FakeStatsProvider`;
- a timeout kills the child — assert `proc.returncode is not None`, no
  zombie;
- **stats recorded exactly once** on each of: success, failure, timeout,
  refusal, and shutdown-cancel. Five cases, one row each.

## Done

- Tests pass; ledger rows for `test_permissions.py`,
  `test_elicitation.py`, `test_acp_stats.py` and `fake_acp.py` ticked.
- `**Status.** Done.` on `### T039a`, in the same commit.

## Files

```
athanore/agents/acp.py
tests/agents/test_acp_outcomes.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
