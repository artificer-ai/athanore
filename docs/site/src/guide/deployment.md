# Deployment

The default deployment is one person, one process, loopback only, and it
needs no configuration at all. This page is about the cases that need
more: a server other people reach, a bigger database, and the ordinary
housekeeping of a thing that keeps state.

## Configuration

Settings come from, in order of precedence: command-line flags, then
environment variables prefixed `ATHANORE_`, then an `athanore.toml`
beside the database, then the defaults. Every setting, its variable, its
file key and its default is in [Settings](../reference/settings.md).

```toml
host = "127.0.0.1"
port = 4002
workers = 2
max_retries = 3
log_format = "json"

[retention]
events_days = 30
stream_days = 14

[pools]
build = 2

[workflows]
feature_build = { pool = "build" }
chat = { target = "workflows/chat.py:wf" }
```

A `[workflows.<name>]` row with a `pool` binds a workflow that arrives
some other way; one with a `target` is a registration in its own right —
`athanore serve` loads it after the targets on its command line and
before the installed packages' entry points, and a registration made
while serving with `persist` is written here as exactly such a row, the
rest of the file kept as it was.

An unknown top-level key is an error at startup rather than a default
quietly taken — a typo in a capacity setting is worth stopping for. Two
settings are refused in the file entirely: the operator token, because it
is a secret, and the agent command override, because it is a test hook.

## Binding to a network

A loopback bind has no operator authentication. Binding anywhere else
turns one on, and the server refuses to start without a token:

```sh
athanore token rotate            # writes .athanore/token, owner-only
athanore serve --host 0.0.0.0
```

Clients then send `Authorization: Bearer <token>`; the command line takes
`--token`, reads `ATHANORE_TOKEN`, or remembers one from `athanore
login`. On a loopback bind the token is ignored entirely, so a machine
that never binds a network never sees a login screen.

## Behind a reverse proxy

There is no built-in TLS. Terminate it in a proxy, keep the application
bound to loopback, and set `require_token` — because "loopback means
trusted" would otherwise expose the API through the proxy with no
credential at all.

Two more settings make that work: `public_url`, which is what agents and
plugins are told to call back on, and `forwarded_allow_ips`, which is
the list of proxies whose forwarded headers the server trusts.

Cross-origin requests are off unless `cors_origins` is set. The interface
is same-origin in production and no cookies are used.

## Postgres

SQLite is the default and is a real answer for a single-operator install:
one file, write-ahead logging, a five-second busy timeout, foreign keys
on. For anything larger:

```sh
uv add "athanore[postgres]"
export ATHANORE_DB_URL="postgresql+asyncpg://user:pass@host/athanore"
athanore db upgrade
athanore serve
```

## Migrations

The schema is managed with Alembic and `athanore serve` upgrades to head
before it serves. Set `run_migrations` to false if you would rather do it
yourself, in which case:

```sh
athanore db current     # what the database is at
athanore db upgrade     # bring it to head
```

Nothing alters tables implicitly at runtime.

## Backups

```sh
athanore db backup /backups/athanore-$(date +%F).db
```

That uses SQLite's own backup interface, so it is consistent while the
server is running. It refuses another backend, a database that is not
there, and a destination that already exists.

## Retention

A background job prunes on an hourly tick. Agent transcript chunks for
finished tasks are dropped after `stream_days` — the work log keeps the
deliverables, and the transcript is diagnostic — and events after
`events_days`, except run-level lifecycle events, which are kept for as
long as the run is. Deleting a run deletes everything under it.

## Running agents in containers

Containerising anything that executes code is the recommended posture,
and it needs nothing from Athanore: an agent's `command` is a command
line, so it can be `docker run` as easily as `npx`.

```python
from athanore import ACPAgent


class Sandboxed(ACPAgent):
    command = ["docker", "compose", "run", "--rm", "-T", "agent"]
    permission_policy = "auto_allow"
```

`permission_policy="auto_allow"` is reasonable *because* the container is
the guardrail. Permission prompts in the protocol are advisory; a hard
deny belongs in the agent harness's own settings, and a real boundary
belongs in the sandbox.

The agent's environment is scrubbed of session-scoped variables before it
is spawned; `env` adds what you want, and `env_allowlist` switches to
allowing nothing by default. Its working directory is yours to choose,
and the engine never writes there.

## Hygiene

- The database file and the token file are owner-only. `athanore token
  show` prints the effective token and where it came from.
- Nothing logs a token, an authorization header, or the stream's query
  string.
- There is no telemetry, and the interface makes no request to anyone
  but the server that served it.
- Pin agent adapter versions rather than floating them. An agent command
  is code you chose to run.

## What is not built

Built-in TLS, rate limiting and multi-user authentication are not in this
version. The first two are a proxy's job for now; the third is a single
seam — the dependency that resolves who is calling — when it is wanted.

## Next

- [Settings](../reference/settings.md) — every setting, generated from
  the model.
- [The command line](cli.md) — the database and token verbs.
