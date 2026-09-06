# T005 — structlog and the tooling gate

**Task.** `docs/v1/17-serial-task-plan.md` § `### T005`.
**Specs.** `docs/v1/02-architecture.md` §Library choices, §Package
layout (the layering the contracts encode); `AGENTS.md` §Architecture
rules §Layering.

## What this task is

`athanore/logging.py`, plus the three tool configs that turn
`./scripts/test.sh` into the real gate. From this commit onward every
later task is checked by `ruff`, `pyright` and `lint-imports` — so this
is the task that decides what "green" means for the rest of the build.

## What this task is not

- No `scripts/gate.sh` yet unless the task names it: `test.sh` already
  delegates to it *if it exists*, so adding one changes the gate's shape.
  If you add it, it must run exactly the documented set.
- No logging calls inserted anywhere else. `configure_logging` is called
  by the server in T031 and the CLI in T011; nothing calls it here.
- No fixing of unrelated code beyond what the new linters demand.

## Steps

1. `athanore/logging.py`:
   - `configure_logging(fmt: str | None)` — pretty `ConsoleRenderer`
     when `fmt is None and sys.stderr.isatty()`, JSON otherwise;
   - `bind_attempt(run_id, task_id, node, workflow, attempt)` as a
     context manager over `structlog.contextvars`;
   - `get_logger(name)`;
   - route stdlib `logging` (uvicorn, alembic, sqlalchemy) through
     structlog, so one process has one log format.
2. `[tool.ruff]`: `line-length = 88`, `select = ["E","F","I","UP","B","ASYNC"]`.
3. `[tool.pyright]`: `typeCheckingMode = "standard"`,
   `strict = ["athanore/graph", "athanore/engine", "athanore/store"]`.
4. `[tool.importlinter]`: the layers contract and the three forbidden
   contracts exactly as the task lists them.

## The decision this task has to make

`uv run ruff check .` runs from the repository root, so it sees
`driver/` and `scripts/` — dev machinery that targets **v0's** API, not
v1's, and that no task may make `athanore/` depend on. Decide once, and
record it in `docs/v1/15-decisions.md`: either lint it with everything
else, or `extend-exclude` it. The boring choice is to lint it (it is
Python in this repository and it is held to the same bar) and fix
whatever the first run reports. Do not leave it unstated — the next task
inherits whichever it is.

## Verification

```sh
./scripts/dev.sh "uv run ruff check . && uv run ruff format --check ."
./scripts/dev.sh "uv run pyright"
./scripts/dev.sh "uv run lint-imports"
```

All three must pass on the tree as it stands (the subpackages T003
created are empty, so the layering contracts pass trivially; that is
expected and still worth seeing). Then confirm the gate itself picked
them up: `./scripts/test.sh` must no longer print them in its
`skipped:` line.

Prove the logger both ways, since the isatty branch is easy to get
backwards:

```sh
./scripts/dev.sh "uv run python -c \"
from athanore.logging import configure_logging, get_logger
configure_logging('json'); get_logger('t').info('hello', run_id='r1')\""
```

## Done

- ruff, ruff format, pyright and lint-imports green, and named by
  `./scripts/test.sh` as run rather than skipped.
- A row in `docs/v1/15-decisions.md` for the `driver/` lint decision.
- `**Status.** Done.` on `### T005`, in the same commit.

## Files

```
athanore/logging.py
pyproject.toml
docs/v1/15-decisions.md
docs/v1/17-serial-task-plan.md
```
