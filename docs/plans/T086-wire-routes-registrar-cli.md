# T086 — Wire: routes, registrar port, CLI verbs

**Task.** `docs/v1/17-serial-task-plan.md` § `### T086`.
**Specs.** `docs/v1/22-live-registration.md` §Wire (the table, the
load-failure body, the registrar port, the security paragraph), §CLI,
§Pools, §Persistence (`persist` on the wire and the CLI), §Reloading a
module (the name check on `PUT`); `docs/v1/08-api.md` §Conventions
(error shape and codes), §Workflows, §OpenAPI; `docs/v1/11-cli.md`
§Verbs, §Exit codes; `docs/v1/12-security.md` §Plugins;
`docs/v1/02-architecture.md` §Package layout, §Layering (the API
imports nothing above its tier); `docs/v1/04-engine.md` §Programmatic
host; D220 (persist only on request), D223 (pool resolution), D227
(`DELETE` answers 200 with a body), D234/D239 (`KeyError` for an
unknown pool, `ValueError` for a pool move in flight), D244 (no header
when no row was touched), D240 (`replace(target=None)` keeps the
recorded target).

## What this task is

The verb reaches the wire. Three routes on the existing workflows
router, the port they call the server through, the error codes they
answer with, `target` on `WorkflowOut`, three CLI subcommands, and the
regenerated contract (OpenAPI snapshot, TypeScript client, docs-site
reference, skills). After this task the chat agent's loop — write,
`POST`, run, edit, `PUT`, run — works over HTTP with no restart.

Everything below the wire exists after T085 and is **not** rebuilt
here: `load_target(target, reload=)` and `LoadError(message, stage,
target, detail, conflict)` in `athanore.plugins.discovery`;
`PersistError(path, detail)`, `write_row`, `remove_row` in
`athanore.plugins.persist`; `Server.add/replace/remove`,
`Server.targets`, `Server._resolve_pool` (raises `KeyError` naming the
known pools), `Server._refuse_move_in_flight` (raises `ValueError`),
`Server._persist_row`; the three `workflow.*` events. Read
`athanore/server.py` §registration and `athanore/plugins/discovery.py`
before writing a line: the port is a thin adapter over what is there.

### The port

1. **`athanore/api/registrar.py`** (new; add the line to 02 §Package
   layout under `api/`):

   ```python
   class WorkflowRegistrar(Protocol):
       async def add_target(self, target: str, pool: str | None, *, persist: bool) -> Registered: ...
       async def reload_target(self, name: str, target: str | None, pool: str | None, *, persist: bool) -> Registered: ...
       async def remove(self, name: str, *, persist: bool = False) -> RemovedWorkflow: ...
       @property
       def targets(self) -> Mapping[str, str | None]: ...
   ```

   `Registered` and `RemovedWorkflow` are imported from
   `athanore.plugins.discovery` — it sits in no tier and imports only
   `athanore.workflow` (D242), so the API may name it; the API may not
   import `athanore.server`, and does not need to. `remove` and
   `targets` already have exactly this shape on `Server`; the two
   `*_target` coroutines are new.

