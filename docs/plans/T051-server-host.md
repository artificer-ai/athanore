# T051 — `Server` host with uvicorn

**Task.** `docs/v1/17-serial-task-plan.md` § `### T051`.
**Specs.** `docs/v1/02-architecture.md` §Programmatic host;
`docs/v1/12-security.md` §Auth (the refuse-to-start rule);
`docs/v1/14-migration-and-phasing.md` §v0 databases.

## What this task is

The thing that ties settings, store, engine, API and uvicorn together —
and the two refusals that keep a misconfigured install from running:
a non-loopback bind without a token, and a v0 database opened as if it
were v1.

## What this task is not

- No CLI (T052/T053). `Server` is the library surface; the CLI drives it.
- No discovery — T072 fills the hook.
- Not a place for new behaviour: it wires up what already exists.

## Steps

1. `class Server(settings=None)`:
   - `register(wf, pool=None)` — finalize, check the name against
     `cli.verbs.RESERVED`, against pool names and existing workflows,
     `collect` + `validate` the plugins, then `engine.register`;
   - `async start()` — migrate when `run_migrations`; **`is_v0_database`
     → refuse with the import hint** (silently migrating someone's v0
     database in place is unrecoverable); build the `Store`, start the
     `Engine`, `create_app`, start uvicorn on a free or configured port
     using the quiet-server pattern, and start the retention loop;
   - `async stop()`, `serve()` (`asyncio.run`, SIGINT/SIGTERM → stop),
     and a `url` property.
2. **Refuse to start on a non-loopback host without an operator token.**
   This is the rule T043's test already asserts from the API side; it is
   enforced here.
3. `Workflow.run(**settings)` builds a `Server` and serves — T020's lazy
   import resolves to this. `AthanoreServer = Server` as the alias.

## Verification

`tests/test_server.py`:

- start and stop **twice in one event loop** (a server that cannot
  restart breaks every test that follows);
- port 0 picks a free port and `url` reports it;
- a reserved workflow name is rejected;
- `wf.run` smoke via a thread;
- a v0 database is refused with the hint;
- `0.0.0.0` with no token refuses to start.

## Done

- Tests pass.
- `**Status.** Done.` on `### T051`, in the same commit.

## Files

```
athanore/server.py
tests/test_server.py
docs/v1/17-serial-task-plan.md
```
