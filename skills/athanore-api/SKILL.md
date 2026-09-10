---
name: athanore-api
description: Drive the Athanore HTTP API and its server-sent event stream from a client of your own — the two credentials, the error shape, resuming the stream, sizes and pagination, and generating a typed client from the OpenAPI document. Load this before writing anything that talks to a running Athanore over HTTP.
---

# Using the Athanore HTTP API

The HTTP API and its event stream are the only way in: the browser
interface, the command line, agents and plugins all go through this one
contract, so anything they can do, your client can do. One contract,
generated from the code; two credentials; one push channel. This
directory is self-contained: every file it names is under its own
`reference/`, including the OpenAPI document itself.

## A complete client session

Everything realtime is one server-sent event stream, filtered
server-side:

<!-- from: docs/site/src/guide/http-api.md -->
```sh
curl -N "http://127.0.0.1:4002/api/events?names=run.*,task.*"
```

Every refusal, from any endpoint, is the same object:

<!-- from: docs/site/src/guide/http-api.md -->
```json
{"error": "no such run", "code": "not_found"}
```

The server publishes its own OpenAPI at `/openapi.json`, with
interactive views at `/docs` and `/redoc`, and generating a client from
it is the recommended way to write one:

<!-- from: docs/site/src/guide/http-api.md -->
```sh
npx @hey-api/openapi-ts -i http://127.0.0.1:4002/openapi.json -o src/api/gen
```

With no server running yet, `reference/openapi.json` in this directory
takes the place of the URL: the same document, minus the plugin routes a
running server mounts (`/api/plugins/_builtin/...` and each served
workflow's own).

## The rules an agent gets wrong first

- **On a loopback bind there is no credential.** Send nothing.
- **On a network bind, or behind a proxy with `require_token` set, send
  `Authorization: Bearer <token>`**; `athanore token rotate` generates
  one. Whether a bind is loopback is decided by the configured host,
  never by the peer address.
- **An agent's task token goes in the `X-Athanore-Token` header.** It
  reaches exactly one task's own endpoints, dies with the attempt, and
  never appears in an operator response. Omitting the header is a 422
  naming it; presenting a token that is refused is a 403.
- **Branch on `code`, never on `error`.** `code` is a stable value from
  a closed vocabulary; `error` is a sentence that may be reworded. A
  validation failure adds `errors`; a rejected agent submission adds
  `errors` and the `schema` it was measured against.
- **Resume the stream with a cursor**: `after=<event id>`, or
  `Last-Event-ID` on reconnect. Replay is capped; past the cap you get
  a `resync` event and refetch rather than assume you have everything.
- **Filter server-side** with `names=` (globs) and `run=`; one stream
  per client is the intended shape. The stream is the one place a token
  is also accepted as a query parameter, because a browser cannot set
  headers on it.
- **Transcript chunks are not on the stream.** A `task.stream` event
  carries the task and the sequence range that arrived; the chunks are
  fetched from the task's stream endpoint. Those events are ephemeral
  and carry no id.
- JSON bodies are capped, by default at one mebibyte, and refused with
  `payload_too_large`. Lists that can grow take `limit` and `cursor`.
  Timestamps are ISO-8601 in UTC.
- New fields, endpoints and event names are minor releases; a removal
  or a rename is a major one. The event vocabulary is part of the
  contract.
- **A new endpoint that belongs to a workflow is a plugin route**,
  mounted under the workflow's own name — that is the `athanore-plugins`
  skill, not a change to the API.

## Where to read next

Every file below is in this skill's `reference/`. The guide is
narrative; the rest is generated from the OpenAPI document the server
produces and from the code, so a shape there is the shape on the wire.

- The document, authenticating, the error shape, the event stream,
  sizes and pagination, what is stable: `reference/guide-http-api.md`.
- Every operation with its parameters, request body and responses,
  grouped by tag, and every schema as a field table:
  `reference/http-api.md`.
- The `code` vocabulary: `reference/errors.md`.
- Every event name, grouped, with the fields of its payload:
  `reference/events.md`.
- The OpenAPI document itself, for a code generator:
  `reference/openapi.json`.

The command line is a client of this API and is the `athanore-cli`
skill; an agent reaches its own task through the same surface, which
the `athanore-workflows` skill describes.
