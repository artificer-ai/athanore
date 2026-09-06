# T043 — Auth dependencies, `/api/health`, `/api/me`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T043`.
**Specs.** `docs/v1/12-security.md` §Auth (the whole section);
`docs/v1/08-api.md` §System; `docs/v1/13-testing.md` §Auth matrix;
`docs/v1/15-decisions.md` D47.
**This is the security task of Phase 3.** Read 12 before writing code,
not after.

## What this task is

Who may call what: operator auth by bearer token when the bind is not
loopback, and task auth by header-only token scoped to one task.

## What this task is not

- No token *generation* or rotation (the CLI's, T053).
- No per-route authorisation logic scattered around; it is two
  dependencies.
- **Never** accept a task token in a query string, and never return one
  in an operator response (`AGENTS.md` §Local first).

## Steps

1. `auth_mode(settings) -> "off" | "token"` — `"token"` when
   `not is_loopback or require_token`.
2. `async operator_auth(request)`: a no-op in `off`; otherwise require
   `Authorization: Bearer` equal to `effective_operator_token`, compared
   with **`hmac.compare_digest`** (not `==`), else 401 `unauthorized`.
   For `GET /api/events` only, also accept an `access_token` query
   parameter — EventSource cannot set headers, which is why that one
   exception exists and why it is scoped to that one route.
3. `async task_auth(task_id, x_athanore_token: Header)`: hash it, look
   up `by_token_hash`, require that it matches **this** `task_id` and
   that the status is `in_progress` or `waiting`, else 403 `forbidden`.
   Returns the `TaskRow`.
4. `routers/system.py`: `GET /api/health` (counts from
   `engine.pools.snapshot()` plus a store query) and `GET /api/me`
   (`auth`, `authenticated`, `version`, `started_at`, `features: []`).
5. A log filter redacting `Authorization` and the `access_token` query —
   otherwise the token lands in uvicorn's access log.

## Verification

`tests/api/test_auth.py`, the full matrix from 13:

- loopback plain → OK with no header;
- a `0.0.0.0` bind without a token → **the server refuses to start**;
- with a token: 401 without the header, 200 with it;
- `require_token` on loopback → 401 without it;
- a task token is valid only for its own task, and only while that task
  is in progress — expired after `finish`;
- the redaction filter: assert the token does not appear in captured log
  output.

## Done

- Tests pass, including the refuse-to-start case.
- `**Status.** Done.` on `### T043`, in the same commit.

## Files

```
athanore/api/deps.py
athanore/api/routers/system.py
athanore/logging.py            (redaction filter)
tests/api/test_auth.py
docs/v1/17-serial-task-plan.md
```
