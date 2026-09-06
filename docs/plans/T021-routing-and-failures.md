# T021 — Routing interpretation and failure classes

**Task.** `docs/v1/17-serial-task-plan.md` § `### T021`.
**Specs.** `docs/v1/04-engine.md` §Routing (the table this task
implements, row for row) and §Failure policy;
`docs/v1/15-decisions.md` D42.
**Reference.** v0's `Scheduler._interpret` — same three rules, now with
an explicit table and a retryability predicate.

## What this task is

Rule 2 and rule 3, as two small pure modules: what a node's return value
means, and which exceptions are worth retrying.

## What this task is not

- No scheduler, no attempt loop, no dead-lettering — T032 onward call
  these.
- No new routing forms. The 04 table is exhaustive; if a value does not
  appear in it, it is a `GraphError`, not a new feature.

## Steps

1. `athanore/engine/errors.py`: `class NonRetryable(Exception)` and
   `is_retryable(exc) -> bool` — `False` for `GraphError`,
   `NonRetryable` and subclasses; `True` otherwise, **including
   `TimeoutError`**. A code defect reproduces on retry and must not burn
   inference (D42); a timeout may not.
2. `athanore/engine/routing.py`: `interpret(node, value) ->
   list[Transition]` per the table:
   - `Transition`, `EdgeRef`, or a list of them → those transitions;
   - a plain value with exactly one edge → that edge, carrying the value;
   - a plain value with ≥2 edges → `GraphError` (ambiguous);
   - no edges → terminal;
   - an empty list → terminal with `value=[]`. **04 does not say this
     today** — the task instructs you to state it there, so update 04
     in the same commit;
   - a target not among the node's declared edges → `GraphError`.
   Payloads coerce through `jsonable` (T019).

## Verification

`tests/engine/test_routing.py` — every row of the 04 table, plus:

- a list mixing `EdgeRef` and `Transition`;
- a pydantic model payload becoming a dict;
- `is_retryable(GraphError(...))` false, `is_retryable(TimeoutError())`
  true, and a `NonRetryable` subclass false.

## Done

- Tests pass, one per table row.
- 04 §Routing updated with the empty-list rule.
- `**Status.** Done.` on `### T021`, in the same commit.

## Files

```
athanore/engine/errors.py
athanore/engine/routing.py
tests/engine/test_routing.py
docs/v1/04-engine.md
docs/v1/17-serial-task-plan.md
```
