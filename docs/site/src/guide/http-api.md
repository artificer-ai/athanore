# Driving the API

The HTTP API and its event stream are the only way in. The browser
interface, the command line, agents and plugins all go through this one
contract, so anything they can do, your client can do.

Every operation, its parameters, its request body, its responses and
every schema are in [HTTP API](../reference/http-api.md), generated from
the document the server produces.

## The document

The server publishes its own OpenAPI at `/openapi.json`, with interactive
views at `/docs` and `/redoc`. That document is generated from the code
and snapshot-tested, so it cannot drift from the routes; a copy of it is
[published beside this site](../openapi.json).

Generating a client from it is the recommended way to write one:

```sh
npx @hey-api/openapi-ts -i http://127.0.0.1:4002/openapi.json -o src/api/gen
```

The event-name and error-code vocabularies are enums in the document, so
a generated TypeScript client gets unions rather than bare strings.

## Authenticating

There are two credentials, and on a default install you need neither.

- **Nothing**, on a loopback bind. Athanore is a local tool; the
  interface and the command line call the API plainly.
- **An operator bearer token**, when the server is bound to a network
  interface, or when it is behind a proxy and `require_token` is set.
  `athanore token rotate` generates one. Send it as
  `Authorization: Bearer <token>`.
- **A task token**, which is what an agent gets. It is minted per attempt,
  sent in the `X-Athanore-Token` header, and reaches exactly one task's
  own endpoints — read the task, append to its log, submit a value, ask a
  question and poll for the answer. It never appears in an operator
  response, and it dies when the attempt does.

Whether a bind is loopback is decided by the configured host, never by
the peer address of a request — which is why a reverse proxy in front of
a loopback bind sets `require_token`.

The stream is the one exception to header-only, because a browser cannot
set headers on it: when a token is needed, `GET /api/events` also accepts
it as a query parameter, and the server does not log that query string.

## The error shape

Every refusal is the same object:

```json
{"error": "no such run", "code": "not_found"}
```

`code` is a stable value from a closed vocabulary; `error` is a human
sentence that may be reworded at any time. Branch on `code`. Some
refusals add fields — a validation failure carries `errors`, and a
rejected agent submission carries `errors` and the `schema` it was
measured against.

The vocabulary is in [Error codes](../reference/errors.md). Status codes
are the ordinary ones: 400 for malformed, 401 for a missing or wrong
operator token, 403 for a task token that was presented and refused, 404,
409 for a state conflict, 413 for a body over the size limit, and 422 for
validation.

A task token fails in two distinguishable ways, and they are two
different statuses. The header is required, so omitting it is a 422
naming the header that is absent. A token that was presented and refused
is a 403 — and unknown, another task's, and an attempt that has ended
share one message, because which of the three it was is not something the
door tells you.

## The event stream

```sh
curl -N "http://127.0.0.1:4002/api/events?names=run.*,task.*"
```

`GET /api/events` is server-sent events, and it is the only push channel;
there is no polling contract and no second socket. Each message carries
an event id, the event name, and a JSON envelope as its data. Every
payload shape is in the document as a discriminated union on the name, so
a generated client gives you a typed switch.

Three things are worth knowing before you write a consumer.

**Resume with a cursor.** Pass `after=<event id>`, or let the browser
send `Last-Event-ID` on reconnect, and the server replays from the store
before switching to live. Replay is capped; past that cap you receive a
`resync` event instead and should refetch rather than assume you have
everything.

**Filter server-side.** `names=` takes globs and `run=` narrows to one
run. One stream per client is the intended shape.

**Transcript chunks are not on the stream.** An agent's output would
swamp it, so a `task.stream` event carries only the task and the
sequence range that arrived, and the chunks themselves are fetched from
the task's stream endpoint. Those events are ephemeral and are sent
without an id, so a reconnecting client's cursor always names something
that was stored.

The names, their groups and the fields each payload carries are in
[Events](../reference/events.md).

## Sizes and pagination

JSON bodies are capped — by default one mebibyte — and a body over it is
refused with `payload_too_large`, whether or not it declared its length.
Lists that can grow take `limit` and `cursor`; run lists are small and
come back whole. Timestamps are ISO-8601 in UTC.

## What is stable

The API is versioned by the package version. New fields, new endpoints
and new event names are minor releases. Removing or renaming anything is
a major release, which would ship under a new path prefix with the old
one proxying for a cycle. The event vocabulary is part of the contract,
not an implementation detail.

## Next

- [Deployment](deployment.md) — putting this behind a proxy, with a
  token.
- [HTTP API](../reference/http-api.md) — every operation and schema.
