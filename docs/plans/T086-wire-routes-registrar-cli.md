# T086 — Wire: routes, registrar port, CLI verbs

**Task.** `docs/v1/17-serial-task-plan.md` § `### T086`.
**Specs.** `docs/v1/22-live-registration.md` §Wire (the table, the
load-failure body, the registrar port, the security paragraph), §CLI,
§Pools, §Persistence (`persist` on the wire and the CLI); `docs/v1/08-api.md` §Conventions (error shape and codes),
§Workflows, §OpenAPI; `docs/v1/11-cli.md` §Verbs, §Exit codes;
`docs/v1/12-security.md` §Plugins; `docs/v1/02-architecture.md`
§Layering (the API imports nothing above its tier); D223 (pool
resolution), D227 (`DELETE` answers 200 with a body).

## What this task is

The verb reaches the wire. Three routes on the existing workflows
router, the port they call the server through, the error codes they
answer with, `target` on `WorkflowOut`, three CLI subcommands, and the
regenerated contract. After this task the chat agent's loop — write,
`POST`, run, edit, `PUT`, run — works over HTTP with no restart.

### The port

1. **`athanore/api/registrar.py`**: `class WorkflowRegistrar(Protocol)`
   with `async add_target(target: str, pool: str | None, persist: bool)
   -> Registered`, `async reload_target(name: str, target: str | None,
   pool: str | None, persist: bool) -> Registered`, `async remove(name:
   str, persist: bool) -> RemovedWorkflow`, and `targets: Mapping[str,
   str | None]`. `Registered.name` is the workflow's name; the router
   answers with `_view(...)` of the graph now registered under it, so
   the response is the same object `GET` gives, plus the
   `X-Athanore-Persisted: <path>` header when `persisted` is set (22
   §Wire) — a receipt belongs on the response, not on the resource.
   `Registered`, `RemovedWorkflow` and `LoadError` come from
   `athanore.plugins.discovery` (T085 defines them there) — the API may
   not import the composition root, and it does not need to.
