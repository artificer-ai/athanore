# T003 — Package skeleton and the graph builder

**Task.** `docs/v1/17-serial-task-plan.md` § `### T003`.
**Specs.** `docs/v1/02-architecture.md` §Package layout (the tree),
§Library choices (the floor); `docs/v1/04-engine.md` §Graph DSL (what the
three rules mean); `AGENTS.md` §Quality bar and §Architecture rules.
**Reference.** v0's `athanore/graph.py` in the sibling checkout
(`$MVP_CHECKOUT`, 157 lines). It is read, never copied from a task's
point of view: write the v1 file fresh, with v0's behaviour as the
acceptance criterion (D65).

## What this task is

The empty package tree of 02 §Package layout, plus one real module: the
graph builder, moved from a flat `graph.py` into `athanore/graph/` with
its behaviour unchanged.

## What this task is not

Do none of this here — each belongs to a later task, and doing it now is
the "narrowed or widened scope" the reviewer rejects:

- **T019** splits `graph/` into `model.py`, `validate.py`, `json.py`,
  adds node options (`join`, `retries`, `timeout`, `label`,
  `description`), the `^[a-z][a-z0-9_]*$` name rule, and the graph test
  suites. T003 leaves `builder.py` holding everything.
- **T020** writes the real `Workflow` class. T003's `workflow.py` is one
  alias line.
- **T004** writes `settings.py`; **T005** writes `logging.py` and the
  `ruff` / `pyright` / `import-linter` config. T003 adds no tool config.
- **T055** writes the public API surface. `athanore/__init__.py` stays
  exactly as T002 left it: empty.
- No engine, store, api, cli or plugin code. Those packages are created
  empty and stay empty.

## Step 1 — the package tree

Create each directory with an `__init__.py` (empty, or a one-line
docstring naming what the package is for — nothing else):

```
athanore/graph/         athanore/store/            athanore/api/
athanore/engine/        athanore/store/repos/      athanore/api/schemas/
athanore/agents/        athanore/store/migrations/ athanore/api/routers/
athanore/requests/      athanore/plugins/          athanore/cli/
athanore/events/        athanore/plugins/builtin/  athanore/testing/
athanore/web/
```

`athanore/web/` holds `dist/.gitkeep` — an empty file that must be
**tracked**. `.gitignore` already carries `athanore/web/dist/` and the
`!athanore/web/dist/.gitkeep` negation (T001), so confirm with
`git check-ignore -v athanore/web/dist/.gitkeep` (it must report nothing)
rather than editing `.gitignore` again.

## Step 2 — `athanore/graph/builder.py`

A faithful reimplementation of v0's `graph.py`. Every name and every
behaviour below must survive, because the engine and the tests written
in later tasks assume them:

- `GraphError(Exception)` — invalid graphs, at finalization or routing.
- `Transition` — frozen dataclass, `target: str`, `payload: Any = None`.
  Serializable: it is what the scheduler persists.
- `EdgeRef` — `__slots__ = ("name",)`; calling it returns
  `Transition(self.name, payload)`; `__repr__` is `<edge NAME>`.
- `Node` — dataclass: `name`, `fn`, `edges: list[str]`, `payload_param:
  str | None`, `start: bool = False`, `priority: int | None = None`,
  `generation: int = 0`.
- `_parse_signature(fn) -> tuple[list[str], str | None]` — the two forms,
  unchanged:
  - with a `/` in the signature, parameters before it are edges and the
    first parameter after it is the payload;
  - without one, positional parameters are edges and a keyword-only
    parameter (after `*`) is the payload;
  - `*args` / `**kwargs` raise `GraphError`.
- `AthanoreWorkflow(name)` with `nodes: dict[str, Node]`:
  - `node(*, start=False, priority=None)` — decorator keyed on
    `fn.__name__`, rejecting a duplicate name with `GraphError`, parsing
    the signature into edges and payload param, returning `fn` unchanged
    so the function stays directly callable;
  - `finalize()` — idempotent, and raises `GraphError` on: not exactly
    one start node; an edge naming a node that does not exist; any node
    unreachable from the start. It sets `generation` on every node to its
    first-reach BFS depth from the start;
  - `start_node() -> Node`.

**One deliberate departure.** v0's `AthanoreWorkflow.run()` (the
Flask-like shorthand that constructs an `AthanoreServer`) is **not**
ported: there is no server in v1 until T031, and T020 reintroduces the
shorthand on `Workflow`. Add the row for this to
`docs/v1/15-decisions.md` — it is a choice the docs did not make.

**Typing.** `pyright` runs strict on `athanore/graph` from T005, so
annotate fully now rather than leaving it for a later task to fix. The
floor is Python 3.11 (D66): no PEP 695 generics, no `@override`.

## Step 3 — `athanore/graph/__init__.py`

Re-export exactly `AthanoreWorkflow`, `EdgeRef`, `GraphError`, `Node`,
`Transition`, with an `__all__`. `graph` imports nothing else from
`athanore` — that is a layering contract import-linter enforces from
T005, and it is the reason this package is written first.

## Step 4 — `athanore/workflow.py`

```python
Workflow = AthanoreWorkflow
```

with a docstring saying the real class arrives in T020, and that this is
the one module allowed to import both `graph` and `plugins.decl` once
those exist.

## Verification

The task's own **Done** condition:

```sh
uv run python -c "import athanore.graph, athanore.engine, athanore.store"
```

Then prove the builder actually builds, which is what QA will ask for:

```sh
uv run python - <<'PY'
from athanore.graph import AthanoreWorkflow, EdgeRef, GraphError, Transition

wf = AthanoreWorkflow("demo")

@wf.node(start=True)
async def a(b, *, payload): ...
@wf.node()
async def b(c): ...
@wf.node()
async def c(): ...

wf.finalize()
assert [n.generation for n in (wf.nodes["a"], wf.nodes["b"], wf.nodes["c"])] == [0, 1, 2]
assert wf.nodes["a"].edges == ["b"] and wf.nodes["a"].payload_param == "payload"
assert wf.start_node().name == "a"
wf.finalize()  # idempotent
assert EdgeRef("b")({"x": 1}) == Transition("b", {"x": 1})

for bad in ("two starts", "no start", "unknown edge", "unreachable node"):
    ...  # build one workflow per case; each must raise GraphError
PY
```

Write those four `GraphError` cases out properly and run them — an
unreachable node and an edge naming a missing node are the two the engine
depends on most.

## Done

- `./scripts/test.sh` green (it still skips pytest, ruff, pyright and
  lint-imports: none of their config exists until T005).
- No new test files. T019 ports `tests/test_graph.py`; adding a graph
  suite now takes T019's work and leaves it half-done.
- A row in `docs/v1/15-decisions.md` for the omitted `run()`.
- `**Status.** Done.` added to `### T003` in
  `docs/v1/17-serial-task-plan.md`, in the same commit.
- One commit on the task's branch, message `T003: ...`.

## Files

```
athanore/{graph,engine,agents,requests,events,store,store/repos,
          store/migrations,plugins,plugins/builtin,api,api/schemas,
          api/routers,cli,testing,web}/__init__.py
athanore/graph/builder.py
athanore/web/dist/.gitkeep
athanore/workflow.py
docs/v1/15-decisions.md
docs/v1/17-serial-task-plan.md
```