2. **`Server` implements it** (`athanore/server.py`, beside `remove`).
   The port methods are adapters: load, check, hand over to the
   existing verb, and let its refusals through unchanged.
   - `add_target(target, pool, *, persist)`: `wf = load_target(target,
     reload=True)`; `return await self.add(wf, pool, target=target,
     persist=persist)`. `reload=True` on a `POST` because a target
     `POST`ed after a `DELETE` of the same name is the second load of
     it in this process, and the caller expects the file as it is now —
     on a first load the purge finds nothing and is a no-op (22
     §Reloading a module; **decision**, record it).
   - `reload_target(name, target, pool, *, persist)`: `name not in
     self._workflows` → `LoadError(stage="register", target="",
     detail=...)` as `remove` raises (the router 404s first; this is for
     a programmatic caller). `resolved = target if target is not None
     else self._targets[name]`; `None` → `LoadError("workflow 'x' has no
     recorded target to reload; give one", stage="target", target="",
     detail=<same>)` (22 §Wire: `stage: "target"` "there is no recorded
     target to reload"). `wf = load_target(resolved, reload=True)`. **Then
     the name check, before anything else touches the server**: `wf.name
     != name` → `LoadError(f"{resolved} names workflow {wf.name!r}; PUT
     /api/workflows/{name} is for {name!r} — POST it", stage="register",
     target=resolved, detail=<same>, conflict=True)`. Without this check
     `Server.replace` would swap the *other* registered workflow if
     `wf.name` happens to be registered too. Then `return await
     self.replace(wf, pool, target=resolved, persist=persist)` —
     `target` passed explicitly, so D240's `None` never reaches
     `replace` from the wire.
   - `remove` is `Server.remove` as it stands.
   - Every `LoadError` a port method raises or lets through is logged
     at ERROR with `target`, `stage` and the traceback (`exc_info=True`)
     before it propagates — 22 §Wire: the traceback is in the server
     log, never on the wire. One `try/except LoadError` per port
     method; the ordinary verbs are untouched.
   - Widen `LoadError.conflict`'s docstring: set by `Server.add` on a
     registered name **and by `reload_target` on a target whose
     workflow is not the one in the URL**; both are the wire's 409.
   - `Server.start` passes `registrar=self` to `create_app`.

3. **`UnknownPool`** (`athanore/plugins/discovery.py`, beside
   `LoadError`): `class UnknownPool(KeyError)` with `pool: str` and
   `known: tuple[str, ...]`, `str(exc)` the sentence `_resolve_pool`
   already builds ("no pool named 'x'; known pools are [...]").
   `Server._resolve_pool` raises it instead of a bare `KeyError`. It
   *is* a `KeyError`, so D234/D239 and
   `tests/test_server.py::test_an_unknown_pool_name_is_a_key_error_naming_the_known`
   hold unchanged; the router gets a type to catch instead of a message
   to parse. **Decision**: the type lives in `discovery`, not the
   engine (no engine change — the engine's own `KeyError` for a pool
   that vanished between the server's check and the engine's cannot
   happen, pools are never removed).

4. **`create_app(..., registrar: WorkflowRegistrar | None = None)`**
   (`athanore/api/app.py`): stored as `app.state.registrar`. `None` →
   the three routes answer `503 registration_unavailable` ("this
   application was built without a registrar; workflows cannot be
   registered over the API"). The OpenAPI dump and the ASGI test
   fixture build without one. Update the docstring and 02 §Package
   layout's `create_app(...)` line.

### The routes (`athanore/api/routers/workflows.py`)

5. Three routes, under the router's existing `operator_auth`, tagged
   `workflows` like the rest (the existing
   `test_every_route_is_tagged_for_the_generated_client` and
   `test_the_operator_dependency_guards_every_route` cover them):
   - `POST /api/workflows` body `RegisterWorkflow` → **201**
     `WorkflowOut`.
   - `PUT /api/workflows/{name}` body `ReloadWorkflow` → **200**
     `WorkflowOut`.
   - `DELETE /api/workflows/{name}?persist=false` → **200**
     `RemovedWorkflowOut`.

   Each takes `response: Response` and sets
   `X-Athanore-Persisted: <path>` when the verb's `persisted` is not
   `None` (`PERSISTED_HEADER: Final` spelled once in the router; D244
   means `DELETE` of a name with no row sends none). No per-route
   `responses=` declarations — the router declares none for its
   existing 404/409s and the snapshot test
   `test_every_declared_refusal_carries_that_shape` is satisfied by
   the router-level 401/422; the header and the statuses are documented
   in the route docstrings (which are the OpenAPI descriptions) and in
   08.

   `PUT` and `DELETE` call `_graph(request, name)` **before** the port,
   so an unregistered name is the existing 404 `unknown_workflow` and
   never reaches the loader. The success body of `POST`/`PUT` is
   `_view(request, _graph(request, registered.name))` — the same object
   `GET` gives, read back off the engine after the verb.

6. **Request and response models** (`athanore/api/schemas/bodies.py`
   for the two bodies, `schemas/workflows.py` for the response; export
   all three from `schemas/__init__`):
   - `RegisterWorkflow {target: Text, pool: str | None = None, persist:
     bool = False}` — `Text` is the module's stripped non-empty string.
   - `ReloadWorkflow {target: Text | None = None, pool: str | None =
     None, persist: bool = False}`.
   - `RemovedWorkflowOut {workflow: str, task_ids: list[int]}` — 22
     §Wire's `{workflow, task_ids}`; `persisted` is deliberately not a
     field (the header is the receipt).

7. **Mapping**, in one helper beside the routes — a context manager
   `_mapping_refusals()` wrapping each port call, whose `except`
   clauses raise `ApiError` (`_registering(request)` is the port lookup
   that 503s without one):
   - `LoadError` with `conflict` → **409** `conflict`, body `{error,
     code}` (`error` is `exc.message`).
   - other `LoadError` → **422** `workflow_load_failed`, body
     `{error: exc.message, code, target: exc.target, stage: exc.stage,
     detail: exc.detail}` — the exact shape of 22 §Wire, nothing more.
   - `UnknownPool` → **422** `unknown_pool`, body `{error, code}`; the
     message names the known pools. No `known` list in the body — the
     brief rules pool listing out of the extras, and 22 §Pools asks only
     that the answer *name* them.
   - `ValueError` (from `Server._refuse_move_in_flight` or the engine's
     own check, both "pool move with attempts in flight"; `persist`
     without a target cannot reach here — every port call has one) →
     **409** `conflict`, `{error, code}`.
   - `PersistError` → **500** `persist_failed`, body `{error, code,
     path: str(exc.path), detail: exc.detail}`; `error` says nothing
     changed ("… was not updated and the registration was not changed:
     …") — one wording for `POST`, `PUT` and `DELETE` — because T085
     orders the write before the mutation.

   **Decision**: the mapping lives in the router, not in
   `DOMAIN_ERRORS`: `ValueError` is too broad for a global handler, and
   the 409-or-422 split on `LoadError` is a fact about these three
   routes. `athanore.api.errors` stays unaware of `plugins.discovery`
   and `plugins.persist` (both are outside the layers contract, so the
   router importing them is an ordinary arrow).

8. **`ErrorCode`** gains `workflow_load_failed`, `unknown_pool`,
   `registration_unavailable`, `persist_failed`, appended in that order
   (the snapshot test asserts the enum is `ErrorCode`'s members in
   declaration order; the TypeScript union follows from the
   regeneration — `web/src/components/answer.ts` types
   `CONFLICT_CODES` as `readonly ErrorCode[]`, which an additive change
   cannot break).

9. **`WorkflowOut.target: str | None = Field(default=None, ...)`**,
   description "The target this workflow was loaded from
   (`module:attr` or `path.py:attr`); `null` for a programmatic
   registration." `WorkflowOut.of(...)` takes `target: str | None =
   None`; `_view` reads it from `request.app.state.registrar.targets`
   when there is a registrar and passes `None` otherwise. **Decision**:
   `null`, not omitted. 22 §Terms says "absent when there is none", and
   on this API's REST models that is spelled `null` — `RunStats.cost`,
   `LogEntry.kind` and `NodeOut.description` all say "absent" in prose
   and send `null` on the wire; the omit-when-`None` machinery is
   `EventModel`'s and belongs to the event stream (18). Making one
   field of one REST model omit itself would need the
   `__get_pydantic_json_schema__` dance of `events/payloads.py` for a
   distinction no client can act on.

### The CLI

10. **`athanore/cli/workflows.py`** (new). `workflows_app =
    typer.Typer(name="workflows", invoke_without_command=True,
    help=...)`, added with `app.add_typer(workflows_app,
    name="workflows")`, imported at the bottom of `athanore/cli/
    __init__.py` beside the other verb modules. The `workflows` verb
    **moves** here from `inspect.py` as the group's callback
    (`@workflows_app.callback(invoke_without_command=True)`), returning
    at once when `ctx.invoked_subcommand` is set and printing the table
    as today otherwise — `tests/cli/test_inspect_verbs.py::
    test_workflows_shows_each_graph_and_its_pool` must pass untouched.
    `NODES` and `_node_row` move with it; `_mappings`/`_mapping` in
    `inspect.py` become public (`mappings`, `mapping`, in `__all__`) so
    the new module imports them without reaching for a private name;
    drop `workflows` and `NODES` from `inspect.__all__`. `RESERVED` is
    unchanged: `add`, `reload`, `rm` are subcommands, not verbs.

11. The three subcommands, thin clients of the routes:
    ```
    athanore workflows add <target> [--pool NAME] [--persist]
    athanore workflows reload <name> [<target>] [--pool NAME] [--persist]
    athanore workflows rm <name> [--persist]
    ```
    - `add` → `POST /api/workflows {target, pool, persist}`; `reload`
      → `PUT /api/workflows/{name} {target, pool, persist}` (`target`
      omitted from the body when not given, so the server re-resolves
      the recorded one); `rm` → `DELETE /api/workflows/{name}?persist=`.
    - Output. `add`/`reload` print the `WorkflowOut` exactly as the
      table verb prints one entry (extract the per-entry rendering into
      a function both use); the entry line gains ` target=<t>` **only
      when `target` is not `null`**, so programmatic fixtures render as
      before. `rm` prints the interrupted task ids one per line, nothing
      when there were none. `--json` prints the body, whole.
    - The receipt. When the response carries `X-Athanore-Persisted`,
      the verb prints `persisted to <path>` (`add`, `reload`) or
      `removed from <path>` (`rm`) as its last line — on stdout in table
      mode, on **stderr** under `--json` so stdout stays the API's own
      JSON (**decision**).
    - Exit codes. `workflow_load_failed` → `fail(message, [f"{stage}:
      {detail}"])` and exit **2** (`EXIT_USAGE`; 22 §CLI, 11 §Exit
      codes). `unknown_pool` → `fail(message)` and exit **2** — 22
      §Pools prices it as the toml binding `athanore serve` refuses at
      2 (**decision**). Everything else (`conflict`, `persist_failed`,
      `unknown_workflow`, 401) stays the `ApiClientError` path of
      `dispatch`: message and exit 1. Implement as one `except
      ApiClientError` helper the three verbs share that re-raises
      anything it does not price.

12. **`athanore/cli/client.py`**: the receipt is a header and
    `Client.request` returns the decoded body only. Add `Reply(body,
    headers)` (frozen dataclass; `headers: Mapping[str, str]`) and
    `Client.exchange(method, path, *, params=None, body=None) -> Reply`;
    `request` becomes `exchange(...).body`. Add `Client.put(...)`
    beside `patch`. Nothing else in the client changes.

### The contract, the generated pages, the folds

13. Regenerate and commit, in this order: `uv run
    scripts/dump_openapi.py && pnpm -C web gen` (snapshot + client);
    `uv run scripts/gen_docs.py` (`docs/site/src/reference/cli.md`,
    `errors.md`, `http-api.md` change); `uv run scripts/gen_skills.py`
    (the skills' `reference/` copies, incl.
    `skills/athanore-api/reference/openapi.json`). The gate's
    `tests/test_openapi_snapshot.py`, `tests/test_docs_site.py` and
    `tests/test_skills.py` fail on any of the three being stale. Add
    `registrar=None` to
    `tests/test_api_app.py::test_create_app_takes_the_published_signature`.

14. Narrative for the site (hand-written pages; no RFC 2119 keywords,
    no `docs/v1` path — `tests/_prose.py` checks): `docs/site/src/guide/
    cli.md` §The verbs gains the three lines and a short paragraph
    (what each does, `--persist`, exit 2 on a load failure);
    `docs/site/src/guide/workflows.md` gains a paragraph after T085's
    "Registration does not stop when serving starts" saying the same
    three verbs are `POST`/`PUT`/`DELETE /api/workflows` and `athanore
    workflows add|reload|rm`, with the `workflow_load_failed` body's
    `stage` as the thing to read.

15. Folds into the spec (each pointing at 22):
    - 08 §Conventions: the four codes in the list; a sentence on the
      `workflow_load_failed` body (`target`, `stage`, `detail`) and the
      `persist_failed` extras (`path`, `detail`); 503 in the status
      list. §Workflows: the three rows exactly as 22 §Wire's table,
      `target?` added to the `GET` row's shape, and the
      `X-Athanore-Persisted` sentence.
    - 11 §Verbs: the three subcommand lines in the block and a
      paragraph (exit 2 on `workflow_load_failed`/`unknown_pool`
      printing `stage` and `detail`; `rm` prints the ids; a persisting
      verb prints the path).
    - 12 §Plugins: 22 §Wire's paragraph — the routes execute Python the
      caller named, are operator routes behind `operator_auth`, and are
      never on the agent surface.
    - 02 §Package layout: `api/registrar.py` and the `create_app`
      signature. 04 §Programmatic host: one sentence — `Server`
      implements `athanore.api.registrar.WorkflowRegistrar`, so the
      process `athanore serve` runs accepts the same three verbs over
      `/api/workflows`.
    - 15: one row per **decision** above (D248 onward: `UnknownPool` as
      a `KeyError` in `discovery`; `target` is `null` for a programmatic
      registration; `add_target` loads with `reload=True`; the
      route-local mapping; `unknown_pool` exits 2 and the `--json`
      receipt goes to stderr).
    - 17: `**Status.** Done.` on T086, same commit.

## What this task is not

- No SPA change outside `web/src/api/gen`: the invalidation rows and the
  stale-assets notice are T087.
- No UI for registering, no library-overlay button.
- No persistence beyond passing `persist` through to T085's verbs
  (D220): the toml writer is `plugins.persist`'s. No pool creation, no
  pool list in error bodies, no watcher (D222).
- No change to the engine, the plugin host, the loader or the
  programmatic `register`/`add`/`replace`/`remove` contracts beyond
  `UnknownPool` (a `KeyError` subclass) and the `LoadError.conflict`
  docstring; a gap found here is fixed on this branch and noted in the
  owning plan.
- No new top-level verb; `RESERVED` and the shorthand `athanore
  <workflow> "title"` are untouched.
- No Playwright (T087).

## Tests

- **`tests/api/test_registration_api.py`** (new). Its own fixtures: a
  `Server` on `port=0` with `root_path=tmp_path` (so `athanore.toml`
  is `tmp_path / "athanore.toml"`), started and stopped per test, an
  `httpx.AsyncClient(base_url=server.url)`; a `write_target(tmp_path,
  stem, name, node)` helper writing a one-node file target; a parked
  variant whose node `await asyncio.sleep(3600)`s for the in-flight
  cases; the `restore_imports` and `sources_are_never_written` autouse
  fixtures as `tests/test_server.py` has them (copy, do not import a
  test module); every wait bounded by `asyncio.timeout`. Cases, one
  test each unless noted:
  - `POST` → 201, body is `GET /api/workflows/{name}` byte-for-byte and
    carries `target`; the name is then in the list.
  - `POST` the same target again → 409 `conflict`; the registry is
    unchanged.
  - The `workflow_load_failed` body per stage, parametrised: not
    `where:attr` (`target`); a missing file and a file that raises at
    import (`import`); no such attribute, and an attribute that is not a
    `Workflow` (`attribute`); a graph that does not finalize
    (`finalize`); a panel naming a missing node (`plugins`); a workflow
    named after a verb (`register`). Assert the exact key set `{error,
    code, target, stage, detail}` and each value.
  - `POST` with `pool: "nope"` → 422 `unknown_pool`, message names the
    known pools, body is `{error, code}` only; `pool` naming a real one
    binds to it (`WorkflowOut.pool`).
  - `PUT` after rewriting the file (rename the node) → 200, the node
    set changed, `GET .../source` shows the new text.
  - `PUT` with no `target` on a workflow registered programmatically →
    422 `stage: "target"`; on a loaded one → 200 (re-resolves the
    recorded target).
  - `PUT` whose target now defines another name → 409 `conflict`, and
    the other name (registered or not) is untouched.
  - `PUT` with a pool move while an attempt is mid-node → 409; after
    the run finishes (or is cancelled) → 200 and `pool` moved.
  - `DELETE` while a parked attempt is mid-node → 200 `{workflow,
    task_ids: [id]}`, the run then reads `unregistered: true`; `POST` it
    back → the run completes.
  - `DELETE` unknown → 404 `unknown_workflow`; `PUT` unknown → 404.
  - `persist: true` on `POST` and `PUT`, and `?persist=true` on
    `DELETE`, against a fixture `athanore.toml` with a comment and an
    unrelated row: exactly the one row changes, the rest is
    byte-identical, the response carries `X-Athanore-Persisted` equal to
    the file's path; `persist` omitted changes nothing and sends no
    header; `DELETE ?persist=true` of a name with no row sends no
    header (D244).
  - A read-only `athanore.toml` → 500 `persist_failed` with `path` and
    `detail`, and `GET /api/workflows` unchanged (nothing registered;
    for `PUT`, the old node set still there).
  - `GET /api/events?after=0&names=workflow.*` carries
    `workflow.registered`, `workflow.replaced`, `workflow.unregistered`
    in order, each with no `run_id` (read the stream as
    `tests/api/test_sse.py` does).
  - Auth: a server with `require_token=True` and a token file — a
    request with only `X-Athanore-Token` (any value) is 401 on all
    three; the bearer token is accepted.
- **`tests/api/test_workflows_api.py`** (existing, ASGI app with no
  registrar): the three routes → 503 `registration_unavailable`; a
  programmatic registration's `WorkflowOut` has `target: null`.
- **`tests/api/test_schemas.py`**: `WorkflowOut.of(..., target=None)`
  dumps `target: None`; with a target, the string.
- **`tests/test_server.py`**: `add_target`/`reload_target` at the
  server level — the `stage: "target"` refusal, the name-mismatch
  `LoadError` with `conflict=True` leaving both registrations
  untouched, `reload_target(name, None, ...)` re-resolving the recorded
  target, `_resolve_pool` raising `UnknownPool` (still caught by the
  existing `KeyError` test).
- **`tests/cli/test_client.py`**: `Client.exchange` returns the body
  and the headers; `put` sends `PUT`.
- **`tests/cli/test_workflow_verbs.py`** (new), on the `cli`/`server`
  fixtures of `tests/cli/conftest.py` plus the two autouse fixtures
  above: bare `workflows` unchanged; `add <target>` prints the entry
  (with `target=`) and exit 0, `--json` is the `WorkflowOut`; `add`
  again → exit 1 with the conflict message on stderr; `add` of a broken
  file → exit 2, stderr carries the message and `stage: detail`; `add
  --pool nope` → exit 2 naming the known pools; `reload <name>` with
  and without a target after editing the file; `rm <name>` prints the
  interrupted id(s) one per line (a parked run) and nothing for a quiet
  workflow; `--persist` on each prints `persisted to <path>` /
  `removed from <path>` and the row exists / is gone afterwards; under
  `--json` the receipt is on stderr and stdout parses; a read-only toml
  → exit 1 with `persist_failed`'s message.
- **`tests/test_openapi_snapshot.py`**, **`tests/test_docs_site.py`**,
  **`tests/test_skills.py`**: regenerated artefacts match; the new
  codes are in the `ErrorCode` enum.

## Verification

```sh
./scripts/test.sh -k "registration_api or workflows_api or schemas or snapshot or workflow_verbs or inspect_verbs or test_client or test_server"
uv run scripts/dump_openapi.py && pnpm -C web gen && uv run scripts/gen_docs.py && uv run scripts/gen_skills.py
git diff --exit-code tests/snapshots web/src/api/gen docs/site/src/reference skills
./scripts/test.sh
```

Then by hand against `./scripts/run.sh`: write `workflows/hello.py`
with a one-node workflow, `athanore workflows add workflows/hello.py:wf
--persist`, `athanore submit hello "first"`, watch it finish; rename
the node, `athanore workflows reload hello`, submit again; `athanore
workflows rm hello --persist` and see `athanore ls` flag the runs and
the row gone from `athanore.toml`.

## Done

- The three routes and three subcommands work against a served
  process with every status 22 §Wire lists and the exact load-failure
  body; `persist` writes the toml row through T085's verbs and the
  response reports it in `X-Athanore-Persisted`; `WorkflowOut.target`;
  snapshot, client, site reference and skills regenerated and
  committed; 02, 04, 08, 11, 12, 15, 17 folded; gate green.
