# T048 — OpenAPI metadata and snapshot

**Task.** `docs/v1/17-serial-task-plan.md` § `### T048`.
**Specs.** `docs/v1/08-api.md` §OpenAPI (tags and security schemes);
`docs/v1/03-domain-model.md` §Event vocabulary.

## What this task is

Making the generated document describe the contract properly: tags,
security schemes, and enums that survive into TypeScript instead of
degrading to `string`.

## What this task is not

- No behaviour changes. If a route's shape changes here, that is a bug
  in the router's task, not something to paper over with metadata.
- No hand-edits to the snapshot or the generated client. Both are
  regenerated output.

## Steps

1. Tags per 08 §OpenAPI.
2. `openapi_extra` security schemes: `taskToken` (apiKey header
   `X-Athanore-Token`) on the agent router, `operatorBearer` on the
   operator routers. This is what makes the two auth modes visible to
   anyone reading the document rather than the code.
3. `Event.name` typed as `EventName | str` with the enum referenced, and
   `ApiError.code` as `ErrorCode` — so the SPA gets a union, not a bare
   string.
4. Regenerate `tests/snapshots/openapi.json` and `web/src/api/gen`.
5. Extend the snapshot test with: **every `EventName` appears in the
   schema enum**. That is the check that keeps the TypeScript mirror
   honest as later tasks add events.

## Verification

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen
./scripts/dev.sh "uv run pytest -q tests/test_openapi_snapshot.py"
./scripts/dev.sh "pnpm -C web typecheck"
```

The typecheck matters here: a union that generated wrongly shows up as a
TypeScript error, not as a Python one.

## Done

- CI contract job green; the EventName-coverage assertion in place.
- `**Status.** Done.` on `### T048`, in the same commit.

## Files

```
athanore/api/{app.py,routers/**,schemas/**}
tests/snapshots/openapi.json
web/src/api/gen/**
tests/test_openapi_snapshot.py
docs/v1/17-serial-task-plan.md
```
