# T044b — Tasks and requests routers

**Task.** `docs/v1/17-serial-task-plan.md` § `### T044b`.
**Specs.** `docs/v1/08-api.md` §Tasks and §Requests;
`docs/v1/06-requests.md` §Errors (the mapping).

## What this task is

The remaining operator routers: one task's detail and transcript, and
the request inbox with the answer endpoint.

## What this task is not

- No agent-facing routes — T045 owns `/api/agent/`, with a different
  auth dependency.
- No new request semantics; T031's service already decided them.

## Steps

1. `routers/tasks.py`: get (including submissions, **never** a token);
   `/stream` with `?after&limit` and `live = task in progress`;
   retry / move / status, returning 409 `conflict` on a join target
   (T024c's rule, surfaced).
2. `routers/requests.py`: inbox (`?pending&run`), get, and answer
   returning the **updated** `RequestView`, with 06's mapping:
   400 `invalid_option`, 409 `already_answered` / `stale_request`, 422
   for a validator failure.

## Verification

`tests/api/test_tasks_api.py` and `tests/api/test_requests_api.py`:

- stream pagination and the `live` flag;
- retry / move / status transitions;
- **every** answer error code, one test each;
- the inbox excludes stale requests as well as answered ones.

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- Tests pass; snapshot and client regenerated.
- `**Status.** Done.` on `### T044b`, in the same commit.

## Files

```
athanore/api/routers/{tasks.py,requests.py}
tests/api/{test_tasks_api.py,test_requests_api.py}
tests/snapshots/openapi.json
web/src/api/gen/**
docs/v1/17-serial-task-plan.md
```
