# 17 — Serial task plan

The tickets in 16 are PR-sized and may run in parallel inside a phase.
This document flattens them into **one serial sequence** of small tasks
(a few hours to one day each) that a single implementer, or one agent at
a time, can execute top to bottom without ever having two half-finished
things at once. Every task names the doc 16 ticket it belongs to, the
files it touches, the tests it adds, and the condition that ends it.

Section references (`04 §Waiting`) point at the spec that is the
acceptance criterion. Where a task adds a detail the design left implicit
(a lock, a data structure, a fixture strategy), that detail is written
here so it is decided once.

## Working rules for the whole sequence

- **Everything runs in the dev stack**, which lives in this repository,
  not the separate `athanore-build` repo T000 described (D64): one image
  (`docker/dev/`) behind the `dev` shell, the `app` server and both ACP
  agents, plus an `orchestrator` running athanore **v0** (the sibling
  checkout, tagged `v0.0.12`) that dispatches each task below to the
  sandbox and shows progress in the v0 browser TUI (D67). Humans, v0 and
  v1 all reach it through the same `scripts/` wrappers — `./scripts/
  test.sh`, `./scripts/agent.sh` — so a green gate means the same thing
  on every machine and for every caller. Each task is built on its own
  branch, `feat/<task-id>`, and merged `--no-ff` onto `main` once the
  gate, the review and QA have passed (D68).
- **Clean slate: no code moves from v0.** This repository holds no MVP
  code (D65). v0 is the neighbouring `athanore` checkout, tagged
  `v0.0.12`, and it is read as the behavioural specification — never
  copied, never moved from. Where a task below says `git mv`, "port",
  "delete the MVP module", or "the existing suite still passes", read it
  as: **write it fresh in the v1 layout, with the named v0 file as the
  reference for behaviour.** Nothing is moved into this repository, and
  nothing is deleted from it that was never in it.
- **Ported test = ticked ledger row.** "Port `tests/test_x.py`" means
  write the v1 test covering what that file covered, then tick its row in
  `docs/porting-ledger.md`. A **Done** block that says an MVP test file is
  "deleted" means its ledger row is ticked.
- New code lives only in the subpackages of 02 §Package layout.
  `athanore/__init__.py` becomes the v1 surface of 02 §Public API surface
  in T055.
- **One commit per task**, on the task's branch, message prefixed with
  the task id (`T012:`).
  Each commit leaves `uv run pytest`, `ruff`, `pyright`, and
  `lint-imports` green from T005 onward, and `pnpm typecheck` green from
  T008 onward.
- **Definition of done** is 13 §Definition of done: tests at the lowest
  layer that can express the behaviour; `tests/snapshots/openapi.json`
  regenerated if the wire changed; a row in 15 if a choice was made; the
  relevant document updated; and a `**Status.** Done.` line on the task
  here, in the same commit, so this document says where the build is.
- **Phase gates.** The last task of each phase is a checkpoint: the
  examples run on `FakeACPAgent` through `ATHANORE_AGENT_COMMAND` and
  per-node scenarios (13 §Running examples on the fake; from T037
  onward) and CI is green.

---

## Phase 0 — Scaffold

### T000 — Dev stack and driver seat (done by hand, in this repository)

Why first: T001–T079 are executed by dispatching each one as a run of
athanore **v0** — the sibling checkout, tagged `v0.0.12` — to a pi agent
in a Docker sandbox, reviewed from the v0 browser TUI.

This task was written here as a **separate `athanore-build` repository**
built around a `v1` worktree, with its own `docker/sandbox` image and a
`submit_plan.py`. It was built differently, and what exists is the
specification now:

