# T008 — OpenAPI → TypeScript pipeline

**Task.** `docs/v1/17-serial-task-plan.md` § `### T008`.
**Specs.** `docs/v1/08-api.md` (the wire contract this pipeline
freezes); `AGENTS.md` §Architecture rules — "one wire contract: OpenAPI
is generated from code; the TypeScript client is generated from OpenAPI
and committed".

## What this task is

The machinery that makes the wire contract checkable: a FastAPI app stub
with exactly one endpoint, a snapshot of its OpenAPI document, a
generated TypeScript client, and a test plus a CI job that fail when any
of the three drifts from the others.

## What this task is not

- **One endpoint only.** `GET /api/health` returning `{ok, version}`.
  No runs, no tasks, no events, no auth dependencies — those are T030
  onward, and each of them regenerates this snapshot as part of its own
  definition of done.
- No hand-written TypeScript in `web/src/api/gen`. It is generated
  output, committed as-is.
- No SPA wiring. Nothing in `web/src` has to *use* the client yet.

## Steps

1. `athanore/api/app.py`: `create_app(settings=None, engine=None,
   store=None, plugins=None) -> FastAPI`. The parameters are the shape
   T031 will fill; they are accepted and unused now, which is the one
   place in this build where an unused parameter is correct — it is the
   published signature, not a stub of behaviour.
2. `scripts/dump_openapi.py`: write `create_app().openapi()` to
   `tests/snapshots/openapi.json` with sorted keys and 2-space indent.
   Deterministic output is the whole point; a dict ordering that varies
   between runs makes the freshness check flap.
3. `web/openapi-ts.config.ts`: input `../tests/snapshots/openapi.json`,
   output `web/src/api/gen`, plugins `@hey-api/client-fetch` and
   `@tanstack/react-query`. `pnpm gen` runs the dump and the codegen.
4. `tests/test_openapi_snapshot.py`: `create_app().openapi()` equals the
   snapshot, with a failure message that tells the reader to run
   `uv run scripts/dump_openapi.py && pnpm -C web gen`.
5. Fill in CI's `contract` job (placeholder from T006) with the real
   check.

## Verification

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen   # must be clean twice in a row
./scripts/dev.sh "uv run pytest -q tests/test_openapi_snapshot.py"
```

Prove the check actually catches drift before you trust it: add a
throwaway route, re-run the test and watch it fail with the message that
names the command, then remove the route and confirm green again. Say in
the TaskReport that you did this — a freshness check nobody has seen
fail is a freshness check nobody knows works.

```sh
./scripts/dev.sh "uv run python -c \"
from athanore.api.app import create_app
import json; app=create_app()
print(json.dumps(app.openapi()['paths'], indent=1)[:400])\""
```

## Done

- Snapshot and generated client committed; regenerating changes nothing.
- The snapshot test fails on a deliberate drift and passes when reverted.
- CI's `contract` job carries the real check.
- `**Status.** Done.` on `### T008`, in the same commit.

## Files

```
athanore/api/app.py
scripts/dump_openapi.py
tests/snapshots/openapi.json
web/openapi-ts.config.ts
web/src/api/gen/**           (generated, committed)
tests/test_openapi_snapshot.py
.github/workflows/ci.yml
docs/v1/17-serial-task-plan.md
```
