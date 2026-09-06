# T042 — Error model, 422 shape, body-limit middleware, `create_app`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T042`.
**Specs.** `docs/v1/08-api.md` §Conventions (the error codes and the
error body shape); `docs/v1/02-architecture.md` §Configuration
(`body_limit`).

## What this task is

The API's spine: one error shape, one place that maps domain exceptions
onto it, a body-size guard, and the app factory the routers hang off.

## What this task is not

- No routers yet — T043 onward add them. `create_app` grows a lifespan
  that does nothing at this point, and that is correct.
- No new error codes beyond the one the task names: `payload_too_large`,
  which is **a choice the docs did not make** — record it as D53 in
  `docs/v1/15-decisions.md`.
- Do not let FastAPI's default validation body escape: 422 has one shape
  here, and the SPA depends on it.

## Steps

1. `athanore/api/errors.py`: `class ErrorCode(StrEnum)` with 08's codes
   plus `payload_too_large`; `class ApiError(Exception)` carrying
   `status`, `code`, `message` and `**extras`; handlers rendering
   `{"error", "code", **extras}`.
2. Map the domain exceptions: `NotFound → 404 not_found`,
   `Conflict → 409 conflict`, `UnknownWorkflow → 404 unknown_workflow`,
   `UnknownNode → 404 unknown_node`, `GraphError → 409 graph_error`,
   `InvalidOption → 400`, `InvalidAnswer → 422`,
   `AlreadyAnswered → 409`, `StaleRequest → 409 stale_request`.
   `RequestValidationError → 422 {"error": "validation failed",
   "code": "validation", "errors": [...]}`.
3. `athanore/api/middleware.py`: `BodyLimitMiddleware(app, limit)` as
   **pure ASGI** — reject `Content-Length > limit` with 413 *before
   reading*, and otherwise wrap `receive` to count bytes and stop past
   the limit (responding 413 if headers have not been sent). A chunked
   upload with no `Content-Length` is the case that matters; a check
   that only reads the header is decorative.
4. `create_app(settings, engine, store, plugins)`: lifespan, middleware,
   handlers, and `state.settings / engine / store / started_at`.

## Verification

`tests/api/test_errors.py`:

- every mapping above, asserted on both status and `code`;
- 413 on a 2 MiB body **with** `Content-Length` and **without** it
  (chunked);
- the 422 body shape, exactly.

## Done

- Tests pass; a D53 row for `payload_too_large`.
- Snapshot regenerated if the shape changed (`uv run
  scripts/dump_openapi.py && pnpm -C web gen`).
- `**Status.** Done.` on `### T042`, in the same commit.

## Files

```
athanore/api/{errors.py,middleware.py,app.py}
docs/v1/15-decisions.md
tests/api/test_errors.py
docs/v1/17-serial-task-plan.md
```
