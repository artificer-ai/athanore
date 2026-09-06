# T033 — `human_input`: modes, slot release, timeout

**Task.** `docs/v1/17-serial-task-plan.md` § `### T033`.
**Specs.** `docs/v1/06-requests.md` §`human_input`;
`docs/v1/04-engine.md` §Waiting.

## What this task is

The user-facing await: one function that opens a request, parks the task
without holding its worker slot, and returns the answer decoded
according to the mode.

## What this task is not

- No agent permissions or elicitations (T035+) — those open requests
  too, but through `create_agent_request`.
- No new waiting mechanism. T026 built `lease.released()`; use it.
- No polling loops in user land. The body awaits; the engine handles the
  rest.

## Steps

1. `async def human_input(prompt, *, options=None, output_model=None,
   timeout=None)` — mode from the arguments:
   - `options` → normalise `[str | dict]` into
     `[{option_id, name, kind}]`;
   - `output_model` → `form`, schema from `model_json_schema()`;
   - neither → `text`.
   Passing both is a `ValueError`, not a silent precedence rule.
2. `req = await ctx.services.requests.reopen_or_create(...)`; register
   the validator.
3. `async with ctx.services.lease.released(req.id): answer = await
   wait(req.id, timeout)`; unregister the validator in a `finally` —
   a validator left registered after a timeout leaks into the next
   answer.
4. Decode: `options` → the `option_id` string; `text` → the string;
   `form` → `output_model.model_validate(value)`.
5. `TimeoutError` propagates into the body, where rule 3 applies.

## Verification

`tests/requests/test_human_input.py`:

- `options` returns the chosen id;
- `text` returns the string;
- `output_model` returns an instance, and a misfit answer is rejected
  **at the endpoint** with 422 rather than reaching the body;
- `timeout=0.1` raises inside the body;
- **the slot is released**: under `workers=1`, a second run's task starts
  while the first is parked, and the parked body resumes ahead of newly
  ready tasks when answered.

That last one is the test that proves T022, T026 and this task compose;
if it passes for the wrong reason (capacity > 1), the test is wrong.

## Done

- Tests pass, including the slot-release ordering.
- `**Status.** Done.` on `### T033`, in the same commit.

## Files

```
athanore/requests/human.py
tests/requests/test_human_input.py
docs/v1/17-serial-task-plan.md
```