- The dev stack lives in this repository, not a second one (D64):
  `compose.yaml`, `docker/dev/` (one image behind `dev`, `app`, `web` and
  both ACP agents), `docker/orchestrator/` (v0's own image and venv), and
  the `scripts/` wrappers, which do the same thing on the host and in the
  container.
- There is no worktree and no `v1` branch (D65). Work is on `main`, one
  `feat/<task-id>` branch per task, merged `--no-ff` (D68).
- The driver is `driver/`, written against v0's API and pinning v0 by
  path. It dispatches through `./scripts/agent.sh` and gates through
  `./scripts/test.sh`, so `compose.yaml` is the one definition of the
  sandbox for humans, for v0, and for v1 after the port (D67). It listens
  on 4102; the v1 app owns 4002.
- The seat is `driver/athanore_build/feature.py`: `prepare → implement →
  gate → review → qa → approve → merge`, three models, five deterministic
  nodes, per-lane loop caps, and a queue that pauses behind a failure
  (D68). Submitting a run is one `POST /api/workflows/v1_feature/runs`,
  wrapped by `./scripts/drive.sh submit <task-id>`.

`AGENTS.md` §Commands is the operating manual for all of it and is kept
current. Read it, not this section, for how the stack works.

**Status.** Done by hand. The pre-D68 seat was proven end to end (a
throwaway run went implement → gate → review → done, committing
`84da1f3` as `athanore-builder`); the current seat is exercised for the
first time by T003.

### T001 — Repository hygiene for the v1 branch (14 §Repository changes)

**Do.** The findings the docs cited from git-ignored files are folded into
20 (D59), so nothing here depends on un-ignoring history. Add to
`.gitignore`: `.athanore/`, `athanore/web/dist/` with
`!athanore/web/dist/.gitkeep`, `web/node_modules/`, `web/dist/`,
`web/test-results/`, `web/playwright-report/`. Add `docs/porting-ledger.md`:
a table of the MVP's 25 test files → target v1 test file, all unticked,
`test_tui.py` marked retired; later tasks tick rows as they port (the
"ported test = ticked ledger row" rule above is how a row gets ticked).
Mark 15 open question 4 as closed by D59 in this branch.
**Done.** `git status` clean after a `pnpm build` and an `athanore token
rotate`; the ledger lists every file under `tests/`.
**Status.** Done, `91683da`.

### T002 — `pyproject.toml` for v1 (A0.4 part, 14 §Repository changes)

**Do.** Version `1.0.0a0`. Dependencies: keep `agent-client-protocol>=0.12,<0.13`,
`fastapi`, `httpx`, `pydantic>=2.7`, `uvicorn`; add
`sqlalchemy[asyncio]>=2.0`, `aiosqlite`, `alembic`, `sse-starlette`,
`pydantic-settings`, `structlog`, `typer`, `rich`, `python-ulid`.
No `textual`, `netext` or `textual-dev`: nothing here imports them and
the TUI stays in v0, retiring with it (D65, D67, D13).
`[project.optional-dependencies] postgres = ["asyncpg"]`.
`[dependency-groups] dev`: `pytest`, `pytest-asyncio` (mode `auto`),
`hypothesis`, `respx`, `freezegun`, `ruff`, `pyright`, `import-linter`,
`pip-audit`.
`[tool.uv.workspace] members = ["examples"]`; create
`examples/pyproject.toml` (name `athanore-examples`, depends on
`athanore` via `[tool.uv.sources] athanore = { workspace = true }`,
empty package for now).
Hatch: `[tool.hatch.build.targets.wheel] packages = ["athanore"]`,
`artifacts = ["athanore/web/dist/**"]`.
`[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]`.
**Done.** `uv sync --all-groups --all-extras` resolves; `uv.lock`
committed.
**Status.** Done, `21735e7` (with D65's departures: no `textual`,
`netext` or `textual-dev`, and `main.py` deleted).

### T003 — Package skeleton and the graph move (A0.1)

**Do.** Create packages with `__init__.py`: `athanore/graph`,
`engine`, `agents`, `requests`, `events`, `store`, `store/repos`,
`store/migrations`, `plugins`, `plugins/builtin`, `api`, `api/schemas`,
`api/routers`, `cli`, `testing`, `web` (with an empty `dist/.gitkeep`
that is **not** ignored: add `!athanore/web/dist/.gitkeep`).
Write `athanore/graph/builder.py` fresh, with v0's `athanore/graph.py`
as the behavioural reference — the three rules and the signature parsing
are unchanged, so this is a faithful reimplementation, not a redesign.
`athanore/graph/__init__.py` re-exports `AthanoreWorkflow, EdgeRef,
GraphError, Node, Transition`. Create `athanore/workflow.py` with
`Workflow = AthanoreWorkflow` for now (the real class arrives in T020).
**Done.** `python -c "import athanore.graph, athanore.engine,
athanore.store"` works.
**Status.** Done.

### T004 — `AthanoreSettings` (A0.2)

**Do.** `athanore/settings.py`: `class AthanoreSettings(BaseSettings)`
with `model_config = SettingsConfigDict(env_prefix="ATHANORE_",
toml_file="athanore.toml", extra="ignore")`; override
`settings_customise_sources` to order init kwargs (CLI) > env > TOML >
defaults, TOML path resolved against `root_path`. Fields and defaults from
02 §Configuration: `root_path: Path = cwd`, `db_url: str | None`
(computed default `sqlite+aiosqlite:///{root}/athanore.db`), `host`,
`port`, `public_url: str | None` (default `http://{host}:{port}`),
`operator_token: SecretStr | None`, `require_token: bool`, `body_limit:
int = 1_048_576`, `sse_replay_cap: int = 5000`, `workers: int = 1`,
`max_retries: int = 3`, `agent_timeout: float = 10800`,
`permission_policy: Literal[...] | None`, `cors_origins: list[str]`,
`log_format: Literal["pretty","json"] | None`, `stream_flush_interval:
float = 0.4`, `run_migrations: bool = True`, `forwarded_allow_ips: str |
None`, `retention: Retention` (`events_days=30`, `stream_days=14`).
Properties: `is_loopback` (`ipaddress.ip_address(host).is_loopback` or
`host == "localhost"`), `token_file` (`root/.athanore/token`),
`effective_operator_token` (setting, else file contents if it exists).
Legacy shim: read `ARTIFICER_PORT`, `ARTIFICER_DB`, `ARTIFICER_HOST` when
the `ATHANORE_` name is unset and emit `DeprecationWarning`.
**Tests.** `tests/test_settings.py`: precedence (kwargs > env > toml),
computed `db_url` and `public_url`, `is_loopback` for `127.0.0.1`,
`::1`, `localhost`, `0.0.0.0` (false), legacy env warning.
**Done.** Tests pass; `AthanoreSettings()` with no env or file yields the
documented defaults.
**Status.** Done.

### T005 — structlog and tooling config (A0.3, A0.4)

**Do.** `athanore/logging.py`: `configure_logging(fmt: str | None)` (pretty
`ConsoleRenderer` when `fmt is None and sys.stderr.isatty()`, else
JSON), `bind_attempt(run_id, task_id, node, workflow, attempt)` context
manager using `structlog.contextvars`, `get_logger(name)`. Route stdlib
`logging` (uvicorn, alembic, sqlalchemy) through structlog.
`[tool.ruff]`: `line-length = 88`, select `E,F,I,UP,B,ASYNC`.
`[tool.pyright]`: `typeCheckingMode = "standard"`, `strict =
["athanore/graph", "athanore/engine", "athanore/store"]`.
`[tool.importlinter]`: layers contract
`athanore.api | athanore.cli | athanore.plugins.builtin` over
`athanore.engine | athanore.requests | athanore.agents | athanore.plugins.registry | athanore.plugins.decl | athanore.plugins.mount`
over `athanore.store | athanore.events | athanore.graph | athanore.settings | athanore.logging`;
forbidden contracts: `athanore.graph` may import nothing from `athanore`;
`athanore.agents` may not import `athanore.store`; `athanore.store` may
not import `athanore.engine`. No `ignore_imports` escape hatch is
needed: there are no MVP flat modules in this repository (D65).
**Done.** `ruff check .`, `pyright`, `lint-imports` green (empty
subpackages trivially pass).
**Status.** Done.

### T006 — CI workflow (A0.5)

**Do.** `.github/workflows/ci.yml`: job `python` (uv sync, ruff, pyright,
lint-imports, pytest with `--cov`) over a `python-version` matrix of
`3.11`, `3.12`, `3.13` so the supported floor is tested and not just
declared (D66); ruff, pyright and lint-imports run once, on 3.13. Job
`web` (placeholder until T008:
`pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm lint`,
`pnpm test`, `pnpm build`), job `contract` (T008's freshness check).
`.github/workflows/nightly.yml`: Postgres service container, `uv run
pytest -m postgres` (marker registered now, tests arrive in T014).
**Done.** CI green on the branch.
**Status.** Done, except its exit condition: this checkout has no git
remote and no CI to be green on, so both workflows were written and
verified locally (they parse, and `tests/test_ci_workflows.py` asserts
that they mirror every step of `./scripts/test.sh`); no run was
observed. The first push to a remote observes it.

### T007 — `web/` scaffold and the Nocturne theme (A0.6)

**Do.** `pnpm-workspace.yaml` (`packages: ["web"]`). `pnpm create vite
web --template react-ts`; React 19, TS strict (`noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`); Tailwind v4 via `@tailwindcss/vite`;
`pnpm dlx shadcn@latest init` (style `new-york`, CSS variables on);
`@fontsource-variable/jetbrains-mono`; `@phosphor-icons/react`.
`web/scripts/gen-theme.mjs`: reads `docs/v1/design/nocturne.css`,
copies every `--color-*`, `--space-*`, `--shadow-*`, `--ath-*` token into
`web/src/styles/theme.css` under `:root`, then appends the shadcn
mapping block from 10 §Tokens → shadcn (`--background: var(--color-bg)`
…), the `@theme inline` block exposing them to Tailwind (no `--radius`
override: Nocturne's 8 px stands, D71), and the app type scale (12 px
base, JetBrains Mono). `pnpm gen:theme`
script; CI fails if the generated file is stale.
`vite.config.ts`: `build.outDir = "../athanore/web/dist"`,
`emptyOutDir: true`, `server.proxy["/api"] → http://127.0.0.1:4002`.
Placeholder `App.tsx` rendering the brand mark on `--color-bg`.
**Dev stack.** `pnpm` runs inside `dev` (T000); `node_modules` lives on
the named volume, so `pnpm install` is always done through the container.
**Done.** `pnpm build` writes `athanore/web/dist/index.html`;
`uv build` produces a wheel containing it (`unzip -l dist/*.whl | grep
web/dist`).
**Status.** Done. The shadcn CLI no longer takes a `--style`; its
`radix-lyra` preset is Radix primitives with Phosphor icons and
JetBrains Mono, which is 10 §Stack exactly (D77). `theme.css` is
generated by `pnpm gen:theme` and its freshness is asserted by
`web/src/styles/theme.test.ts`, so `pnpm test` — a step of the gate and
of CI's `web` job — fails on a hand edit (D78). `[tool.hatch.build]
artifacts` moved out of `targets.wheel`, without which the wheel `uv
build` produces has no `index.html` (D79).

### T008 — OpenAPI → TypeScript pipeline (A0.7)

**Do.** `athanore/api/app.py` stub: `create_app(settings=None, engine=None,
store=None, plugins=None) -> FastAPI` exposing only `GET /api/health`
(`{ok: true, version}`) for now. `scripts/dump_openapi.py` writes
`create_app().openapi()` to `tests/snapshots/openapi.json` (sorted keys,
2-space indent). `web/openapi-ts.config.ts`: input
`../tests/snapshots/openapi.json`, output `web/src/api/gen`, plugins
`@hey-api/client-fetch`, `@tanstack/react-query`. `pnpm gen` runs both.
`tests/test_openapi_snapshot.py`: `create_app().openapi() ==
json.load(snapshot)` with a message telling the reader to run the script.
CI `contract` job: `uv run scripts/dump_openapi.py && pnpm gen && git
diff --exit-code tests/snapshots web/src/api/gen`.
**Done.** Snapshot and generated client committed; CI contract job green.
**Status.** Done, with the same caveat as T006: there is no remote to
watch the `contract` job on, so it was run step by step locally
(`uv run scripts/dump_openapi.py && pnpm -C web gen` leaves
`git diff --exit-code tests/snapshots web/src/api/gen` clean, twice in a
row), and `tests/test_openapi_snapshot.py` carries the Python half of
the check into the gate. The job lost T006's probe: both generators are
in the tree for good, and a freshness check that can decide not to run
is not one. `web/src/api/gen` is its own TypeScript project because the
generator bundles a fetch runtime that is not
`exactOptionalPropertyTypes`-clean (D80).

---

## Phase 1 — Store and engine

### T009 — Event vocabulary and the `Event` model (A1.7)

**Do.** `athanore/events/names.py`: `class EventName(StrEnum)` with every
row of 03 §Event vocabulary (`run.created` … `engine.stopping`); one
pydantic payload model per name in `athanore/events/payloads.py` exactly
as 18 specifies, plus `EventEnvelope` with the discriminated union;
`PLUGIN_PREFIX = "plugin."`; `is_known(name) -> bool` (enum member or
`plugin.<wf>.<name>` with two further identifier segments);
`EPHEMERAL = {EventName.task_stream}`; `matches(pattern, name)` for glob
patterns (`fnmatch` on dotted names, `run.*` matches one segment only).
`athanore/events/model.py`: `class Event(BaseModel)`: `id: int | None`,
`run_id: str | None`, `task_id: int | None`, `name: str`, `data: dict`,
`created: datetime`.
**Tests.** `tests/test_events_names.py`: every enum value is `subject.verb`;
`matches("task.*", "task.stream")` true, `matches("run.*", "run.a.b")`
false; `is_known("plugin.gamedev.word")` true.
**Done.** Tests pass.

**Status.** Done. The payload models type 18's domain-enum fields as
`str`: those enums arrive with the store in T010, and `events` may not
import `store` (D81). `agent.stats` carries `denied_permissions`, which
05 §Stats entry names and 18's field list omits.

### T010 — Domain enums and read models (A1.3 part)

**Do.** `athanore/store/rows.py`: `RunStatus` (`queued running paused
completed failed cancelled`), `TaskStatus` (`ready in_progress waiting
done failed dead_letter cancelled`), `LogAuthor` (`agent engine user`),
`LogKind` (`deliverable note stats failure`), `ChunkKind` (`text thought
tool_call tool_result notice`), `RequestMode` (`options form text`),
`RequestSource` (`agent node`), `RequestKind` (`permission elicitation
question`), `AnswerAuthor` (`user engine`). Pydantic read models with
`model_config = ConfigDict(frozen=True)`: `RunRow`, `TaskRow` (no token
field, `token_hash` excluded from `model_dump` by default via
`Field(exclude=True)`), `LogEntryRow`, `SubmissionRow`, `StreamChunkRow`,
`RequestRow`, `AnswerRow`, `EventRow`, `RunSummary` (adds
`current_nodes: list[str]`, `pending_requests: int`, `unregistered:
bool`), `RunStats` (`input_tokens, output_tokens, total_tokens, cost,
tool_calls, duration_s`, all optional).
**Done.** Importable; pyright strict clean.

**Status.** Done. The models share a frozen `ReadModel` base and
`RunSummary` extends `RunRow`; `TaskRow.branch` is a list of a typed
`BranchFrame` while the other JSON columns stay untyped, and
`RequestRow` spells 08's `schema` as `schema_` with that alias (D82).
`ChunkKind`'s `thought` was missing from 03 §StreamChunk, which now
lists it. `tests/store/test_rows.py` pins the two properties that are
not typing: `token_hash` never serializes, and `RunStats` omits what
was not measured.

### T011 — SQLAlchemy Core tables and the engine factory (A1.1)

**Do.** `athanore/store/tables.py`: `metadata = MetaData(naming_convention=…)`;
`JSONV = JSON().with_variant(JSONB, "postgresql")`; `TS =
DateTime(timezone=True)`. Tables exactly as 07 §Schema: `runs`, `tasks`
(`token_hash String(64) nullable`, `stats JSONV nullable`, `lineage
JSONV`, `terminal Boolean default False`, `branch JSONV default []`),
`join_arrivals` (07; unique on `run_id, join_node, fanout_task, index`), `log_entries`, `submissions`, `stream_chunks` (`UniqueConstraint
("task_id","seq")`), `requests` (`ordinal Integer nullable`; partial
unique `Index("uq_requests_task_ordinal", "task_id", "ordinal",
unique=True, sqlite_where=text("ordinal IS NOT NULL"),
postgresql_where=text("ordinal IS NOT NULL"))`), `answers` (`request_id`
PK+FK), `events` (`id Integer PK autoincrement`). All FKs `ondelete=
"CASCADE"`. Indexes from 07.
`athanore/store/engine.py`: `make_engine(db_url) -> AsyncEngine`; for
SQLite attach a `connect` listener executing `PRAGMA journal_mode=WAL`,
`synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`; pool size
small (`pool_size=4`) for readers. `is_sqlite(engine)` helper.
**Tests.** `tests/store/test_tables.py`: `metadata.create_all` on a tmp
SQLite file; each PRAGMA reads back; inserting a task with an unknown
`run_id` raises `IntegrityError` (proves FKs on); second request with
the same `(task_id, ordinal)` raises, two with `ordinal NULL` do not.
**Done.** Tests pass.

**Status.** Done. The nine tables, their indexes and their cascades are
07 §Schema transcribed; `metadata` carries the naming convention T012's
autogenerate needs, so every constraint has the same name on both
backends. `events` keeps the section's one omission — it carries no
foreign keys, because the outbox writes `run.deleted` after the
transaction deleted the run — and gains `sqlite_autoincrement` so the SSE
cursor is never reused (D83). `make_engine` registers the four pragmas on
the pool's `connect` event, and skips `pool_size` for an in-memory URL,
whose pool rejects it.

### T012 — Alembic environment and the initial migration (A1.1)

**Do.** `athanore/store/migrations/{env.py, script.py.mako, alembic.ini,
versions/0001_v1_schema.py}`; `env.py` uses `run_sync` on the async
engine and `target_metadata = tables.metadata`, `render_as_batch=True` for
SQLite. `athanore/store/migrate.py`: `alembic_config(db_url) -> Config`
(programmatic, `script_location` inside the package), `async def
upgrade(db_url, rev="head")`, `async def current(db_url) -> str | None`,
`async def is_v0_database(db_url) -> bool` (has `runs`, lacks
`alembic_version`).
**Tests.** `tests/store/test_migrations.py`: upgrade on an empty file then
`alembic.autogenerate.compare_metadata` returns `[]`; `current()` ==
`"0001"`; `is_v0_database` true for a v0 fixture (T018 adds the fixture;
mark `xfail` until then or create a 3-table stub inline).
**Done.** Tests pass; no `CREATE TABLE` outside the migration.

**Status.** Done. The environment, the scripts and `alembic.ini` ship
inside the wheel, so an installed Athanore migrates its own database;
`env.py` drives `make_engine` with `run_sync`, so a migration runs with
07's pragmas. `0001` is the autogenerated schema, hand-corrected in two
places: `terminal`'s server default is `false()` rather than the
rendered `text("0")`, which PostgreSQL refuses on a boolean column, and
the `JSONB` variant is written without autogenerate's undefined
`Text()`. The database URL travels in `Config.attributes`, not
`sqlalchemy.url` (D84), and `upgrade()` runs Alembic in a worker thread
because `env.py` owns the event loop. `current()` and `is_v0_database()`
answer for an absent SQLite file without creating one.

### T013 — `EventBus` (A1.2)

**Do.** `athanore/events/bus.py`: `class EventBus` with
`subscribe(patterns: list[str] | None = None, *, maxsize=1000) ->
Subscription` (an `asyncio.Queue` plus `close()`; on a full queue set
`sub.overflowed = True` and drop, so SSE can `resync`), `publish(event)`
(fan out to matching subscriptions using `names.matches`, never awaits
subscribers), `async def wait_for(pattern, predicate, timeout) -> Event`
convenience for tests and waiters.
**Tests.** `tests/events/test_bus.py`: subscriber with `["run.*"]`
receives `run.created` but not `task.started`; overflow flag set when
`maxsize=1` and two events published; `close()` stops delivery;
`wait_for` returns the first matching event and raises `TimeoutError`.
**Done.** Tests pass.
**Status.** Done. `publish` is a plain function and a ticker task
alongside it asserts it never yields to the loop, which is the property
the drop-on-full exists for. `wait_for`'s `timeout` carries a `noqa`
for ASYNC109 — owning the timeout is what the convenience is (D85).

### T013a — `Store`, `UnitOfWork`, outbox (A1.2)

**Do.** `athanore/store/uow.py`: `class Store(engine, bus)` with
`_writer_lock = asyncio.Lock()`, `async def uow() ->
AsyncIterator[UnitOfWork]` (acquires the writer lock, opens a connection
+ `begin()`), `async def read() -> AsyncIterator[AsyncConnection]` (no
lock, pooled), `async def publish_ephemeral(event)` (bus only, never
stored). `class UnitOfWork`: `conn`, repos as attributes (populated by
T014–T016), `emit(event)` appends to `self._outbox`; on `__aexit__`
without exception: insert outbox rows with `RETURNING id`, set
`event.id`, commit, release the lock, then `bus.publish` each in id
order. On exception: rollback, drop the outbox, re-raise. `now()`
helper returning aware UTC.
**Tests.** `tests/store/test_uow.py`: emit inside a failing uow publishes
nothing and stores nothing; two sequential uows produce ascending ids;
a subscriber sees the event only after commit; `publish_ephemeral`
never touches the table; two concurrent `uow()` calls serialise.
**Done.** Tests pass.

**Status.** Done. `store` and `events` are independent siblings of the
bottom tier, so `uow.py` names the two shapes it needs from the event
layer structurally — `OutboxEvent` and `EventPublisher` — instead of
importing `athanore.events` (D86). `UnitOfWork` is itself the async
context manager and `Store.uow()` is a one-line wrapper around it, so
insert / commit / unlock / publish is stated in one place; the outbox is
one `INSERT ... RETURNING id` per event in emission order.

### T014 — `RunRepo` (A1.3)

**Do.** `athanore/store/repos/base.py`: `Repo(conn)` with `_row(model,
Row)` conversion. `repos/runs.py`: `insert(workflow, title, description)
-> RunRow` (ULID id, `status=queued`, `position = COALESCE(MAX(position),
0)+1`), `get(id)`, `list(status=None, workflow=None) -> list[RunSummary]`
(one query with two correlated scalar subqueries: `current_nodes` as
`GROUP_CONCAT`/`string_agg` of distinct nodes where task status in
`(in_progress, waiting)`, `pending_requests` as count of requests with no
answer whose task is in `(in_progress, waiting)`), `detail(id) ->
(RunRow, list[TaskRow], RunStats)` (stats via `SUM(json_extract(stats,
'$.input_tokens'))` etc., dialect-switched), `update(id, **fields)`
touching `updated`, `set_status(id, status, finished=None)`,
`swap_position(id, direction)` (neighbour by `position` ordering, swap
both rows), `move_position(id, index)` (renumber all in a single
`UPDATE … CASE`), `compact_positions()`, `delete(id)` (one `DELETE`,
cascades). Wire onto `UnitOfWork` and a read-only `Reader` facade on
`Store`.
**Tests.** `tests/store/test_runs_repo.py`: positions append at `max+1`;
swap with no neighbour is a no-op returning the same position;
`move_position` to index 0 renumbers 1..n; `list()` aggregates for a run
with two in-flight nodes and one open request; `detail()` sums stats
across attempts including failed ones; `delete` cascades.
**Done.** Tests pass.

**Status.** Done. `Repo._row` takes a row *mapping* rather than a `Row`
(pyright strict refuses `Row._mapping` as private) and stamps UTC onto
the naive datetimes SQLite hands back, so a read model is the same value
on both backends. `list()` and `detail()`'s statements are built by
module-level `list_statement(dialect, …)` / `stats_statement(dialect, …)`,
so the PostgreSQL spelling is compiled by the gate and not only by the
nightly job; `list()` is asserted to be one statement with a cursor
counter. `update()` refuses a column it does not own rather than dropping
it, position changes do not touch `updated`, and `delete()` is the
`DELETE` plus the events sweep D83 called for. `Reader` and `UnitOfWork`
share a `Repos` bundle, so a repository is reached the same way on either
(D87). `compact_positions()` renumbers in Python and writes
`move_position()`'s single `UPDATE … CASE`: a correlated rank subquery
inside the `UPDATE` reads the rows the same statement has already
rewritten on SQLite but not on PostgreSQL, so duplicated positions —
which T018's import can produce — compacted differently on the two
backends (D88). T014a and T014b were built in this task's run, as the
two commits after this one on `feat/T014` (D88).

### T014a — `LogRepo`, `EventRepo`, `SubmissionRepo` (A1.3)

**Do.** `repos/log.py`: `append(run_id, node, author, text, task_id=None,
kind=None) -> LogEntryRow`, `list(run_id, after=0, limit=None,
exclude_kinds=())`. `repos/events.py`: `insert_many(events) -> list[int]`,
`list_after(after, limit, run_id=None, patterns=None)`, `list_for_run`,
`prune(before, keep_prefix="run.")`. `repos/submissions.py`:
`insert(task_id, payload)`, `latest(task_id)`, `list(task_id)`.
**Tests.** `tests/store/test_log_repo.py`, `test_events_repo.py`,
`test_submissions_repo.py`: `exclude_kinds=("stats",)` drops stats
lines; `list_after` honours cursor, limit, run filter and glob patterns;
`prune` keeps `run.*`; `latest` returns the highest id.
**Done.** Tests pass.

**Status.** Done. `EventRepo.insert_many` is the outbox's write path:
`UnitOfWork._write_outbox` flushes through it with
`sort_by_parameter_order`, superseding T013a's insert-per-event (D87).
The glob of `list_after` is translated to `LIKE` plus an equal-dot-count
check, which is exactly `athanore.events.names.matches` for `*` and `?`
and is asserted against it case by case; a `fnmatch` character class is
refused rather than silently mismatched. `OutboxEvent` moved to
`repos/events.py` and is re-exported from `uow.py`. Built in T014's run, as
the commit `T014a:` on `feat/T014` (D88); do not submit it again. A later
re-dispatch audited the merged deliverable against the **Verification**
block above and found the glob and `prune`'s prefix case-insensitive on
SQLite and case-sensitive on PostgreSQL, where `matches` is `fnmatchcase`
on both; `feat/T014a` carries that fix (D89).

### T014b — `StreamRepo` and the Postgres test matrix (A1.3)

**Do.** `repos/stream.py`: `append_batch(task_id, chunks: list[(seq,
kind, text)])` (one `INSERT … VALUES (…),(…)`), `list_after(task_id,
after_seq, limit)`, `last_seq(task_id)`, `prune_finished(before)` (join
tasks where `finished < before`). `tests/store/conftest.py`: a `db_url`
fixture parametrised over SQLite (always) and `ATHANORE_TEST_PG_URL`
(marker `postgres`, skipped when unset), applied to every store test.
**Tests.** `tests/store/test_stream_repo.py`: batch insert of 50 chunks;
`list_after` pagination; unique `(task_id, seq)` violation raises;
`prune_finished` leaves running tasks alone.
**Dev stack.** `docker compose --profile pg up -d postgres` and the `dev`
service's `ATHANORE_TEST_PG_URL` (T000) run the Postgres variants locally.
**Done.** Tests pass on SQLite; Postgres variants skip without the `pg`
profile and pass with it.

**Status.** Done. The `postgres` parameter skips when
`ATHANORE_TEST_PG_URL` is unset **and** when it is set but nothing
answers — the dev container always sets it, so a reachability probe
(once per session, cached) is what keeps the gate green with the profile
down. Each PostgreSQL test starts from `DROP SCHEMA public CASCADE`, so a
migration test finds no `alembic_version` either. `test_uow.py`,
`test_tables.py` and `test_migrations.py` were retrofitted onto the
fixture; the tests whose subject *is* SQLite — the pragmas, the file a
question must not create — take `sqlite_url` and skip on the other
parameter. `append_batch` is one multi-row `VALUES`, split only above
`MAX_ROWS_PER_INSERT` so an implausible burst cannot exceed a backend's
bind-parameter limit. Built in T014's run, as the commit `T014b:`
on `feat/T014` (D88); do not submit it again. A later re-dispatch
audited the merged deliverable against the **Verification** block of
`docs/plans/T014b-stream-repo-and-pg-matrix.md` and found nothing to fix
(D90): the store suite is green on SQLite with the Postgres parameter
skipping with its reason rather than erroring, every store test that
opens a database takes `db_url` — the ones off the matrix read metadata
or call pure functions — and all four statements compile unchanged for
both dialects. The PostgreSQL half was not re-run: that container has no
docker socket and nothing answers on 5433, so `feat/T014b` carries the
audit and no code.

### T015 — `TaskRepo` (A1.3)

**Do.** `athanore/store/repos/tasks.py`: `enqueue(run_id, node, payload,
priority, explicit, attempt=1, created=None, lineage=None, branch=())
-> TaskRow` (`created` defaults now; retries pass the old value),
`get(id)`, `list_for_run(run_id)`, `by_token_hash(hash) -> TaskRow |
None`, `finish(id, status, result=None, error=None, terminal=False)`
(sets `finished`), `set_status(id, status)`, `set_stats(id, stats)`,
`last_for_node(run_id, node) -> TaskRow | None` (payload and branch for
rerun), `has_pending(run_id) -> bool` (any `ready in_progress waiting`),
`terminal_tasks(run_id) -> list[TaskRow]` in branch order,
`reset_for_recovery() -> list[int]` (`in_progress|waiting → ready`,
`started=NULL`, `token_hash=NULL`).
**Tests.** `tests/store/test_tasks_repo.py`: enqueue defaults; `finish`
sets `finished` and `terminal`; `reset_for_recovery` touches only the
two statuses and clears the token hash; `terminal_tasks` ordering by
branch index path.
**Done.** Tests pass.

**Status.** Done. `enqueue` takes `created` because the engine owns the
clock: a retry passes the failed attempt's value, and `created DESC` is
the dispatch order's last tiebreaker. `set_status` deliberately writes no
timestamp — `finish` is the one call that ends an attempt — and
`by_token_hash` is a lookup, not an authorisation: whether the attempt is
still live is T043's check. `terminal_tasks` sorts on the frame index
path in Python, because a path through a JSON array has no index either
backend can use, and `reset_for_recovery` is a startup sweep across every
run (D91).

### T015a — `TaskRepo.claim_ready` (A1.4, D38, D41)

**Do.** `claim_ready(limit, workflows) -> list[ClaimedTask]` where
`ClaimedTask = (TaskRow, token: str, run_started: bool)`: (1) the SELECT
of 04 §Dispatch order (with `FOR UPDATE SKIP LOCKED` when dialect is
postgresql), (2) for each id mint `token = secrets.token_urlsafe(32)`,
`token_hash = sha256(token).hexdigest()`, (3) `UPDATE tasks SET
status='in_progress', started=now, token_hash=? WHERE id=? AND
status='ready'` (rowcount 1 or the id is skipped), (4) for each distinct
run with `status='queued'` flip to `running` and flag `run_started=True`,
(5) re-select rows in claimed order.
**Tests.** `tests/store/test_claim.py` (port the ordering assertions of
`tests/test_priority.py` to the repo level): run position dominates;
explicit priority beats generation; `-generation` orders downstream
first; equal keys → newer `created` first; a retry with the old `created`
does not jump; `limit` respected; tokens unique per claim, hash matches,
clear text absent from the row; second `claim_ready` returns nothing;
`queued → running` flagged once; paused runs are never claimed.
**Done.** Tests pass; `tests/test_priority.py` still exists (its API
half is ported in T044a).

**Status.** Done. Built inside T015's run, on `feat/T015`, as one commit
with it (D91, the precedent of D88); do not submit it again. The select
is 04 §Dispatch order transcribed, and the two `CASE` expressions are not
redundant next to `explicit DESC`: that split is what keeps either
group's order off the backends' disagreement about where `NULL` sorts.
The PostgreSQL lock is `FOR UPDATE OF tasks SKIP LOCKED`, and the
`UPDATE` is one statement per id — a token per attempt means a different
hash per row — with `AND status = 'ready'` as the claim. 07 §Repositories
is updated to match. The PostgreSQL leg was not run: that container has
no docker socket (D90). A later re-dispatch audited the merged
deliverable against the **Verification** block of
`docs/plans/T015a-claim-ready.md` and found nothing to fix (D90): the
select is 04 §Dispatch order clause for clause, each `CASE` is non-`NULL`
in exactly the group `explicit DESC` put it in, the claim is one
`UPDATE … AND status = 'ready'` per id with a token minted per id, the
run flip is `AND status = 'queued'` on `runs`, and the re-select returns
the rows in claimed order. `tests/store/test_claim.py` carries every
assertion the block names — the four ordering rules, the retry that keeps
its `created`, `limit`, unique tokens whose clear text is absent from the
row, the second claim that returns nothing, `run_started` flagged once,
and the paused run — and the whole gate is green on SQLite (401 passed,
211 skipped). The PostgreSQL leg was again unreachable, for the reason
D90 records, so `feat/T015a` carries the audit and no code.

### T016 — Repositories part 3: requests and answers (A1.3)

**Do.** `athanore/store/repos/requests.py`: `create(run_id, task_id,
prompt, mode, source, kind, options=None, schema=None, tool_call=None,
ordinal=None) -> RequestRow`, `get(id)`, `by_ordinal(task_id, ordinal)`,
`answer(request_id, author, option_id=None, value=None) -> AnswerRow`
(raises `IntegrityError` on a second answer, mapped by the service),
`mark_consumed(request_id)`, `view(id) -> RequestView` and
`list_views(run_id=None, pending_only=False)`: one query joining
`requests ⟕ answers ⟗ tasks`, computing `pending = answer IS NULL AND
task.status IN ('in_progress','waiting')`, `stale = answer IS NULL AND
NOT pending`, `node = task.node`, `age = now - created`. `RequestView`
pydantic model in `rows.py` with the fields of 08 §Requests.
**Tests.** `tests/store/test_requests_repo.py`: second answer raises;
view flags pending vs stale by task status; inbox excludes answered and
stale; ordinal lookup.
**Done.** Tests pass.

**Status.** Done. `view` and `list_views` are one statement,
`view_statement(run_id, pending_only)`: `pending` and `stale` are SQL
predicates over the outer-joined answer and the inner-joined task, so
`pending_only` narrows the query rather than the rows already fetched,
and the run list's `pending_requests` counts by the same rule. `age` is
finished in Python — the row already carries `created`, and date
arithmetic in SQL would be a dialect switch buying nothing — with one
timestamp per call, so every view in a listing is measured against the
same instant. `RequestView` carries `stale` beside 08's field list and
folds the answer's two columns into one `answer` (D92). Nothing here
decides: `answer` lets the double-answer `IntegrityError` out for the
service to map, and `mark_consumed` records the claim without judging a
replay. `RequestRepo` joins the `Repos` bundle, so it is reachable as
`uow.requests` and `reader.requests`. The PostgreSQL leg was not run:
that container has no docker socket (D90).

### T017 — Retention job (A1.5)

**Do.** `athanore/store/retention.py`: `async def prune_once(store,
retention, now)` (stream chunks of finished tasks older than
`stream_days`; events older than `events_days` except `run.*`), `async
def retention_loop(store, retention, interval=3600)` cancellable.
**Tests.** `tests/store/test_retention.py` with `freezegun`: chunks of a
task finished 15 days ago are gone, of a running task remain; a
`task.done` event 31 days old is gone, `run.created` of the same age
remains; deleting a run removes all eight child tables' rows (cascade).
**Done.** Tests pass.

**Status.** Done. Two functions and no SQL: both windows are one call to
a query T014a and T014b already own, and the two deletes share one
transaction so a pass cannot enforce the two windows to different
instants. `now` defaults to the store's clock, which is what lets a
caller pass the exact instant a `freezegun` test measures from.
`Retention` is a `Protocol` naming `events_days` and `stream_days`, not
an import of `athanore.settings`: they are independent siblings of the
bottom tier, the shape `EventPublisher` already takes for the bus (D93).
`prune_once` returns real `PruneCounts` from the two statements' row
counts. `retention_loop` prunes *before* its first sleep, so a machine
restarted more often than the interval still prunes, and catches
nothing: `CancelledError` propagates untouched, and a failed pass ends
the loop rather than leaving a janitor that looks alive while the
database grows. The cascade is asserted end to end over all eight child
tables — seven by key, `events` by the sweep of D83 — against a second
run that keeps its rows. The PostgreSQL leg was not run: that container
has no docker socket (D90).

### T018 — v0 importer (A1.6)

**Do.** Fixture: `scripts/make_v0_fixture.py` uses the **MVP**
`athanore.store.Store` (still present) to build
`tests/fixtures/v0/mvp_small.sqlite3` (extension chosen so `*.db` in
`.gitignore` does not swallow it) containing: two runs (one completed,
one `running` with no task ever started), tasks in each status, a log
with a `[stats]` line and an `attempt 1 failed` engine line, a
`messages` request + answer pair, legacy `permission` and `question`
kinds, `agent_progress` events with a `> tool:` line, a `run_stats` event,
a `transition` event. Commit the file.
`athanore/store/legacy.py`: `async def import_v0(src: Path, dest_url:
str) -> ImportReport` implementing the 07 mapping table row by row
(`sqlite3` read of the source, Core inserts into a freshly migrated
destination; `runs.priority → position`; `running` with no started task
→ `queued`; `tasks.token → token_hash` for finished, NULL otherwise;
`log → log_entries` with kind inference; `messages` split into
`requests`/`answers`; `agent_progress → stream_chunks`; `run_stats →
agent.stats` + `tasks.stats`; `transition → task.enqueued
reason=transition`). Idempotent: skip when the destination already has
the run id. Never writes to `src`.
**Tests.** `tests/store/test_legacy_import.py`: row counts per table
match expectations; running twice changes nothing; source file bytes
unchanged (hash before/after).
**Done.** Tests pass.

### T019 — Graph package split and node options (A0.1 tail, 04 §Graph DSL)

**Do.** `athanore/graph/model.py`: `@dataclass(frozen=True) class Node`
(`name, fn, edges: tuple[str,...], payload_param, start, join: bool,
priority, retries: int | None, timeout: float | None, label,
description, generation`), `@dataclass(frozen=True) class Graph` (`name, nodes:
Mapping[str, Node], start: str`). `athanore/graph/builder.py`:
`Transition`, `EdgeRef`, `GraphError`, `parse_signature(fn)` (the MVP
function, public), `class GraphBuilder(name)` with `node(*, start=False,
priority=None, retries=None, timeout=None, label=None, description=None)`
(rejects duplicates, records `label or fn.__name__`, `description or
inspect.getdoc(fn)`) and `build() -> Graph`. `athanore/graph/validate.py`:
`finalize(builder) -> Graph` running the five checks of 04 §Finalization
(name must match `^[a-z][a-z0-9_]*$`), rejecting a `join=True` node
without a payload slot, and BFS generations.
`athanore/graph/json.py`: `jsonable(value)` (pydantic → `model_dump(mode=
"json")`, dataclass → `asdict`, `Transition` → dict, fallback `str`);
move `_util.jsonable` users to it.
**Tests.** `tests/graph/test_builder.py` (port `tests/test_graph.py`
assertions), `tests/graph/test_hypothesis.py`: random DAGs with cycles
→ `finalize` never raises on valid graphs, generations equal
shortest-path depth from start, every unreachable node is reported.
**Done.** `tests/test_graph.py` deleted; hypothesis suite passes with
`max_examples=200`.

### T020 — `Workflow` object (D48, 04 §Programmatic host)

**Do.** `athanore/workflow.py`: `class Workflow` owning a `GraphBuilder`
and (from T049) plugin declarations. Methods now: `node(...)` delegating,
`finalize() -> Graph` (idempotent, caches), `graph` property (raises if
not finalized), `name`, `run(**settings)` shorthand (imports `Server`
lazily; real implementation in T031). `AthanoreWorkflow = Workflow` kept in
`athanore/graph/__init__.py` as the deprecated alias (14
§Compatibility).
**Tests.** `tests/test_workflow.py`: `finalize` twice returns the same
`Graph`; node options round-trip.
**Done.** MVP suite still green (it constructs `AthanoreWorkflow`).

### T021 — Routing interpretation and failure classes (A1.9 part, D42)

**Do.** `athanore/engine/errors.py`: `class NonRetryable(Exception)`;
`is_retryable(exc) -> bool` (`False` for `GraphError`, `NonRetryable`
and subclasses; `True` otherwise including `TimeoutError`).
`athanore/engine/routing.py`: `interpret(node: Node, value) ->
list[Transition]` per the 04 table; payload coercion via `jsonable`;
undeclared target → `GraphError`; `≥2 edges` with a plain value →
`GraphError`; empty list → treated as terminal with `value=[]` (state
this in 04).
**Tests.** `tests/engine/test_routing.py`: every row of the table; list of
mixed `EdgeRef`/`Transition`; pydantic payload becomes dict.
**Done.** Tests pass.

### T022 — Pools, leases, re-admit queue, live registry (A1.8, D43)

**Do.** `athanore/engine/pools.py`: `class Pool(name, capacity)` (public,
frozen, validates name `^[a-z][a-z0-9_]*$`); `class PoolState(pool)` with
`leased: int`, `readmit: deque[Waiter]` where `Waiter = (task_id,
future[Lease], enqueued_at)`; `free()`, `try_acquire() -> Lease | None`,
`release(lease)`, `request_readmit(task_id) -> Awaitable[Lease]`, `drain_
readmits()` (hands leases while `free() > 0`); `class Lease(pool_state,
task_id)` with `release()` idempotent. `class PoolRegistry`: `add(pool)`,
`bind(workflow, pool_name)`, `for_workflow(wf)`, `workflows_of(pool)`,
`snapshot() -> dict[name, {capacity, in_flight}]`; rejects duplicate
names and a pool name equal to a workflow name.
`athanore/engine/live.py`: `class LiveRegistry`: `register(ctx)`,
`unregister(task_id)`, `context_for(task_id) -> TaskContext | None`,
`all()`.
**Tests.** `tests/engine/test_pools.py`: capacity 0 never acquires;
release then acquire; readmit served before `try_acquire` in
`drain_readmits`; FIFO among readmits.
**Done.** Tests pass.

### T023 — `TaskContext`, `current_task()`, `TaskServices` (A1.10)

**Do.** `athanore/engine/context.py`: `@dataclass class TaskContext` with
the fields of 04 §TaskContext plus private `_timeout: asyncio.Timeout |
None` and `_released_at: float | None`; `_current: ContextVar[TaskContext
| None]`; `bind(ctx)` context manager; `current_task()` (raises
`RuntimeError("no task context")`), `maybe_current_task()`.
`athanore/engine/services.py`: `class TaskServices` bundling
`log: LogService` (`append(text, *, author="agent", kind=None)` → uow +
`log.appended`), `submissions: SubmissionService` (`latest()`,
`accept(payload)` → insert + `submission.accepted`, `reject(errors,
schema)` → event only), `requests: RequestsPort` (a Protocol;
implementation lands in T032), `run: RunService` (`get()`), `lease:
LeaseService` (`released()` implemented in T026; stub raising
`NotImplementedError` now), `events: EventPort` (`publish(name, data)`
restricted to `plugin.*` names), `stream` (T023a; `None` until then).
**Tests.** `tests/engine/test_context.py`: `current_task()` raises
outside `bind`; nested binds restore; `TaskServices.log.append` writes a
row and emits `log.appended` with the task id; `events.publish("task.
done", …)` is rejected.
**Done.** Tests pass.

### T023a — `StreamService` flusher (A1.10, 07 §Transcript writes)

**Do.** `StreamService` in `services.py`: in-memory `buffer: list[(seq,
kind, text)]`, `seq` counter initialised from `StreamRepo.last_seq`,
`append(kind, text)`, background `_flusher()` every
`stream_flush_interval`: if the buffer is non-empty, one
`uow.stream.append_batch` then `store.publish_ephemeral(Event("task.
stream", data={seq_from, seq_to}))`; `async def close()` cancels the
flusher and flushes once more; a flush failure is logged and retried on
the next tick, never raised into the body.
**Tests.** `tests/engine/test_stream.py`: 20 appends within one interval
→ one batch insert and one ephemeral event; `close()` flushes the
remainder; seq continues after a restart (`last_seq`); the ephemeral
event never appears in `events`.
**Done.** Tests pass.

### T024 — Runner: attempt lifecycle and the success path (A1.9)

**Do.** `athanore/engine/runner.py`: `async def run_attempt(engine, claimed:
ClaimedTask, lease)`: load run + node from the registered `Graph`; build
`TaskContext` (`api_base = settings.public_url`, `token = claimed.token`);
`live.register`; `bind_attempt` logging; uow: `task.started` (and
`run.started` if `claimed.run_started`). Body call: `edge_refs = [EdgeRef
(e) for e in node.edges]`, `kwargs = {node.payload_param: task.payload}`
when the node has a payload slot (a `None` payload is passed as `None`,
04 §Routing edge cases); wrapped in `async with asyncio.timeout(node.
timeout or None) as t:` with `ctx._timeout = t`. Success: `interpret` →
one uow: `finish(done, result=jsonable(value), terminal=not transitions)`;
for each transition `enqueue(node=target, payload, priority=explicit or
-generation, explicit=bool(node.priority is not None), lineage={"from":
id, "reason": "transition"}, branch=task.branch)` + `task.enqueued` +
`task.done`; if no transitions and `not has_pending(run)` → `set_status
(run, completed, finished=now)` + `run.completed` with `output` per the
shape rule (T015 `terminal_tasks`). Fan-out frames and joins are T024b.
`finally`: `services.stream.close()`, `lease.release()`, `live.unregister`,
`scheduler.notify()`.
**Tests.** `tests/engine/test_runner.py` with a minimal engine stub
(`store`, `settings`, `live`, `graphs`, `notify`; the real `Engine`
arrives in T027): plain return with one edge auto-transitions and
carries the payload; bare ref, called ref, and list of two refs enqueue
the expected rows; terminal completes the run and stores `output`;
`current_task()` works inside the body and not after; the context is
unregistered in `finally` even when the body raises.
**Done.** Tests pass.

### T024a — Runner: failure path, retries, timeouts, cancellation (A1.9, D42, D52, D60)

**Do.** In `run_attempt`, the `except` arm: uow `finish(failed,
error=repr(exc))`; `log.append(engine, kind=failure, f"attempt {n} failed:
{exc}")`; if `is_retryable(exc) and attempt < (node.retries or
settings.max_retries)`: enqueue the retry (same payload/priority/branch/
`created`, `attempt+1`, lineage `retry`) + `task.failed will_retry=true
retry_task_id=…`; else `set_status(task, dead_letter)` + `task.dead_
lettered` + `set_status(run, failed)` + `run.failed`. `asyncio.
TimeoutError` from the node timeout follows the same arm.
`CancelledError`: re-raise without writing a status (the operator op has
recorded `cancelled`; a shutdown leaves the row for recovery). The
`finally` of T024 runs on every path.
**Tests.** `tests/engine/test_runner_failures.py`: raise → retry keeps
`created` and increments `attempt`; `NonRetryable` and `GraphError`
dead-letter on attempt 1 and fail the run; the third failure of a
`retries=3` node dead-letters; `timeout=0.05` on a sleeping body → failed
+ retry; cancelling the asyncio task leaves the row `in_progress` and
records nothing; the failure log line is present with `kind=failure`.
**Done.** Tests pass.

### T024b — Fan-in: branch frames, `JoinRepo`, arrival and dispatch (A1.9b, D62)

**Do.** `TaskRepo.enqueue` propagates `branch`: copied from the parent
for single transitions, retries, reruns and moves; a pushed frame for
fan-outs. Fan-out in T024's success path pushes `{fanout: task.id,
index: i, count: N, key: jsonable(payload)}` onto each child's `branch`
for a list of N ≥ 1 transitions. `store/repos/joins.py`: `JoinRepo.arrive(run_id,
join_node, fanout_task, index, key, value, from_task) -> (arrived, count,
late)` (upsert on the unique key; `late=True` when a join task for that
fan-out already exists), `arrivals(run_id, join_node, fanout_task) ->
list[ArrivalRow]`, `incomplete(run_id) -> list[(join_node, fanout_task,
arrived, count)]`. Runner: a transition whose target node has `join=True`
pops the top frame (`GraphError` on an empty stack), calls `arrive`,
emits `join.arrived`, and when `arrived == count` enqueues the join task
with `payload = [{index, key, value, from_task}]` in index order, `branch
= frames[:-1]`, lineage `{from: fanout, reason: "join", arrivals: [...]}`.
Graph builder: `node(join=True)`; finalize rejects a join with no payload
slot. Event payloads per 18.
**Tests.** `tests/engine/test_fanin.py`: three branches → join receives
three dicts in index order with the fan-out keys; nested fan-out/join;
`count == 1` fires on the first arrival; routing into a join with no
frame raises `GraphError`; a join node without a payload slot fails
`finalize`; the join task's `branch` is the parent's stack.
**Done.** Tests pass.

### T024c — Fan-in: failure semantics, late arrivals, output shape (A1.9b, D58, D62)

**Do.** Completion check in the runner: no pending tasks and
`JoinRepo.incomplete(run)` empty → `completed` with `output` per the
shape rule (single terminal task → its value; several → list in branch
order); non-empty → `failed` with `join_incomplete: <join> has k of n
arrivals` and `run.failed code=join_incomplete`. Late arrivals (after the
join task exists) are stored with `late=true` and emit `join.arrived
late=true` without a second join task. `Ops` (T027b): `move` rejects a
join target with `Conflict`; `rerun` of a join node replays the stored
payload.
**Tests.** `tests/engine/test_fanin_failures.py`: one branch dead-letters
→ run `failed`, `retry` on it → join fires → run `completed`; a branch
that terminates instead of joining → `failed` with
`code=join_incomplete`; late arrival after the join fired → `late: true`,
no second join task; recovery with two of three arrived → third arrives
after restart and the join fires; `output` is scalar with a join and a
list without one; the same fan-out with shuffled body delays yields an
identical `output`.
**Done.** Tests pass; no `output` assertion depends on finish order.

### T025 — Scheduler loop (A1.8)

**Do.** `athanore/engine/scheduler.py`: `class Scheduler(engine)`:
`_wake = asyncio.Event()`, `_attempts: dict[task_id, asyncio.Task]`,
`notify()`, `start()`, `stop()` (cancel all attempts, await them, cancel
the loop). `_loop()` per 04 §The loop: reap done tasks; per pool:
`drain_readmits()`; `free = pool.free()`; if `free > 0`: one uow
`claim_ready(free, workflows_of(pool))` (emitting `run.started` for
flagged runs); for each claimed: `lease = pool.try_acquire()`; spawn
`asyncio.create_task(run_attempt(...))`. Wait on `_wake` with a 1 s
timeout (`tick` injectable for tests). Exceptions inside the loop are
logged and the loop continues.
`cancel_attempts(task_ids)` for ops (T026).
**Tests.** `tests/engine/test_scheduler.py`: with `workers=1` two ready
tasks run one after the other; `capacity=0` pool never claims; `notify()`
wakes before the tick; `stop()` cancels a running body.
**Done.** Tests pass.

### T026 — Lease release for waiting bodies (A1.8, 04 §Waiting)

**Do.** Implement `LeaseService.released()` in `services.py`: on enter,
uow `set_status(task, waiting)` + `task.waiting {request_id}` (request id
passed in by the caller), record `ctx._released_at = loop.time()`,
`lease.release()`, `scheduler.notify()`. On exit: `lease = await
pool.request_readmit(task_id)` (the scheduler hands it in
`drain_readmits`), uow `set_status(task, in_progress)` + `task.resumed`;
if `ctx._timeout` is set: `remaining = ctx._timeout.when() -
ctx._released_at`; `ctx._timeout.reschedule(loop.time() + remaining)`.
Store the new lease on the context so the runner's `finally` releases the
right one.
**Tests.** `tests/engine/test_waiting.py` (bodies call the service
directly; `human_input` arrives in T033): under `workers=1` a body in
`released()` lets a second ready task run; the waiter re-acquires before
a third ready task; `timeout=0.2` with `released()` lasting 0.5 s does
not fail.
**Done.** Tests pass.

### T027 — `Engine` object and recovery (A1.12, A1.13 part)

**Do.** `athanore/engine/__init__.py`: `class Engine(settings, store, bus)`
with `pools: PoolRegistry`, `graphs: dict[str, Graph]`, `live`,
`scheduler`, `ops: Ops` (T027a), `register(graph, pool)`, `async start()`
(recovery then scheduler), `async stop()` (04 §Shutdown: stop claiming,
emit `engine.stopping`, cancel attempts, wait ≤ 10 s).
`athanore/engine/recovery.py`: `recover(engine)`: uow
`reset_for_recovery()` → `engine.recovered {task_ids}`; runs with
unregistered workflows are left alone (the API flags them from
`engine.graphs`). `engine/errors.py` gains `UnknownWorkflow`,
`UnknownNode`, `NotFound`, `Conflict(message)`.
**Tests.** `tests/engine/test_recovery.py`: `in_progress` and `waiting`
rows become `ready` with NULL token hash; `engine.recovered` lists them;
a run of an unregistered workflow is untouched and never claimed.
`tests/engine/test_shutdown.py`: `stop()` during a sleeping body emits
`engine.stopping`, leaves the row `in_progress`, and a following
`start()` recovers it.
**Done.** Tests pass.

### T027a — Operator ops, part 1: submit, edit, reorder, pause, resume, append_log (A1.11)

**Do.** `athanore/engine/ops.py`: `class Ops(engine)`; each op one uow +
events + `notify()` when relevant, preconditions of 04 §Operator
operations mapped to the T027 exceptions. `submit(wf, title,
description)` (run `queued`, start task with `{title, description}`,
lineage `start`); `edit(run, title?, description?)` (empty title →
`Conflict`; `run.updated {changed}`); `reorder(run, direction | index)`
(D57); `pause(run)` / `resume(run)`; `append_log(run, text)` (author
`user`, node = the single in-flight node or `"user"`).
**Tests.** `tests/engine/test_ops_basic.py` (port `tests/test_edit_run.py`
and `test_run_log.py` engine parts, `test_pause.py`): pause blocks the
next claim but the in-flight body finishes; resume dispatches; `edit`
rejects an empty title; reorder swaps and clamps; append_log picks the
node.
**Done.** Tests pass.

### T027b — Operator ops, part 2: cancel, delete, rerun, retry, move, set_status (A1.11)

**Do.** `cancel(run)`: collect `ready|in_progress|waiting` task ids, set
them `cancelled` in the uow (`task.cancelled reason=cancel`), run
`cancelled`, then `scheduler.cancel_attempts(ids)` after commit.
`delete(run)`: `cancel` then `runs.delete` (`run.deleted`). `rerun(run,
node)`: payload and branch from `last_for_node`, lineage `rerun`, attempt
= max attempt for that node + 1; a join node replays its stored arrivals
payload. `retry(task)`: lineage `manual_retry`, keeps `created`, copies
branch. `move(task, node)`: `Conflict` for a join target; cancel the task
(kill via `cancel_attempts`), enqueue at target with the same payload and
branch, lineage `move`, fresh `created`. `set_status(task, ready |
cancelled | dead_letter)`. Re-opening a terminal run sets `running` and
emits `run.updated {changed: {status}}`.
**Tests.** `tests/engine/test_ops_tasks.py` (port `tests/test_management.py`
engine parts): cancel kills a sleeping body and marks tasks; delete
leaves no child rows in any of the nine tables; rerun/retry/move lineage
and `created` rules; `set_status(ready)` re-dispatches; move into a join
→ `Conflict`; a terminal run re-opens on retry.
**Done.** `tests/test_management.py`, `test_pause.py`, `test_run_log.py`
deleted (their API-level assertions are re-added in T044a).

### T028 — Port the engine behaviour tests (A1.14)

**Do.** `tests/engine/test_behaviours.py` driven by an `engine` fixture
(`tests/conftest.py`: tmp SQLite, migrated, `Engine` started and stopped
per test, `run_to_completion(run_id)` helper awaiting `run.completed|
run.failed` on the bus): port `tests/test_deterministic.py`,
`test_fanout.py` (run completes when the last branch lands; branches
carry payloads), `test_priority.py` (dispatch order observed via
`task.started` order), `test_worker_pools.py` (dedicated vs shared vs
zero-capacity; registration errors), `test_qa_gate.py` (loop-back). New:
loop-back payload dropped vs carried; `queued` visible before first
claim; `feature_build`-shaped fan-out closed by a join (T024b/T024c cover the
mechanism, this covers the example's shape).
**Done.** Those five MVP files deleted; coverage of `graph` and `engine`
≥ 95 % (`--cov-fail-under` on those paths in CI).

### T029 — Phase 1 checkpoint

**Do.** Run the full suite; confirm `lint-imports` passes; update 04 with the two
implicit details decided here (empty-list return, `None` payload not
passed). Tag `v1.0.0a1` locally (no push needed).

---

## Phase 2 — Requests and agents

### T030 — Request validators and error classes (A2.1)

**Do.** `athanore/requests/errors.py`: `InvalidOption`, `InvalidAnswer
(errors: list[dict])`, `AlreadyAnswered`, `StaleRequest`, `RequestNotFound`.
`athanore/requests/validators.py`: `pydantic_validator(model) -> Callable
[[Any], Any]` (returns the model instance; converts `ValidationError`
to `InvalidAnswer` with `[{loc, msg, type}]`), `json_schema_validator
(schema)` supporting `type` (incl. unions), `required`, `properties`,
`additionalProperties: false`, `enum`, `const`, `items`, `minItems`,
`minimum/maximum`, `minLength/maxLength`, `pattern`, returning the value
unchanged (move the MVP's light validator from `agents.py`/`human.py`).
**Tests.** `tests/requests/test_validators.py`: each keyword accepted and
rejected; error `loc` paths for nested objects.
**Done.** Tests pass.

### T031 — Requests service (A2.1)

**Do.** `athanore/requests/service.py`: `class RequestService(store, bus)`
with the signatures of 06 §Service. `create` → uow insert + `request.
opened {request_id, mode, kind}`. `answer(request_id, *, option_id=None,
value=None, author="user")`: load view; `StaleRequest` if not pending
and not answered; `AlreadyAnswered` if answered; mode checks
(`options`: id must be in `options`; `text`: non-empty `str`; `form`:
`dict`, run the registered validator if any and store its normalised
return); uow `answers.insert` + `request.answered {request_id, author}`;
map `IntegrityError` → `AlreadyAnswered`. `wait(request_id, timeout)`:
`sub = bus.subscribe(["request.answered"])` **then** re-check the store
(missed-wake guard); loop on the queue until the matching id; `mark_
consumed`; raise `TimeoutError` on expiry. `poll(request_id, wait_s)`:
same without consuming, returns `None` on expiry. `register_validator`/
`unregister_validator` on a dict. `list_for_run`, `inbox` via the repo.
`view(id)`.
**Tests.** `tests/requests/test_service.py` (port `tests/test_requests.py`):
keyed answers under two concurrent waiters; second answer 409 class;
stale after the task finishes; validator normalisation; `wait` sees an
answer that landed before it subscribed; timeout raises.
**Done.** `tests/test_requests.py` deleted.

### T032 — Wire `TaskServices.requests` and the ordinal counter (A2.2 part)

**Do.** `RequestsPort` implementation in `services.py`: `reopen_or_create
(prompt, *, mode, kind, options, schema)`: `ordinal = ctx.request_ordinal
+ 1` (increment on the ctx), `existing = repo.by_ordinal(task_id,
ordinal)`; return it if present, else `create(..., source="node",
ordinal=ordinal)`. `create_agent_request(...)` (source `agent`, no
ordinal). `answer_as_engine(request_id, option_id)`. `wait`, `poll`
delegate.
**Done.** Unit-tested through T033.

### T033 — `human_input`: modes, slot release, timeout (A2.2)

**Do.** `athanore/requests/human.py`: `async def human_input(prompt, *,
options=None, output_model=None, timeout=None)`: mode from arguments
(`options` → normalise `[str | dict]` to `[{option_id, name, kind}]`;
`output_model` → `form` with `model_json_schema()`; else `text`); `req =
await ctx.services.requests.reopen_or_create(...)`; register the
validator; `async with ctx.services.lease.released(req.id): answer =
await wait(req.id, timeout)`; unregister. Decode: `options` →
`option_id` str; `text` → str; `form` → `output_model.model_validate
(value)`. `TimeoutError` propagates into the body.
**Tests.** `tests/requests/test_human_input.py`: `options` returns the
id; `text` returns the string; `output_model` returns an instance and
rejects a misfit at the endpoint with 422; `timeout=0.1` raises in the
body; waiting releases the slot under `workers=1` (a second run's task
starts while the first is parked) and the body resumes ahead of new
ready tasks.
**Done.** Tests pass.

### T033a — `human_input`: ordinal replay after a crash (D44)

**Do.** In `human_input`, when `reopen_or_create` returns a request that
already has an answer: validate it (`pydantic_validator` for form); on
success return it without waiting; on a stale-fit failure log the errors,
append them to the prompt, and open a **new** request at the next
ordinal. A pending existing request is waited on, not re-created.
**Tests.** `tests/requests/test_human_input_replay.py`: three questions,
kill the attempt after two answers (cancel the asyncio task, reset the
row to `ready` like recovery, re-run): the third attempt asks only
question three and gets answers one and two replayed; a replayed form
answer that no longer validates re-asks with errors at ordinal 4; a
retry (new task row) starts its ordinals at 1 and asks afresh.
**Done.** Tests pass.

### T034 — Agent base: `Agent`, `AgentResult`, prompt assembly (A2.3)

**Do.** `athanore/agents/base.py`: `class AgentError(Exception)`;
`@dataclass class AgentResult` (fields of 05 §AgentResult; `ok` property);
`class Agent` with the class attributes of 05 and `async run(prompt="")`
raising `NotImplementedError`; `render_prompt(prompt, ctx) -> str`
assembling the blocks of 19 byte for byte: system prompt, `---`, `## Your
assignment`, `---`, `## Your task` with `curl -H "X-Athanore-Token:
{token}" {api_base}/api/agent/tasks/{id}` lines, `## Asking the operator`
(only when `ask_policy == "http"`), `## Submitting your result` (only
with `output_model`: the curl `POST …/submit` and `json.dumps(model_json_
schema(), indent=2)`); outside a task context the task section is
omitted with a warning. `declare(ctx)` async context manager setting
`ctx.output_model`, `ctx.ask_policy`, `ctx.last_rejection = None` and
restoring the previous values on exit (nested agents).
**Tests.** `tests/agents/test_prompt.py` (port the prompt assertions from
`tests/test_agents.py`): sections present/absent by config; token only
in the header form; no `?token=` or `_token` anywhere.
**Done.** Tests pass.

### T035 — Submissions helpers (A2.3)

**Do.** `athanore/agents/submissions.py`: `validate_submission(model,
payload) -> tuple[ok, errors, normalised]`; `attach(ctx, result) ->
AgentResult` (latest submission via `services.submissions.latest()`,
validated against `ctx.output_model`; missing → `AgentError("agent
finished without a valid submission")`; raw when no model);
`needs_repair(ctx, stop_reason) -> bool` (`end_turn` and model declared
and no valid submission); `repair_prompt(ctx, turn) -> str` quoting
`ctx.last_rejection` errors and the schema.
**Tests.** `tests/agents/test_submissions_unit.py`: attach picks the
latest; repair prompt contains the last errors.
**Done.** Tests pass.

### T036 — Stats: provider protocol and the entry recorder (A2.6, D27, D46)

**Do.** `athanore/agents/stats.py`: `class SessionStats(BaseModel)`
(`model, input_tokens, output_tokens, cost`, all optional); `class
SessionStatsProvider(Protocol)` with `stats(session_id, cwd)` and
`final_stop_reason(session_id, cwd)`; `usage_from_acp(usage) -> dict |
None` (port `build_acp_usage`); `merge_usage(acp, provider)` (ACP wins
for tokens, provider supplies cost); `build_entry(*, node, attempt,
status, model, usage, tool_calls, duration_s, session_id, repair_turns)
-> dict` omitting unknowns; `format_stats_line(entry) -> str` (port);
`async def record_entry(ctx, entry)`: one uow → `log.append(engine,
kind=stats, format_stats_line)`, `tasks.set_stats`, emit `agent.stats`;
guarded so a second call in the same `run()` is a no-op; never raises
(logs).
**Tests.** `tests/agents/test_stats_unit.py` (port the pure parts of
`tests/test_stats.py`: builders, formatter, merge; the session-file
parsing tests move in T039).
**Done.** Tests pass.

### T037 — `FakeACPAgent`, `MockAgent`, `StatsMockAgent`, `FakeStatsProvider` (A2.7)

**Do.** `athanore/testing/fake_acp.py`: port `tests/fake_acp.py` to the
JSON scenario vocabulary fixed in 13 §Fakes (every key listed there,
including `log`/`submit` against the task API and per-node selection via
`ATHANORE_FAKE_SCENARIOS`; unknown keys are an error).
`athanore/testing/scenarios.py`: `scenario(**kwargs) -> list[str]`
returning the `command` for `ACPAgent(command=…)`. `athanore/testing/
mock.py`: `MockAgent(output=None, submit=None, log=None, stream=None,
fail=None)` (no subprocess; `submit=` posts to `ctx.api_base` with the
task token via httpx once the API exists in T045; until then it calls
`services.submissions.accept` directly behind a flag), `StatsMockAgent
(stats=…, fail=False)` calling `record_entry`, `FakeStatsProvider(stats=
…, stop_reason=…)`. `athanore/testing/__init__.py` exports them; delete
the MVP `athanore/testing.py` once `tests/test_agents.py` is ported in
T040 (keep both until then).
**Tests.** `tests/testing/test_fake_acp.py`: the fake speaks
`initialize`/`session/new`/`session/prompt` against a raw ACP client and
honours each scenario key.
**Done.** Tests pass.

### T038 — Policies: permissions, elicitation, ask gating (A2.5, D10)

**Do.** `athanore/agents/policies.py`: `choose_by_kind(options, kinds:
list[str]) -> str | None`; `async resolve_permission(agent, ctx, tool_call,
options) -> str`: `auto_allow` → `allow_once, allow_always`; `auto_deny`
→ `reject_once, reject_always`; missing → `AgentError`; `ask` outside a
context → warn + `auto_allow`; `ask` → `create_agent_request(mode=
options, kind=permission, options verbatim, tool_call=bounded summary
(title, kind, first 500 chars of raw input))`, `wait(timeout=agent.
permission_timeout)`; on `TimeoutError` → `answer_as_engine` with the
option chosen by kind for `permission_timeout_action`. `async
resolve_elicitation(agent, ctx, message, mode, requested_schema) ->
(action, content)`: `decline` policy or URL mode → `("decline", None)`;
form → `form` request with the schema, `json_schema_validator`
registered, wait, `("accept", value)`; timeout → decline.
`ask_allowed(ctx) -> bool`.
**Tests.** `tests/agents/test_policies.py` (port `tests/test_permissions.py`
and `test_elicitation.py` assertions that do not need a subprocess):
reject-first ordering still picks `allow_once`; engine-authored timeout
answer recorded; decline on URL mode.
**Done.** Tests pass.

### T039 — `ACPClient` and the session lifecycle up to the prompt (A2.4)

**Do.** `athanore/agents/acp.py`: `class ACPClient(Client)` (the SDK's
callback interface) forwarding `session_update` chunks to
`ctx.services.stream.append(kind, text)` with the kind mapping of 05
(`agent_message_chunk → text`, `agent_thought_chunk → thought`,
`tool_call → tool_call` counted for stats, `tool_call_update →
tool_result`), `request_permission → policies.resolve_permission`,
`create_elicitation → policies.resolve_elicitation`, `complete_elicitation`
no-op, `fs/*` and `terminal/*` raising `method_not_found`. `class
ACPAgent(Agent)` with the attributes of 05 §Agent classes; `_child_env()`
(scrub `CLAUDE_*`, `CLAUDECODE`, `CLAUDE_PID`, or keep only
`env_allowlist`; then set `ATHANORE_TASK_TOKEN`, `ATHANORE_TASK_URL`;
merge explicit `env`); `_command()` honouring `settings.agent_command`;
`run()` up to and including the prompt: `async with declare(ctx)`, spawn
with `asyncio.create_subprocess_exec(..., stdin=PIPE, stdout=PIPE,
stderr=PIPE)`, stderr pump to structlog DEBUG capped at 64 KiB;
`initialize` (client info `athanore/__version__`); `new_session(cwd)`;
config by category (`_resolve_config_id(session, "model"|"thought_
level")`, rejections logged at WARNING and written as a `notice` chunk);
`prompt(render_prompt(...))` under `asyncio.timeout(self.timeout or
settings.agent_timeout)`; return the raw `PromptResponse` to T039a.
**Tests.** `tests/agents/test_acp_lifecycle.py` on `FakeACPAgent`: full
handshake; config ids resolved by category from the advertised list
(request log) and a rejected id produces a `notice` chunk; text and
thought chunks land with the right kinds; tool calls counted; env scrub
and allowlist (fake echoes its env); `agent_command` override replaces a
subclass's command; permission with reject-first order picks
`allow_once`.
**Done.** Tests pass.

### T039a — `ACPAgent.run()`: repair loop, outcome mapping, cleanup, stats once (A2.4, A2.6)

**Do.** Continue `run()`: repair loop (`needs_repair` → send
`repair_prompt` on the same session up to `max_repair_turns`, emitting
`submission.repair` and a `notice` chunk); outcome mapping (`refusal` /
`cancelled` → failed result with `reason`; provider `final_stop_reason
== "length"` on the final turn → failed `truncated`; else `attach`);
`finally`: `stream.close()`, close the connection, `terminate()` then
`kill()` after 5 s, `record_entry` exactly once with `duration_s`,
`tool_calls`, `repair_turns`, `denied_permissions`. Raise `AgentError`
(`reason` timeout / transport / no_submission) after recording stats.
**Tests.** `tests/agents/test_acp_outcomes.py` on `FakeACPAgent` (port the
subprocess-dependent parts of `test_submissions.py`, `test_acp_stats.py`,
`test_agents.py`): repair loop stops at `max_repair_turns` and the second
submission wins; refusal returns a failed result and does not raise;
truncation via `FakeStatsProvider`; timeout kills the child (no zombie:
`proc.returncode is not None`); stats recorded exactly once on success,
failure, timeout, refusal, and shutdown-cancel.
**Done.** `tests/test_permissions.py`, `test_elicitation.py`,
`test_acp_stats.py` deleted; `tests/fake_acp.py` deleted.

### T039b — Tooling tiers in the façade (A2.10, D63)

**Do.** `ACPAgent.tooling` attribute; in `run()` read `initialize`'s
`mcpCapabilities`; `auto` → `mcp` when `http` is advertised, else `http`;
`mcp` tier passes `mcp_servers=[McpServerHttp(name="athanore", url=
f"{api_base}/mcp/agent", headers=[HttpHeader("X-Athanore-Token", token)])]`
to `new_session`. `render_prompt` emits the tool-agnostic core plus the
tier block of 19; in `mcp`/`native` the submission and ask blocks are
replaced by the one-line variants and the token is absent from the
prompt (asserted). Policies: a permission request whose tool call names
the `athanore` MCP server is answered `allow_once` under `ask` without
opening a request.
**Tests.** `tests/agents/test_tooling.py` on `FakeACPAgent`: `advertise_
mcp` → `mcp` tier, the fake records the server URL and header, and
`mcp_calls` to `append_log` and `submit_result` land through the real
endpoint; no advertisement → `http` tier with the curl block; prompt
contains no token in `mcp`/`native`; the athanore-server permission
request is auto-allowed while a filesystem one still asks.
**Done.** Tests pass.

### T040 — Pi stats provider in `examples/` and the remaining agent tests (A2.8, A2.9)

**Do.** `examples/pi/__init__.py`, `examples/pi/stats.py`: `class
PiSessionStats(SessionStatsProvider)` wrapping the MVP `find_session_file`,
`parse_session_file`, `final_assistant_stop_reason`; `examples/tests/
test_pi_stats.py` receives the session-file tests from
`tests/test_stats.py`. Port `tests/test_stats_workflow.py` and the
remainder of `tests/test_agents.py`, `tests/test_stats.py` to
`tests/agents/`. (No MVP modules to delete: they were never in this
repository, D65.)
**Done.** `uv run pytest examples` and `tests/` green; `tests/test_stats.py`,
`test_stats_workflow.py`, `test_agents.py` deleted.

### T040a — pi extension for the `native` tier (A2.11, D14)

**Do.** `examples/pi/extensions/athanore.ts`: `pi.registerTool()` for
`get_task`, `append_log`, `submit_result`, `ask_operator`, `wait_answer`,
each calling the HTTP API with `ATHANORE_TASK_URL` / `ATHANORE_TASK_TOKEN`
from the environment; descriptions copied from 19; `submit_result` fetches
the schema from `GET /api/agent/tasks/{id}` (add `output_schema?` to that
response, 08) so pi's tool definition shows it. The pi example agents
set `tooling="native"` and the sandbox image copies the extension into
`~/.pi/agent/extensions/`. README in `examples/pi` explains the tier.
**Tests.** `examples/tests/test_pi_extension.py`: the extension file
parses and registers five tools (node smoke via `pi -e` in the sandbox,
skipped without pi); the façade prompt for a `native` agent contains no
curl and no token.
**Done.** Tests pass; smoke run in the sandbox shows `append_log` as a
tool call in the transcript.

### T041 — Phase 2 checkpoint

**Do.** Full suite; `pyright` strict paths clean; 05 and 06 updated with
implementation notes (stderr cap, kill grace period, empty-list return).

---

## Phase 3 — API, CLI, plugin manifest

### T042 — Error model, 422 shape, body-limit middleware, `create_app` (A3.1)

**Do.** `athanore/api/errors.py`: `class ErrorCode(StrEnum)` with the
codes of 08 §Conventions plus `payload_too_large` (record as D53 in 15);
`class ApiError(Exception)(status, code, message, **extras)`; handlers:
`ApiError → JSONResponse({"error", "code", **extras})`,
`RequestValidationError → 422 {"error": "validation failed", "code":
"validation", "errors": [...]}`, engine/requests exceptions mapped
(`NotFound → 404 not_found`, `Conflict → 409 conflict`, `UnknownWorkflow
→ 404 unknown_workflow`, `UnknownNode → 404 unknown_node`, `GraphError →
409 graph_error`, `InvalidOption → 400`, `InvalidAnswer → 422`,
`AlreadyAnswered → 409`, `StaleRequest → 409 stale_request`).
`athanore/api/middleware.py`: `BodyLimitMiddleware(app, limit)` pure ASGI:
reject `Content-Length > limit` with 413 before reading; otherwise wrap
`receive` to count bytes and raise past the limit (respond 413 if
headers not yet sent). `create_app(settings, engine, store, plugins)`:
lifespan (nothing yet), middleware, handlers, routers registered in
later tasks; `state.settings/engine/store/started_at`.
**Tests.** `tests/api/test_errors.py`: each mapping; 413 on a 2 MiB body
with and without `Content-Length`.
**Done.** Tests pass.

### T043 — Auth dependencies, `/api/health`, `/api/me` (A3.2, D47)

**Do.** `athanore/api/deps.py`: `auth_mode(settings) -> "off" | "token"`
(`"token"` when `not is_loopback or require_token`); `async
operator_auth(request)` dependency: no-op in `off`; else require
`Authorization: Bearer` equal (`hmac.compare_digest`) to
`effective_operator_token`, else 401 `unauthorized`; for `GET /api/events`
only, accept `access_token` query param. `async task_auth(task_id,
x_athanore_token: str = Header(...))`: hash, `by_token_hash`, must match
`task_id` and status in `(in_progress, waiting)` else 403 `forbidden`;
returns `TaskRow`. `athanore/api/routers/system.py`: `GET /api/health`
(counts from `engine.pools.snapshot()` and a store query), `GET /api/me`
(`auth`, `authenticated`, `version`, `started_at`, `features: []`). Log
filter that redacts `Authorization` and the `access_token` query.
**Tests.** `tests/api/test_auth.py`: matrix from 13 (loopback plain OK;
`0.0.0.0` bind without token → server refuses to start; with token: 401
without header, 200 with; `require_token` on loopback → 401; task token
valid only for its own task and only while in progress; expired after
`finish`).
**Done.** Tests pass.

### T044 — Response schemas and the workflows router (A3.3)

**Do.** `athanore/api/schemas/*.py`: `RunSummary`, `RunDetail` (with
`outputs`, `stats`), `TaskView` (with `terminal`, `branch`, never
`token_hash`), `LogEntry`, `EventEnvelope` (18), `RequestView`,
`WorkflowOut`, `NodeOut`, `GraphOut`, `SourceOut`, `StreamOut`, request
bodies (`NewRun`, `EditRun`, `Position`, `LogText`, `Rerun`, `Move`,
`SetStatus`, `Answer`), `Ok`, `Created`. `routers/workflows.py`: list/get
(graph, pool, capacity, in_flight, `plugin` placeholder until T049),
`/source` via `inspect.getsourcefile` + `getsourcelines` per node, `POST
/runs` → 201. All operator routers use `Depends(operator_auth)` and the
08 tags.
**Tests.** `tests/api/test_workflows_api.py` via `httpx.AsyncClient
(transport=ASGITransport)`: list shape incl. generations and node
options; 404 on unknown; `/source` returns lines per node; submit → 201
and a `queued` run.
**Done.** Tests pass; snapshot updated.

### T044a — Runs router including `/graph` and `/position` (A3.3, D57, D58)

**Do.** `routers/runs.py`: every row of 08 §Runs. `/graph` per 08 §Graph
semantics: `state` precedence, `live`, `attempts`, `last_task_id`,
`branches` from `branch` frames, `join` and `arrivals` from `JoinRepo.
incomplete`, `edges[].kind` (`forward`/`back`/`join`) and `traversed`.
`/position` per D57. `RunDetail` fills `outputs` from `terminal_tasks`.
**Tests.** `tests/api/test_runs_api.py`: port `tests/test_edit_run.py`, the
API halves of `test_management.py`, `test_pause.py`, `test_run_log.py`,
`test_priority.py`; graph state precedence on a run with a retry
pending; a fan-out run reports branches; a join reports `2 of 3`;
`position {index}` clamps; assert no `token` or `token_hash` key anywhere
in any response (recursive walk).
**Done.** `tests/test_edit_run.py` deleted; ledger rows for the four API
halves ticked.

### T044b — Tasks and requests routers (A3.3)

**Do.** `routers/tasks.py`: get (+ submissions, no token), `/stream`
(`?after&limit`, `live = task in progress`), retry/move/status (409
`conflict` on a join target). `routers/requests.py`: inbox
(`?pending&run`), get, answer → the updated `RequestView` with the 06
error mapping (400 `invalid_option`, 409 `already_answered` /
`stale_request`, 422).
**Tests.** `tests/api/test_tasks_api.py`, `test_requests_api.py`: stream
pagination and `live`; retry/move/status state transitions; every
answer error code; inbox excludes stale.
**Done.** Tests pass; snapshot updated.

### T045 — Agent router under `/api/agent/` (A3.4, D39)

**Do.** `athanore/api/routers/agent.py` with `Depends(task_auth)`:
`GET /tasks/{id}` (title, description from the run, `input = payload`,
the work log without `kind=stats` lines per D56), `POST /log`, `POST /submit` (read `ctx = engine.live.context_
for(id)`; 409 if none; validate against `ctx.output_model` →
`services.submissions.accept` or `reject` + 422 `{errors, schema}`, set
`ctx.last_rejection`), `POST /ask` (403 unless `ctx.ask_policy == "http"`;
`prompt`, optional `options` or `schema` → mode), `GET /requests/{rid}`
(`wait` clamped to 120 s → `poll`). Switch `MockAgent(submit=)` to the
real endpoint.
**Tests.** `tests/api/test_agent_api.py` (port `tests/test_submissions.py`
and `test_ask.py`): 422 with schema; last valid wins; 409 after finish;
ask 403 when off; long-poll returns on answer.
**Done.** `tests/test_submissions.py`, `test_ask.py` deleted.

### T045a — MCP server at `/mcp/agent` (A3.4b, D63)

**Do.** `athanore/api/mcp.py`: an `mcp` SDK server (streamable HTTP)
mounted as a sub-application at `/mcp/agent`, authenticated by the
`task_auth` dependency of T043 (the task is the token's; tools take no
task id). Tools per 08 §MCP: `get_task`, `append_log`, `submit_result`
(input schema read from `engine.live.context_for(task).output_model`
at list-tools time, free object when none; misfit → `isError` result
with `errors` and `schema`), `ask_operator` (present only when the live
context has `ask_policy == "http"`), `wait_answer`. Tool descriptions
reuse the 19 wording. OpenAPI lists the route under `agent` as opaque.
**Tests.** `tests/api/test_mcp.py` with the `mcp` Python client against
the ASGI app: list-tools reflects the declared model; `submit_result`
success and misfit; `append_log` writes with author `agent`; a wrong
token is refused; `ask_operator` absent when the policy is off.
**Done.** Tests pass; snapshot updated.

### T046 — SSE endpoint (A3.5)

**Do.** `athanore/api/sse.py`: `GET /api/events` → `EventSourceResponse
(generator, ping=15)`. Generator: parse `after` (or `Last-Event-ID`),
`run`, `names` (comma-separated globs); `sub = bus.subscribe(patterns)`
**before** replay; replay `events.list_after(after, limit=cap+1)` filtered
by run/names; if `len > cap`: yield `event: resync` and stop replay,
then continue live; track `last_id`; live loop: drop events with `id <=
last_id`, yield `{"id": e.id, "event": e.name, "data": json}` for stored
events and `{"event": "task.stream", "data": …}` without `id` for
ephemeral; on `sub.overflowed` yield `resync`; set header
`X-Accel-Buffering: no`; close `sub` on disconnect.
**Tests.** `tests/api/test_sse.py`: replay then live in one stream; no
duplicate across the replay/live boundary; `names=run.*` filters;
`task.stream` frames lack `id:`; cap exceeded → `resync`; `access_token`
accepted when auth is on.
**Done.** Tests pass.

### T047 — Static SPA, CSP, and CORS (A3.6)

**Do.** `athanore/api/static.py`: mount `athanore/web/dist` at `/` (SPA
fallback to `index.html` for non-`/api` paths), plugin assets mount hook
(used in T070), CSP header from 12 §Plugins on HTML and asset responses;
`CORSMiddleware` only when `cors_origins` is set. Serve a minimal
"build the SPA" page when `dist/index.html` is missing.
**Tests.** `tests/api/test_static.py` (port `tests/test_web_serve.py`):
`/` returns HTML with the CSP header; `/api/nothing` is 404 JSON, not
HTML.
**Done.** `tests/test_web_serve.py` deleted.

### T048 — OpenAPI metadata and snapshot (A3.7)

**Do.** Tags per 08 §OpenAPI; `openapi_extra` security schemes `taskToken`
(apiKey header `X-Athanore-Token`) on the agent router and
`operatorBearer` on operator routers; `Event.name` typed as
`EventName | str` with the enum referenced; `ApiError.code` as
`ErrorCode`. Regenerate `tests/snapshots/openapi.json` and `web/src/api/
gen`. Extend the snapshot test with "every `EventName` appears in the
schema enum".
**Done.** CI contract job green.

### T049 — Plugin declarations, registry, manifest (A3.8, D50)

**Do.** `athanore/plugins/decl.py`: `Route(path, methods, fn)`,
`Action(name, title, scope, confirm, model, fn)`, `Panel(name, slot,
placement, kind, scope, node, source, element, refresh_on)`,
`Handler(event, fn)`, `PanelKind` and `Slot` enums, `PluginError(status,
message)`. Extend `Workflow` (T020) with `route()`, `action()`,
`panel()`, `on()`, `assets=`. `athanore/plugins/registry.py`:
`collect(workflow) -> PluginSpec`; `validate(spec, graph, assets_root)`
with the six checks of 09 §Registration; `manifest_entry(spec) -> dict`
(actions carry `model_json_schema()`; `plugin.*` handler names checked).
**Tests.** `tests/plugins/test_registry.py`: each of the six validation
errors; the manifest shape for a workflow with one of every declaration;
`panel()` is a plain call and returns the `Panel`.
**Done.** Tests pass.

### T049a — Plugin mount, `PluginContext` dependency, `on` dispatch (A3.8)

**Do.** `athanore/plugins/context.py`: `PluginContext` dataclass (`run_id,
task_id, node, workflow, run, task, services, ops`) with the scope rules
of 09 (`workflow`/`global` contexts have no run and only run-independent
services). `athanore/plugins/mount.py`: `mount(app, spec)`: `APIRouter
(prefix=f"/api/plugins/{wf}")` with `Depends(operator_auth)`; the
`PluginContext` dependency resolves `run_id`/`task_id`/`node` query
params and 404s a run of another workflow. `GET /api/plugins` manifest
(builtins first, `_builtin` workflow). `dispatch_handlers(bus, specs)`
subscribes once and calls matching `on` handlers after commit, logging
exceptions.
**Tests.** `tests/plugins/test_mount.py`: a route resolves its context;
a foreign `run_id` is 404; a `global` route gets `run=None` and
`services.log` raises `PluginError(400)`; `on` handler receives
`run.completed`; a raising handler does not affect the engine; manifest
endpoint shape.
**Done.** Tests pass; snapshot updated.

### T050 — Builtin plugin declarations (A3.9)

**Do.** `athanore/plugins/builtin/{overview,log,agent,requests,graph}.py`
each a function `declare(wf_host)` registering on an internal
`BuiltinWorkflow` scope that applies to every run: `overview` (`dashboard`
run pane, `source` route returning `{note, metrics: [TOKENS, COST,
DURATION, POSITION], table: nodes}` plus `kv` meta), `log` (`log` run
pane, source merging `log_entries` and lifecycle events by time,
`refresh_on=["log.appended", "task.*"]`), `agent` (`custom` `<ath-agent-
stream>`), `requests` (`custom` `<ath-requests>` run pane + `global`
pane), `graph` (`custom` `<ath-run-graph>`). Manifest lists them under
`workflow: "_builtin"` first, in this order.
**Tests.** `tests/plugins/test_builtin.py`: manifest order; overview
source totals equal `RunDetail.stats`; log source interleaves.
**Done.** Tests pass; snapshot updated.

### T051 — `Server` host with uvicorn (A1.13)

**Do.** `athanore/server.py`: `class Server(settings=None)`: `register(wf,
pool=None)` (finalize, name checks against `cli.verbs.RESERVED`, pool
names, existing workflows; `collect`+`validate` plugins; `engine.register`),
`async start()` (migrate if `run_migrations`, `is_v0_database` → refuse
with the import hint, `Store`, `Engine.start`, `create_app`, uvicorn
`Server` with `_QuietUvicorn` pattern from the MVP on a free or configured
port, retention loop), `async stop()`, `serve()` (`asyncio.run`, SIGINT/
SIGTERM → stop), `url` property. Refuse to start on a non-loopback host
without an operator token. `Workflow.run(**settings)` builds a `Server`
and serves. `AthanoreServer = Server` alias.
**Tests.** `tests/test_server.py`: start/stop twice in one loop; port 0
picks a free port; reserved name rejected; `wf.run` smoke via a thread.
**Done.** Tests pass.

### T052 — CLI skeleton, client, output (A3.10)

**Do.** `athanore/cli/__init__.py` typer `app`; `cli/verbs.py`:
`RESERVED = {serve, db, token, login, submit, ls, show, logs, stream,
workflows, requests, answer, permit, deny, pause, resume, cancel, rm,
rerun, retry, move, set-status, edit, position, open}`; `cli/client.py`:
`Client(url, token)` over httpx (`transport=HTTPTransport(retries=2)`,
bearer header, `events(after, names)` SSE iterator shared with tests),
config from `--url/--token`, `ATHANORE_URL/ATHANORE_TOKEN`,
`~/.config/athanore/config.toml`; `cli/output.py`: `emit(data, table_
spec, json_flag)` (rich table or JSON); exit codes 0/1/2/3 via a
`main()` wrapper catching `ApiClientError`, `typer.BadParameter`,
`httpx.ConnectError`.
**Tests.** `tests/cli/test_client.py`: exit codes; `--json` output parses.
**Done.** Tests pass.

### T053 — CLI server-side verbs: `serve`, `db`, `token`, `login` (A3.10)

**Do.** `serve [targets...] --host --port --workers --db --no-discover
--public-url --open`: load `module:attr` or `path.py:attr` targets,
discovery hook (T072), read `[pools]`/`[workflows]` from `athanore.toml`,
build `Server`, print URL, `webbrowser.open` on `--open`. `db upgrade |
current | backup <path> | import-v0 <file>` (backup via `sqlite3.
Connection.backup`). `token show | rotate` (write `0600`, create
`.athanore/`). `login <url>` prompts for the token and stores it.
**Tests.** `tests/cli/test_serve.py`: `serve path.py:wf --port 0` starts
and answers `/api/health` (subprocess with a timeout); `token rotate`
mode bits; `db import-v0` on the fixture.
**Done.** Tests pass.

### T054 — CLI inspect verbs (A3.10)

**Do.** `submit`, `ls [--status --workflow --watch]`, `show`, `logs [-f]`,
`stream [-f]`, `workflows`, `requests [run]`, `open [run]`, and the
bare-workflow alias (first positional not in `RESERVED` and present in
`GET /api/workflows`). `--watch` and `-f` use the T052 SSE iterator with
`after=` reconnect. Table specs per verb; `--json` emits the API shape.
**Tests.** `tests/cli/test_inspect_verbs.py` (port the read half of
`tests/test_cli_entry.py`) against a live `Server` on a free port: every
verb once in table and JSON form; alias; `logs -f` sees a live event;
exit code 3 when the server is down.
**Done.** Tests pass.

### T054a — CLI steer verbs (A3.10)

**Do.** `answer <req> <option-id | text | json>` (JSON when the argument
parses as an object, option id when the request is `options`, text
otherwise), `permit [option]`, `deny`, `pause`, `resume`, `cancel`, `rm`
(confirm unless `--yes`), `rerun`, `retry`, `move`, `set-status`, `edit
[--title --description]`, `position up|down|<index>`.
**Tests.** `tests/cli/test_steer_verbs.py` (port the write half of
`tests/test_cli_entry.py`): each verb changes state visible through the
API; `answer` picks the right body shape for each mode; exit code 1 with
the API `error` message on a 409.
**Done.** `tests/test_cli_entry.py` deleted.

### T055 — Port the end-to-end API tests and retire the MVP server (A3.11)

**Do.** `tests/api/test_e2e.py` (port `tests/test_e2e.py`,
`test_api_surface.py`): submit → MockAgent submits → completion via API
and SSE; fan-out via API; requests answered through the API. There is no
MVP teardown here (D65): no flat modules to delete, no `textual` /
`netext` / `textual-dev` to drop, no `ignore_imports` hatch to remove,
and no TUI — it stays in v0 and retires with it (D13, D67).
Write `athanore/__init__.py` as the 02 §Public API surface plus the
deprecated aliases (`warnings.warn` on attribute access via module
`__getattr__`).
**Tests.** `tests/test_public_api.py`: every name in 02 importable;
aliases warn.
**Done.** `find athanore -maxdepth 1 -name "*.py"` lists only
`__init__.py`, `settings.py`, `logging.py`, `workflow.py`, `server.py`;
ledger rows for `test_e2e.py`, `test_api_surface.py` and `test_tui.py`
(retired) ticked.

### T056 — Phase 3 checkpoint

**Do.** Full suite; coverage gates (`graph/engine/requests ≥ 95 %`,
overall ≥ 85 %) enabled in CI; `docs/v1/08` and `09` updated with the
implicit details (state precedence in `/graph`, `_builtin` manifest
workflow, `payload_too_large`).

---

## Phase 4 — SPA core

### T057 — Theme mapping is the first commit (A4.1 prelude, 10 §Design system)

**Do.** Finish `gen-theme.mjs` output: status colour utilities
(`.text-status-ok` … from the 10 table), type scale classes (`text-metric`
15/500, `text-body` 12, `text-row` 11.5, `text-secondary` 11,
`text-kicker` 10.5 uppercase tracking `.12em`), surfaces (`bg-chrome` =
`color-mix(in srgb, var(--color-surface) 45%, var(--color-bg))`,
`bg-zebra` 60 %), `ath-pulse` and `ath-caret` keyframes with a
`prefers-reduced-motion` guard. No glow utility, no scan or flicker, and
no `--radius` override (D71).
Storybook is not used; instead `web/src/dev/Tokens.tsx` renders every
token and component primitive at `/__tokens` in dev only.
**Done.** `pnpm gen:theme` idempotent; `/__tokens` matches the mock's
palette by eye against `Athanore.dc.html`.

### T058 — App shell: router, client state, layout regions (A4.1)

**Do.** TanStack Router with one route `/` and validated search
`{run?: string, pane?: number, overlay?: "palette"|"new"|"library"|
"edit"|"keys"|"task"|"pick-retry"|"pick-move"|"pick-cancel"|"pick-rerun",
task?: number}`. zustand store `usePrefs` (persisted: `listWidth`,
`listCollapsed`, `autoSwitchOnRequest`, `notifications`, `token`)
and `useUi` (transient: focus region). Layout components: `Header`
(brand mark, `__APP_VERSION__` injected from `pyproject.toml` at
build, count placeholders), `RunList` (empty), `Detail` (empty pane bar),
`Footer` (key chips).
**Tests.** Vitest: search param round-trip; prefs persist to
`localStorage` and survive a reload; an invalid `?overlay=` is dropped,
not thrown.
**Dev stack.** `docker compose --profile dev up web` serves Vite with hot
reload on `:5173`, proxying `/api` to the v1 server started with
`docker compose run --rm dev "uv run athanore serve ..."`.
**Done.** `pnpm build` output served by `athanore serve` shows the shell.

### T058a — Splitter and list collapse (A4.1, D71)

**Do.** `Splitter` (`react-resizable-panels`, min 260, max `window − 340`,
5 px handle, width persisted); list collapse to the 30 px `RUNS n` rail
(`listCollapsed`). The CRT chrome is gone from the mock (D71): no
`CrtChrome`, no `crt` preference, no settings toggle.
**Tests.** Vitest: collapse toggles the store and the rail renders the
count; width clamps.
**Done.** Tests pass.

### T059 — API client bootstrap, `/api/me`, query provider (A4.1, A4.9 prelude)

**Do.** `web/src/api/client.ts`: configure the generated fetch client
with `baseUrl: ""`, an auth interceptor adding `Authorization` from
prefs when `/api/me.auth === "token"`, and a 401 interceptor setting
`useUi.needsToken = true`. `QueryClientProvider` with `staleTime: 5000`,
`retry: 1`. `useMe()` query; `AppGate` renders the token screen (T065)
when needed, else the shell.
**Done.** Loopback dev server shows data-free shell without prompting.

### T060 — SSE wrapper and invalidation table (A4.2)

**Do.** `web/src/realtime/sse.ts`: `class EventFeed` over `EventSource`
(`/api/events?after=<lastId>&access_token=…` when auth on); tracks
`lastId` from frames carrying `id`; exponential reconnect 1 s → 30 s;
emits `status: "open"|"reconnecting"|"down"`; on `resync` → clear
`lastId`, `queryClient.invalidateQueries()`; on reconnect refetch
`/api/me` and, if `started_at` changed, refetch `/api/plugins`.
`web/src/realtime/invalidate.ts`: the table of 10 §Realtime; matcher
exact-then-glob (`task.stream` never hits `task.*`); coalescer batching
keys in a 250 ms window; `stream` handler calls `appendStream(taskId,
seqFrom)` which fetches `/api/tasks/{id}/stream?after=` and appends to
the cache rather than refetching. `registerRefreshOn(names, keys)` for
plugin panels. `ServerDownBanner` with countdown; header counts greyed
via a `data-down` attribute.
**Tests.** Vitest: matcher precedence; coalescing merges duplicate keys;
reconnect uses `after=lastId`; `resync` clears the cache.
**Done.** Tests pass.

### T061 — Run list (A4.3)

**Do.** `RunList`: header chips (`all` + one per workflow, accent-tinted
when on), `/` filter input (client-side over title/id), grid rows with
the mock's column template (RUN 8-char id · WORKFLOW · TITLE · STATUS
pill · NODE (+ `⚠` when `pending_requests > 0`) · AGE), zebra, selected
row treatment (flat accent tint, 2 px accent left border), footer
strip `n shown · ↑↓ select · ⏎ focus detail`, collapsed rail `RUNS n`.
Selection writes `?run=`. Header: `n runs · ● k active` with pulse only
when `k > 0`. `useRuns()` from the generated query options, invalidated
by `run.*`/`task.*`.
**Tests.** Vitest: `⚠` appears; filter narrows; pill text and colour
class per status.
**Done.** Live list updates when a run is submitted from the CLI.

### T062 — Pane host: `usePanes`, `PaneBar`, index rules (A4.4)

**Do.** `usePanes(runId)`: manifest (`/api/plugins`) → builtins first,
then the selected run's workflow panels with `slot=run, placement=pane`
(node-slot panels only while `/api/runs/{id}/graph` reports the node
`live`); with no run selected: the `global` panes. `PaneBar`: collapse
toggle, `◀ PANE (i/n) ▶`, dots (`RadioGroup` styled 14×3, accent current
/ accent-800 plugin / neutral-800 builtin), `run <id>` and status pill.
Index persists across selection changes and clamps to the pane count;
`←`/`→` wrap; `1`–`9` jump (keys wired in T067; expose the actions now).
**Tests.** Vitest: pane order for a workflow with two plugin panes; a
node-slot pane appears only when live; clamp on selection change; cycle
wraps; the global panes show with no run.
**Done.** Tests pass.

### T062a — `PaneRenderer` kinds (A4.4, 09 §Panel kinds)

**Do.** `PaneRenderer` switching on `kind`: `markdown` (react-markdown +
gfm, shiki lazy), `kv` (two-column dl), `table` (shadcn `Table`,
click-to-sort), `log` (autoscroll list with `@tanstack/react-virtual`,
sticky "tailing" toggle), `chart` (tiny SVG line/bar, no library),
`dashboard` (note, `MetricGrid`, table), `form` (placeholder until T070),
`custom` (placeholder until T071), unknown → placeholder card. Panel
data via `useQuery` on the panel's `source` path with `run_id/task_id/
node` params; `refresh_on` registered in the invalidation table.
**Tests.** Vitest: each kind renders its sample data from 09; unknown
kind renders the placeholder without throwing; `refresh_on` registers
the right query key; a `source` 500 renders an error card.
**Done.** Overview and log panes render from the builtin sources.

### T063a — Overview renderer (A4.5)

**Do.** `MetricGrid` (TOKENS, COST, DURATION, POSITION), per-node token
bars (accent active, accent-700 others, scaled to the largest node),
`kv` meta (RUN, WORKFLOW, TITLE, STATUS · node, AGE, SESSION, AGENTS,
DESCRIPTION; sources per 10 §Panes), NODES zebra table (NODE · ATT ·
STATUS · TOKENS · DUR; click → task drawer), OUTPUTS list when a run had
more than one terminal branch, `placement=card` panels appended.
**Tests.** Vitest with a `RunDetail` fixture: tiles, bars, the kv fields
including SESSION omitted when no agent ran, OUTPUTS shown only for
multi-branch runs.
**Done.** Tests pass.

### T063b — Log renderer (A4.5)

**Do.** Header `EVENT LOG · n lines · ● tailing/○ complete`, rows `time ·
source · message` merged from the work log and lifecycle events with the
tone mapping of 10 §Panes, composer (`l`) posting `/api/runs/{id}/log`,
`?node=` filter (used by the graph pane), markdown for agent/user
entries.
**Tests.** Vitest: merge order by time; tone classes per kind; the
composer posts and clears; `?node=` filters.
**Done.** Tests pass.

### T063c — Agent stream renderer (A4.5)

**Do.** `<ath-agent-stream>` as a React component registered in the
custom-element table (T071 generalises this); focused task = most recent
in-flight task of the run, override from the task drawer; virtualised
`StreamBlock`s mapping chunk kinds (`notice → system`, `text →
assistant`, `thought → assistant dimmed collapsible`, `tool_call/
tool_result → tool`); blinking caret while `live`; appends from
`task.stream` via `after=seq`.
**Tests.** Vitest: block mapping per kind; append on a `task.stream`
event fetches `after=` and does not refetch the whole transcript; caret
only while live.
**Done.** Tests pass.

### T063d — Requests pane renderer (A4.5)

**Do.** Cards `node → operator` / `agent → operator`, pending first,
timestamp, prompt, then the answer (with author) or the controls slot
(controls arrive in T064); permission cards show the bounded tool-call
summary.
**Tests.** Vitest: ordering; answered card shows author and value;
tool-call summary rendered.
**Done.** Tests pass.

### T063e — Graph rail renderer (A4.5, D32, D62)

**Do.** From `/api/runs/{id}/graph`: nodes in generation order, glyphs
(`✓ ● ✗ ·`, `⋈` for joins), detail column (tokens · duration / `attempt n
· elapsed` / `waiting` / `k of n arrived`), `▼` connectors for forward
edges, `▲` from branch sub-lists into their join, right-hand rail with
`◀` and `loop` label for back edges, fan-out branches as indented
sub-lists keyed by `branches[].from_task` and closed at the join, EDGES
legend (edge / loop / join / gate), SOURCE path, `open definition` →
library overlay; click → log pane filtered; right-click menu rerun /
move (move disabled on joins).
**Tests.** Vitest with three fixtures: linear with a loop-back, fan-out
without a join, fan-out closed by a join; row order, rails, sub-list
nesting, and the `k of n` text.
**Done.** All five panes render `feature_build` and `gamedev` runs
produced on `FakeACPAgent`.

### T064 — Docked request panel, `ActionForm`, inbox (A4.6, D49)

**Do.** `ActionForm`: RJSF `@rjsf/core` + `@rjsf/shadcn` theme with
Nocturne tokens, `validator-ajv8`, `extraErrors` populated from a 422
`errors[]` (`loc` → RJSF path), submit and cancel. `RequestPanel`:
`options` → outlined buttons styled by kind (`allow_*` accent, `reject_*`
destructive, others neutral), `text` → input + send, `form` →
`ActionForm(schema)`; posts `/api/requests/{id}/answer`; toast on 409.
Docked under the agent stream when the focused task has open requests;
same component inside the requests pane cards and the global inbox pane
(newest first, header shows count). Tab title prefix `(n)`; desktop
notification opt-in.
**Tests.** Vitest: nested schema round-trip; 422 maps onto the field;
option kind classes.
**Done.** A permission from `FakeACPAgent` can be allowed from the UI.

### T065 — Token screen and 401 handling (A4.9)

**Do.** `TokenScreen` overlay (same backdrop/panel idiom): input, save to
prefs, retry `/api/me`; shown when `auth === "token" && !authenticated`
or after any 401; SSE URL gains `access_token`.
**Tests.** Vitest: 401 → screen; token stored and sent.
**Done.** Works against `athanore serve --host 0.0.0.0` with a rotated
token.

### T066a — Command palette (A4.7)

**Do.** cmdk in a `Dialog`, `›` input, rows `name · hint · key`; every
operator action and every overlay listed with its key; plugin actions
appended under `plugin: <title>` (from T070).
**Tests.** Vitest: filter narrows; enter runs the action; `esc` closes.
**Done.** Tests pass.

### T066b — New run overlay (A4.7, D34, D57)

**Do.** WORKFLOW chip group, TITLE, DESCRIPTION, POSITION top/bottom
(top → `POST …/runs` then `POST …/position {index: 0}`), read-only ENTRY
NODE from the graph, `⌘⏎` submit, cancel; react-hook-form + zod.
**Tests.** Vitest: posts the right bodies for top and bottom; empty title
blocked; the entry node updates with the chip.
**Done.** Tests pass.

### T066c — Workflow library overlay (A4.7, D35)

**Do.** Left list (name, node count, run count, file), right source
viewer from `/api/workflows/{name}/source` with shiki and node line
anchors; `open definition` from the graph pane lands on the node's line.
**Tests.** Vitest: selection loads source; anchor scrolls.
**Done.** Tests pass.

### T066d — Edit run and pickers (A4.7)

**Do.** Edit run (title, description → `PATCH`); pickers for `t` (retry),
`m` (move: task list then node list), `x` (cancel task), `r` (rerun: node
list) as palette-style lists of the selected run's tasks (node, attempt,
status) with the resulting `POST`.
**Tests.** Vitest: each picker posts the right endpoint and body; move
hides join nodes in the target list.
**Done.** Tests pass.

### T066e — Task drawer and keys overlay (A4.7)

**Do.** Task drawer: payload, result, error, submissions, stats, lineage,
branch; retry / move / set-status actions; "focus stream" button feeding
T063c. Keys overlay: the footer chips expanded. All overlays close on
`esc` and are driven by `?overlay=`.
**Tests.** Vitest: drawer renders a failed attempt with lineage; actions
post; keys overlay lists every binding of 10 §Keyboard.
**Done.** Every operator op of 04 reachable from the UI.

### T067 — Keyboard map and focus scoping (A4.8, D51)

**Do.** `useKeymap()` with the exact table of 10 §Keyboard; suppressed
when `event.target` is an input/textarea/contenteditable or an overlay
owns focus (overlays register their own scope); `a`/`d` only when the
request panel has focus; `D` (shift) opens delete confirm; `^r`
invalidates all; `?` opens keys.
**Tests.** Vitest: `d` in the list does nothing; `D` opens confirm; `a`
answers only with panel focus.
**Done.** Tests pass.

### T068 — Vitest suites and coverage (A4.10)

**Do.** Fill in the unit suites the earlier tasks stubbed: renderers per
kind, `ActionForm` round-trips nested schemas and arrays, invalidation
table precedence and coalescing, SSE wrapper reconnect and `resync`,
keymap scoping. `vitest --coverage` gate ≥ 80 % on `web/src`.
**Tests.** The suites themselves.
**Done.** `pnpm test --run` green; coverage gate in CI.

### T068a — Playwright E2E and the a11y gate (A4.10)

**Do.** `web/e2e/` Playwright config starting `athanore serve` with
`examples/msgtest` and a scenario workflow on `FakeACPAgent` (free port,
tmp db, `ATHANORE_AGENT_COMMAND`). Specs: submit → graph shows progress
→ allow permission → answer `human_input` → completed; reorder via
`position`; pause/resume; server-down banner (kill and restart the
server); shortcuts; inbox with no run selected; a fan-out closed by a
join renders `k of n`. `@axe-core/playwright` a11y ≥ 95 on the dashboard.
CI `web` job runs Playwright (Chromium only).
**Dev stack.** Already done (D68): `WITH_BROWSERS` defaults to 1 and the
image ships chromium, because the driver's `qa` node drives Playwright.
**Done.** CI green with the E2E job.

### T069 — Phase 4 checkpoint

**Do.** `pnpm build` in CI before `uv build`; wheel contains the fresh
SPA; `athanore serve` from a clean venv shows the UI. Update 10 with
deviations found (record in 15).

---

## Phase 5 — Plugin actions, assets, discovery

### T070 — Action execution endpoint and the `form` kind (A5.1)

**Do.** `POST /api/plugins/{wf}/actions/{name}`: validate `input` with
the action model (422 shape), resolve `PluginContext` from `scope`, 404
foreign run, call handler, `PluginError → {status, error, code: "plugin_
error"}`, return JSON. SPA: `form` panel kind renders `ActionForm(schema)`
for the named action; `confirm=true` opens a confirm dialog first;
result toast. Actions also listed in the palette under `plugin: <title>`.
**Tests.** Python: validation, scoping, `PluginError`. Vitest: confirm
flow.
**Done.** Tests pass; snapshot updated.

### T071 — Assets, `custom` panels, `window.athanore` (A5.2)

**Do.** Server: `assets` resolved relative to the declaring module
(`importlib.resources` when packaged), `StaticFiles` at
`/plugins/{wf}/static/`, manifest `assets: [urls of *.js]`. SPA:
`CustomElementHost` injects each asset once as `<script type="module">`,
renders `<element run-id task-id node>`; `window.athanore = {fetch
(bound to /api/plugins/{wf}/ with auth), subscribe(names, cb) (on the
shared `EventFeed`), theme: {tokens}}`; the builtin elements (`ath-agent-
stream`, `ath-requests`, `ath-run-graph`) resolve to the SPA's own React
components via a registry so the host has no hard-coded pane knowledge.
**Tests.** Python: missing assets dir fails registration; traversal
`../` is 404. Playwright: a test plugin element mounts and receives an
event via `subscribe`.
**Done.** Tests pass.

### T072 — Entry-point discovery and `athanore.toml` pools (A5.3)

**Do.** `athanore/plugins/discovery.py`: `discover() -> list[Workflow]`
from `importlib.metadata.entry_points(group="athanore.workflows")`
(`module:attr` or callable). `serve`: `--no-discover` flag; `[pools]`
and `[workflows]` from `athanore.toml` (`Pool(name, n)`; unknown pool
name → exit 2); explicit targets override discovery for the same name;
default pool `Pool("default", workers)` for unbound workflows. Document
precedence in 09/11.
**Tests.** `tests/cli/test_discovery.py` with a fake distribution
registered via a temporary `entry_points` shim.
**Done.** Tests pass.

### T073 — Plugin test workflow and the plugin suite (A5.4)

**Do.** `tests/plugins/fixture_wf.py`: one `route`, one `action` (nested
model), one panel per kind, a `node`-slot panel, an `on`, an `assets`
dir with one `.js`. `tests/plugins/test_suite.py`: manifest complete;
route and action 404 on a foreign run; node liveness flips with task
state; `on` fires after commit; asset served with CSP.
**Done.** Tests pass; coverage of `plugins` ≥ 90 %.

---

## Phase 6 — Examples, docs, release

### T074 — Move `workflow/` to `examples/` and port `feature_build` (A6.1)

**Do.** Write `examples/{feature_build,gamedev,...}` fresh, with v0's
`workflow/` package as the reference; `examples/pyproject.toml`
gains `[project.entry-points."athanore.workflows"]` for each; port
`feature_build`: `Workflow`, `ACPAgent`, `command=["npx","-y","pi-acp@X.Y.Z"]`
pinned to the version in `uv.lock`/current install, `stats_provider=
PiSessionStats()`, node options where the MVP used ad-hoc retries.
`examples/__main__.py` builds a `Server` programmatically (the
"programmatic form" of 11).
**Tests.** `examples/tests/test_feature_build.py` (graph shape, prompts
inlined, models declared).
**Done.** `athanore serve` discovers `feature_build`.

### T075 — Port `gamedev`, `msgtest`, `projects` (A6.1)

**Do.** Same treatment; `gamedev` additionally declares the plugin
panel/action from 09 §Declarations as the showcase (`/words` route,
`override` action, `Words` table pane). `tests/test_gamedev.py` moves to
`examples/tests/test_gamedev.py`.
**Done.** `tests/test_gamedev.py` deleted; `examples/tests` green.

### T076 — Port `claude_acp`, `docker_acp`, `examples/docker` (A6.1)

**Do.** `claude_acp`: `command=["npx","-y","@agentclientprotocol/claude-agent-acp@X.Y.Z"]`,
`model` only, `stats_provider=None`. `docker_acp`: point it at the dev
stack's sandbox rather than a new image — `command=["./scripts/agent.sh",
"pi"]` (D64, D67) — with `permission_policy="auto_allow"` and
`public_url` set for the container. No `examples/docker/` image of its
own: `docker/dev` already is that image.
**Done.** Both import and finalize under `examples/tests`.

### T077 — Live smoke scripts (A6.2)

**Do.** `tests/smoke/{test_pi.py,test_claude.py}` gated on
`ATHANORE_SMOKE=1`, each: start `Server`, submit `msgtest`, wait for
completion, assert a stats line with real token counts. Document in
13 §Live smoke how to run them.
**Done.** Skipped in CI; pass locally against installed adapters.

### T078 — README, docs final pass, deprecation aliases (A6.3)

**Do.** Rewrite `README.md` (install, `athanore serve`, first workflow,
link to `docs/v1`); `DESIGN.md` gets a one-paragraph banner pointing at
`docs/v1`; verify every `AthanoreX` alias warns once; `docs/v1/*` pass
for stale statements found during implementation; add this document's
row to `docs/v1/README.md`.
**Done.** `grep -r "ARTIFICER\|artificer" athanore` returns only the
deprecation shim.

### T079 — Audits, coverage gates, release (A6.4)

**Do.** CI: `pip-audit`, `pnpm audit --audit-level high`; coverage gates
enforced; nightly Postgres job runs the store suite for real (remove the
skip). `uv build`; install the wheel into a clean venv; `athanore serve
examples...:feature_build --port 0`; browse. Bump version `1.0.0`, tag,
push.
**Done.** Tag `v1.0.0` exists; the wheel on a clean machine serves the
SPA and runs `msgtest` on `FakeACPAgent`.

---

## Traceability

| Doc 16 ticket | Tasks here |
|---|---|
| — (dev stack and driver seat, not in 16) | T000 |
| A0.1–A0.7 | T001–T008 |
| A1.1–A1.7 | T009–T018 |
| A1.8–A1.14 | T019–T029 |
| A2.1–A2.9 | T030–T041 |
| A3.1–A3.11 | T042–T056 |
| A4.1–A4.10 | T057–T069 |
| A5.1–A5.4 | T070–T073 |
| A6.1–A6.4 | T074–T079 |

Sequencing changes relative to 16, all recorded in 15 when executed:
the TUI is not deleted at all in this repository — it never lived here
(D65) and retires with v0 (D13, D67); the `payload_
too_large` error code is added; the graph package split (A0.1's
"unchanged" move) is completed in T019 rather than T003 so the MVP
modules keep running through phase 1.
