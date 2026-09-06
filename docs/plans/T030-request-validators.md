# T030 — Request validators and error classes

**Task.** `docs/v1/17-serial-task-plan.md` § `### T030`.
**Specs.** `docs/v1/06-requests.md` §Validation and §Errors;
`docs/v1/08-api.md` §Error codes (what these classes become on the wire).
**Reference.** v0's light JSON-schema validator, currently split between
`agents.py` and `human.py` — this task consolidates it.

## What this task is

Two small modules: the error vocabulary for the request channel, and the
two validators — pydantic-backed and a deliberately light JSON-schema
subset.

## What this task is not

- **T031** is the service. No store access, no bus, no waiting here.
- Not a full JSON Schema implementation. The supported keyword list in
  the task is exhaustive: implement those, and reject nothing else
  silently — an unsupported keyword is ignored, not an error, and the
  tests should say which behaviour you chose.
- No HTTP status codes. These are exceptions; T038 maps them.

## Steps

1. `athanore/requests/errors.py`: `InvalidOption`,
   `InvalidAnswer(errors: list[dict])`, `AlreadyAnswered`,
   `StaleRequest`, `RequestNotFound`.
2. `athanore/requests/validators.py`:
   - `pydantic_validator(model)` — returns the validated **model
     instance**, and converts `ValidationError` into `InvalidAnswer`
     with `[{loc, msg, type}]` entries. The `loc` path is what the SPA
     renders next to the offending field, so nested paths must survive;
   - `json_schema_validator(schema)` supporting `type` (including
     unions), `required`, `properties`, `additionalProperties: false`,
     `enum`, `const`, `items`, `minItems`, `minimum`/`maximum`,
     `minLength`/`maxLength`, `pattern` — returning the value unchanged.

## Verification

`tests/requests/test_validators.py`:

- every supported keyword, accepted **and** rejected;
- `loc` paths for nested objects (`("outer", "inner", 0)`), since a flat
  error message is useless to the form that has to display it;
- `additionalProperties: false` rejecting an unexpected key.

## Done

- Tests pass; pyright clean.
- `**Status.** Done.` on `### T030`, in the same commit.

## Files

```
athanore/requests/errors.py
athanore/requests/validators.py
tests/requests/test_validators.py
docs/v1/17-serial-task-plan.md
```
