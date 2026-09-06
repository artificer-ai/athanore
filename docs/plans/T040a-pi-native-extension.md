# T040a — pi extension for the `native` tier

**Task.** `docs/v1/17-serial-task-plan.md` § `### T040a`.
**Specs.** `docs/v1/05-agents.md` §Tooling tiers (`native`);
`docs/v1/19-agent-prompts.md` (the tool descriptions — copy them);
`docs/v1/08-api.md` §Agent endpoints;
`docs/v1/15-decisions.md` D14.

## What this task is

A TypeScript pi extension registering five tools, so a pi agent reaches
the task API as native tool calls rather than curl.

## What this task is not

- Nothing in `athanore/`. This is `examples/pi`, and the sandbox image
  copies it in.
- No new API surface **except** the one addition the task names:
  `output_schema?` on `GET /api/agent/tasks/{id}` (08). That is a wire
  change — regenerate `tests/snapshots/openapi.json` and the TypeScript
  client, or the contract job fails.

## Steps

1. `examples/pi/extensions/athanore.ts`: `pi.registerTool()` for
   `get_task`, `append_log`, `submit_result`, `ask_operator`,
   `wait_answer`, each calling the HTTP API using `ATHANORE_TASK_URL`
   and `ATHANORE_TASK_TOKEN` from the environment. Descriptions copied
   from 19 — the same text the prompt would have carried.
2. `submit_result` fetches the schema from
   `GET /api/agent/tasks/{id}`, so pi's tool definition shows it. Add
   `output_schema?` to that response in 08 and in the API.
3. The pi example agents set `tooling="native"`; the image copies the
   extension into `~/.pi/agent/extensions/`.
4. A README in `examples/pi` explaining the tier.

## Verification

`examples/tests/test_pi_extension.py`:

- the extension file parses and registers five tools — a node smoke test
  via `pi -e` in the sandbox, **skipped** (not failed) when pi is
  unavailable;
- the façade prompt for a `native` agent contains no curl and no token.

Then the smoke run the task's Done requires: dispatch a real pi agent in
the sandbox and confirm `append_log` appears as a tool call in the
transcript. Say in the report which of these actually ran.

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- Tests pass; the OpenAPI snapshot and client regenerated for
  `output_schema`.
- The sandbox smoke run observed, or its absence reported plainly.
- `**Status.** Done.` on `### T040a`, in the same commit.

## Files

```
examples/pi/extensions/athanore.ts
examples/pi/README.md
athanore/api/routers/agent.py     (output_schema)
docs/v1/08-api.md
tests/snapshots/openapi.json
web/src/api/gen/**
examples/tests/test_pi_extension.py
docs/v1/17-serial-task-plan.md
```
