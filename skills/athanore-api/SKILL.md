---
name: athanore-api
description: Drive the Athanore HTTP API and its SSE event stream from a client — the endpoint groups, the two credentials, the error shape, pagination and size caps, and the generated OpenAPI document and TypeScript client. Load this before writing anything that talks to a running Athanore over HTTP, or before changing a route and needing to know what must be regenerated.
---

# Using the Athanore HTTP API

Every path in this file is relative to the **checkout root**: the
directory two levels above this file in the checkout this skill was
installed from. Nothing here is normative — `docs/v1/08-api.md` is the
specification and this only says which part of it to open.

## The surface

The HTTP API and its event stream are the only way in: the SPA, the
CLI, agents and plugins all go through this one contract. Three ideas
are the whole of it:

1. **One contract, generated.** OpenAPI is generated from the code and
   the TypeScript client from OpenAPI, and both are committed, so a
   change to a route shows up as a diff:
   `docs/v1/08-api.md` §OpenAPI. Neither
   `tests/snapshots/openapi.json` nor `web/src/api/gen` is ever
   hand-edited.
2. **Two credentials.** An operator bearer token, needed only on a
   non-loopback bind, and a task token that is header-only, reaches one
   task, and never appears in an operator response:
   `docs/v1/08-api.md` §Authentication (12 has the model).
3. **One push, and it is the event stream.** Everything realtime is SSE;
   there is no second channel and no polling contract:
   `docs/v1/08-api.md` §Events (SSE).

## What is and is not a seam

**Adding a route to `athanore/api` is not how this surface is
extended.** A new endpoint that belongs to a workflow is a plugin route,
mounted under that workflow's own name — see
`skills/athanore-plugins/SKILL.md`. What this skill is for is *use*: the
endpoint groups, the credentials, the error shape, and the two ways an
agent reaches its own task.

## Where to read

| If you are asking | Open |
|---|---|
| how are ids, ordering, pagination and JSON spelled? | `docs/v1/08-api.md` §Conventions |
| do I need a token on this bind, and where does it go? | `docs/v1/08-api.md` §Authentication (12 has the model) |
| what may a task token do, and how long does it live? | `docs/v1/12-security.md` §Task tokens |
| where does the operator token come from? | `docs/v1/12-security.md` §Operator token (network binds only) |
| which endpoints are there? | `docs/v1/08-api.md` §Endpoints |
| what does the run graph response mean? | `docs/v1/08-api.md` §Graph semantics |
| what can an agent call on its own behalf? | `docs/v1/08-api.md` §Agent-facing (task token; own prefix, tagged `agent` in OpenAPI) |
| how does an agent use MCP instead of REST? | `docs/v1/08-api.md` §MCP (agent-facing, task token) |
| how do I subscribe to events, filter them, and resume after a drop? | `docs/v1/08-api.md` §Events (SSE) |
| what does an error body look like? | `docs/v1/08-api.md` §Conventions |
| how big may a payload, a log entry or a transcript chunk be? | `docs/v1/08-api.md` §Sizes |
| what is allowed to change without a new version? | `docs/v1/08-api.md` §Versioning |
| what must I regenerate after changing a route? | `docs/v1/08-api.md` §OpenAPI |
| what does an event's `data` object contain? | `docs/v1/18-event-payloads.md` §Payloads |
| how is that union typed for a TypeScript client? | `docs/v1/18-event-payloads.md` §Typing |

After a route changes, `uv run scripts/dump_openapi.py` and
`pnpm -C web gen` regenerate the snapshot and the client; CI's
`contract` job runs both and fails on a tree either left dirty. A route
whose wire shape changed without those two files changing is the one
failure this contract exists to catch.

## What to copy

- `tests/snapshots/openapi.json` — the entire contract in one file, and
  the fastest way to answer "what does this endpoint accept?".
- `athanore/cli/client.py` — a working Python client of this API,
  including how it resolves a server and a token.
- `web/src/api/client.ts` — how the SPA configures the generated client;
  `web/src/api/gen/` is the generated part.
- `web/src/realtime/` — a working SSE consumer, including what it does
  with each event.
- `examples/pi/extensions/athanore.ts` — a client of the *agent* surface,
  written from inside an agent.

## Generated reference

Facts, read off the committed contract by `scripts/gen_skills.py`, so
they cannot drift from it:

- `skills/athanore-api/reference/routes.md` — every operation, its tag
  and the credential it declares.
- `skills/athanore-api/reference/error-codes.md` — the `code`
  vocabulary a client branches on.

The event names that arrive on the stream, and the payload each one
carries, are `skills/athanore-workflows/reference/events.md`.