2. **`Server` implements it.** `add_target(target, pool)`:
   `load_target(target)`; the pool name, when given, is resolved on
   `engine.pools` and an unknown one raises `UnknownPool(name, known)`
   (a small exception in `plugins.discovery` beside `LoadError`, so
   the router maps one module's exceptions); then `await self.add(wf,
   pool=..., target=target)`. `reload_target(name, target, pool)`:
   `target or self.targets[name]`, `LoadError(stage="target")` when
   both are `None` (22 §Wire); `load_target(t, reload=True)`; the
   loaded workflow's name must equal `name`, else
   `LoadError(stage="register", conflict=True, detail="target names
   workflow 'y'; PUT is for 'x' — POST it")`; `await self.replace(wf,
   pool, target=t, persist=persist)`. `remove` is `self.remove`.
   `persist` passes straight through to the verbs; the port adds no
   behaviour of its own. `create_app(registrar=
   ...)` stores it as `app.state.registrar`; `Server.start` passes
   `self`.

3. **`create_app(..., registrar: WorkflowRegistrar | None = None)`**.
   `None` → the three routes raise `ApiError(503,
   ErrorCode.registration_unavailable)`.

### The routes (`athanore/api/routers/workflows.py`)

4. `POST /api/workflows` `RegisterWorkflow {target: str, pool: str |
   None, persist: bool = False}` → 201 `WorkflowOut`; `PUT
   /api/workflows/{name}` `ReloadWorkflow {target: str | None, pool:
   str | None, persist: bool = False}` → 200 `WorkflowOut`; `DELETE
   /api/workflows/{name}?persist=false` → 200 `RemovedWorkflowOut
   {workflow: str, task_ids: list[int]}`. Each carries
   `X-Athanore-Persisted` when it wrote or removed a row. All three
   under the router's existing `operator_auth`; `PUT` and `DELETE` 404
   `unknown_workflow` through the existing `_graph` lookup **before**
   calling the port, so a name that is not registered never reaches the
   loader.
5. **Mapping**, in one function beside the routes:
   - `LoadError` → 422 `workflow_load_failed`, body `{error, code,
     target, stage, detail}` — `error` is the one-line message, `detail`
     the underlying error's full text; except `stage == "register"`
     with a *duplicate* or *renamed* cause → 409 `conflict` (22 §Wire
     lists both). Give `LoadError` a `conflict: bool` so the router does
     not parse messages.
   - `UnknownPool` → 422 `unknown_pool`, `{pool, known: [...]}` extras.
   - `ValueError` from `engine.replace` (pool move with attempts in
     flight) → 409 `conflict`.
   - `PersistError` → 500 `persist_failed`, `{path, detail}` extras;
     nothing was registered (T085 orders the write before the
     mutation), and the body says so in `error`.
   The server logs the `LoadError` at ERROR with the target and the
   traceback (22 §Wire: the traceback is not sent).
6. **`ErrorCode`**: `workflow_load_failed`, `unknown_pool`,
   `registration_unavailable`, `persist_failed`. The TypeScript mirror follows from the
   snapshot (`ErrorCode` is an enum in the schema — confirm the
   generator emits it; it does for the existing codes).
7. **`WorkflowOut.target: str | None`**, description "The target this
   workflow was loaded from; absent for a programmatic registration."
   Serialised absent, not `null`, per 08 §Conventions' real-data rule
   — check how `WorkflowOut` handles its other optionals and match.
8. **Sizes.** The bodies are tiny; the existing body cap applies.

### The CLI (`athanore/cli/inspect.py` or a new `cli/workflows.py`)

9. `athanore workflows` becomes a typer group with
   `invoke_without_command=True`: bare, it prints the table as today
   (the existing tests must pass untouched); `add <target> [--pool]
   [--persist]`, `reload <name> [<target>] [--pool] [--persist]`, `rm
   <name> [--persist]` call the three routes through
   `options.client()`. `add` and `reload` print the `WorkflowOut` the
   way `workflows` prints one entry (or `--json`); `rm` prints the
   interrupted task ids one per line (nothing when none); when the
   response carries `X-Athanore-Persisted`, each prints `persisted to
   <path>` (or `removed from <path>`) as its last line. A `workflow_load_failed` prints `stage: detail` to stderr and
   exits 2; `unknown_pool` likewise with the known pools; `conflict`
   prints the message and exits 1 like other 409s (check
   `cli/client.py`'s existing mapping and extend rather than special-
   case). `RESERVED` is unchanged: `add`, `reload` are subcommands, not
   top-level verbs, and `rm` already is one.

### The contract and the folds

10. `uv run scripts/dump_openapi.py && pnpm -C web gen`; commit both.
11. 08 §Workflows: the three rows and the `X-Athanore-Persisted`
    header; §Conventions: the four codes and the `workflow_load_failed`
    body. 12 §Plugins: the paragraph from 22
    §Wire on the routes being operator routes that execute named
    Python, and never on the agent surface. 11 §Verbs: the three
    subcommands and the exit code. 04 §Programmatic host: one sentence
    that `athanore serve`'s process accepts the same verbs over the API.

## What this task is not

- No SPA change outside `web/src/api/gen`: the invalidation rows and the
  notice are T087.
- No UI for registering, no library-overlay button.
- No persistence beyond passing `persist` through to T085's verbs
  (D220): the toml writer is theirs. No pool creation, no watcher
  (D222).
- No change to the engine, the plugin host or the loader beyond
  `UnknownPool` and `LoadError.conflict`; a gap found here is fixed on
  this branch and noted in the owning plan.
- No new top-level verb; `RESERVED` and the shorthand `athanore
  <workflow> "title"` are untouched.

## Tests

- `tests/api/test_workflows_api.py`, on the started-server fixture
  (`tests/api/conftest.py`) with a workflow file written to `tmp_path`:
  `POST` → 201 with `target` and the workflow then in `GET
  /api/workflows`; `POST` the same name → 409 `conflict`; `POST` with a
  missing file / a file with no `wf` / a graph that does not finalize /
  a panel naming a missing node / a name that is a verb → 422 with the
  exact `{code, target, stage, detail}` for each `stage`; `POST` with
  `pool: "nope"` → 422 `unknown_pool` naming the known pools; `PUT`
  after editing the file → 200 and `GET .../source` shows the new text;
  `PUT` with no body on a programmatic workflow → 422 `stage: target`;
  `PUT` whose target now names another workflow → 409; `PUT` with a
  pool move while an attempt is in flight → 409, and 200 after it
  finishes; `DELETE` while a `FakeACPAgent` attempt is mid-turn → 200
  `{workflow, task_ids: [id]}`, the run then `unregistered: true`, the
  plugin route 404; `DELETE` unknown → 404; `POST` it back → the run
  completes; `persist: true` on `POST`/`PUT`/`DELETE` against a
  fixture `athanore.toml` changes exactly that row and answers with
  `X-Athanore-Persisted`, `persist` omitted changes nothing and sends
  no header, a read-only file → 500 `persist_failed` and `GET
  /api/workflows` unchanged; `GET /api/events` carries `workflow.registered`,
  `workflow.replaced`, `workflow.unregistered` with no `run_id`; a task
  token on all three → 401/403 as the operator routes answer; a
  `create_app(registrar=None)` application → 503
  `registration_unavailable` on all three.
- `tests/test_openapi_snapshot.py`: regenerated; `tests/api/
  test_schemas.py`: `WorkflowOut` omits `target` when `None`.
- `tests/cli/test_inspect_verbs.py` (or a new `test_workflow_verbs.py`)
  against the served fixture: bare `workflows` unchanged; `add`,
  `reload` (with and without a target), `rm` — output, `--json`, exit
  0; `--persist` prints the path and the row exists afterwards; exit 2
  with `stage: detail` on a load failure; exit 1 on 409 and on 500
  `persist_failed`.

## Verification

```sh
./scripts/test.sh -k "workflows_api or schemas or snapshot or inspect_verbs or workflow_verbs"
uv run scripts/dump_openapi.py && pnpm -C web gen
git diff --exit-code tests/snapshots web/src/api/gen
./scripts/test.sh
```

Then by hand against `./scripts/run.sh`: write `workflows/hello.py`
with a one-node workflow, `athanore workflows add workflows/hello.py:wf`,
`athanore submit hello "first"`, watch it finish; rename the node,
`athanore workflows reload hello`, submit again; `athanore workflows rm
hello` and see `athanore ls` flag the runs.

## Done

- The three routes and three subcommands work against a served
  process with every status 22 §Wire lists and the exact load-failure
  body, `persist` writing the toml row through and reporting it;
  `WorkflowOut.target`; snapshot and client regenerated and committed;
  08, 11, 12, 04 folded; gate green.
