# T035 — Submissions helpers

**Task.** `docs/v1/17-serial-task-plan.md` § `### T035`.
**Specs.** `docs/v1/05-agents.md` §Submissions and §Repair;
`docs/v1/19-agent-prompts.md` §Repair block.

## What this task is

The three small pieces around a structured submission: validate it,
attach the latest one to a result, and build the repair prompt when an
agent finished without a valid one.

## What this task is not

- No ACP turn loop — T037 decides *when* to repair; this task only says
  whether repair is needed and what the prompt says.
- No new event names. `submission.accepted` and the rejection event are
  T023's service.

## Steps

1. `validate_submission(model, payload) -> (ok, errors, normalised)`.
2. `attach(ctx, result) -> AgentResult`: take the latest submission via
   `services.submissions.latest()`, validate against `ctx.output_model`;
   a missing or invalid one raises
   `AgentError("agent finished without a valid submission")`; with no
   model declared, attach the raw payload. **Latest**, not first — an
   agent that submits twice meant the second one.
3. `needs_repair(ctx, stop_reason) -> bool`: `end_turn`, a model is
   declared, and no valid submission exists.
4. `repair_prompt(ctx, turn) -> str` quoting `ctx.last_rejection`'s
   errors and the schema, byte-exact per 19.

## Verification

`tests/agents/test_submissions_unit.py`:

- `attach` picks the latest of several submissions;
- `attach` raises the exact `AgentError` message when there is none;
- the repair prompt contains the last errors and the schema;
- `needs_repair` is false when the stop reason is not `end_turn`, even
  with a model declared.

## Done

- Tests pass.
- `**Status.** Done.` on `### T035`, in the same commit.

## Files

```
athanore/agents/submissions.py
tests/agents/test_submissions_unit.py
docs/v1/17-serial-task-plan.md
```
