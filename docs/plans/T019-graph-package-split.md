# T019 — Graph package split and node options

**Task.** `docs/v1/17-serial-task-plan.md` § `### T019`.
**Specs.** `docs/v1/04-engine.md` §Graph DSL and §Finalization (the five
checks, verbatim); `docs/v1/02-architecture.md` §Package layout (what
each graph module holds).
**Reference.** v0's `tests/test_graph.py` — its assertions are ported
here, and its ledger row is ticked by this task.

## What this task is

The real graph package. T003 wrote `builder.py` as a faithful port of
v0's flat module; this task splits it into `model.py`, `builder.py`,
`validate.py` and `json.py`, and adds the node options the engine needs.

## What this task is not

- **T020** writes the `Workflow` class. `AthanoreWorkflow` stays as the
  deprecated alias in `graph/__init__.py`.
- No engine. `finalize` validates; nothing here executes.
- `graph` still imports nothing from the rest of `athanore` —
  import-linter enforces it, and every module you add here inherits it.

## Steps

1. `graph/model.py`: frozen `Node` (`name, fn, edges: tuple[str,...],
   payload_param, start, join: bool, priority, retries: int | None,
   timeout: float | None, label, description, generation`) and frozen
   `Graph` (`name, nodes: Mapping[str, Node], start: str`). Frozen is
   the change from T003's mutable `Node`: generations are computed into
   the built graph, not mutated onto it afterwards.
2. `graph/builder.py`: `Transition`, `EdgeRef`, `GraphError`,
   `parse_signature(fn)` (now **public** — the engine and tests use it),
   and `class GraphBuilder(name)` whose `node(...)` takes `start`,
   `priority`, `retries`, `timeout`, `label`, `description`, rejects
   duplicates, records `label or fn.__name__` and `description or
   inspect.getdoc(fn)`, and whose `build() -> Graph` freezes.
3. `graph/validate.py`: `finalize(builder) -> Graph` running the five
   checks of 04 §Finalization, including the name rule
   `^[a-z][a-z0-9_]*$` and the rejection of a `join=True` node with no
   payload slot, plus BFS generations.
4. `graph/json.py`: `jsonable(value)` — pydantic via
   `model_dump(mode="json")`, dataclass via `asdict`, `Transition` to
   dict, fallback `str`. Move existing users onto it.

## Verification

- `tests/graph/test_builder.py` — port v0's `tests/test_graph.py`
  assertions wholesale.
- `tests/graph/test_hypothesis.py` — random DAGs, `max_examples=200`:
  `finalize` never raises on a valid graph; generations equal
  shortest-path depth from start; every unreachable node is reported.
  Generate cycles too: a cycle is legal (the driver's own seat has
  three), so a property test that only makes DAGs proves less than it
  looks.

```sh
./scripts/dev.sh "uv run pytest -q tests/graph"
./scripts/dev.sh "uv run pyright"     # strict on athanore/graph
```

## Done

- Both suites pass; hypothesis at `max_examples=200`.
- `docs/porting-ledger.md` row for `tests/test_graph.py` ticked.
- `**Status.** Done.` on `### T019`, in the same commit.

## Files

```
athanore/graph/{model.py,builder.py,validate.py,json.py,__init__.py}
tests/graph/{test_builder.py,test_hypothesis.py}
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
