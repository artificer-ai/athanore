# T044 — Response schemas and the workflows router

**Task.** `docs/v1/17-serial-task-plan.md` § `### T044`.
**Specs.** `docs/v1/08-api.md` §Workflows and §Schemas;
`docs/v1/18-event-payloads.md` (`EventEnvelope`).

## What this task is

The pydantic surface of the wire contract, and the first real router.
Every schema added here lands in the OpenAPI snapshot and generates
TypeScript, so getting a field wrong is a change to two committed files.

## What this task is not

- No runs router (T044a), no events (T045+), no plugins (T049) — the
  `plugin` field on a workflow is a placeholder until then.
- `TaskView` **never** carries `token_hash`. T010 excluded it at the
  model level; keep it excluded here rather than relying on that alone.

## Steps

1. `athanore/api/schemas/*.py`: `RunSummary`, `RunDetail` (with
   `outputs`, `stats`), `TaskView` (with `terminal`, `branch`),
   `LogEntry`, `EventEnvelope`, `RequestView`, `WorkflowOut`, `NodeOut`,
   `GraphOut`, `SourceOut`, `StreamOut`, the request bodies (`NewRun`,
   `EditRun`, `Position`, `LogText`, `Rerun`, `Move`, `SetStatus`,
   `Answer`), plus `Ok` and `Created`.
2. `routers/workflows.py`: list and get (graph, pool, capacity,
   `in_flight`, `plugin` placeholder), `/source` via
   `inspect.getsourcefile` + `getsourcelines` per node, and
   `POST /runs` returning **201**.
3. Every operator router uses `Depends(operator_auth)` and 08's tags —
   the tags are what group the generated client, so they are part of the
   contract too.

## Verification

`tests/api/test_workflows_api.py` through
`httpx.AsyncClient(transport=ASGITransport(app))`:

- the list shape including generations and node options;
- 404 on an unknown workflow;
- `/source` returns the right lines per node;
- submit → 201 and a `queued` run.

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- Tests pass; snapshot and generated client committed.
- `**Status.** Done.` on `### T044`, in the same commit.

## Files

```
athanore/api/schemas/**
athanore/api/routers/workflows.py
tests/api/test_workflows_api.py
tests/snapshots/openapi.json
web/src/api/gen/**
docs/v1/17-serial-task-plan.md
```
