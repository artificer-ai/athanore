# AGENTS.md

Instructions for anyone (human or agent) working in this repository.

## Quality bar

This is a production application, not a prototype. Every task ships the
real feature.

- No proof-of-concept code, no demo-grade paths, no "good enough for now".
  What lands is what runs in a release.
- No stubs, no `TODO` left behind, no `pass` where behaviour belongs, no
  hard-coded sample data standing in for a real code path, no silently
  narrowed scope. If a task names behaviour, implement all of it.
- No mocked or faked behaviour outside tests. `FakeACPAgent` is a test
  fixture, not a shortcut.
- Errors are handled, not swallowed. Edge cases named in the specs are
  implemented, not deferred.
- If a task looks too large, do it anyway, in full. Splitting it is a
  change to `docs/v1/17-serial-task-plan.md`, not a decision to make
  silently mid-task.
- **If you do not have enough information to build the full feature, ask.**
  The specs in `docs/v1/` are the source of truth; if they are silent or
  ambiguous and the boring choice is not obvious, stop and ask rather than
  guessing or shipping a reduced version. Record the answer in
  `docs/v1/15-decisions.md`.

## What this repository is

Athanore: an orchestrator for code-defined AI agent workflows over the
Agent Client Protocol. The design is complete and implementation is
starting. Everything that matters is specified in `docs/v1/`:

- Read `docs/v1/README.md` first. It maps the twenty documents and the
  conventions they use. MUST / SHOULD / MAY carry RFC 2119 meanings.
- `docs/v1/17-serial-task-plan.md` is the build order: one serial list of
  tasks (`T001`...), each naming the ticket it belongs to, the files it
  touches, the tests it adds, and its exit condition.
- `docs/v1/15-decisions.md` is the decision log. If you make a choice the
  docs did not, add a row there with the reason.

## Current state of the tree

- Phases 0 to 5 of `docs/v1/14-migration-and-phasing.md` have landed: the
  package of 02 §Package layout is built (store, engine, requests, agents,
  the API and its plugin host, the CLI, `server.py`), the SPA in `web/`
  ships in the wheel, and `examples/` carries the six example workflows.
  Where the build is exactly is read from the `**Status.** Done.` lines of
  `docs/v1/17-serial-task-plan.md`, never from this paragraph.
- This repository has **no MVP code** — the MVP lives in the neighbouring
  `athanore` checkout and is the behavioural spec, not a coexisting
  codebase (D65). Tasks that say "port `tests/test_x.py`" mean: write the
  v1 test informed by that file and tick its row in
  `docs/porting-ledger.md`.
- The package layout and the per-module responsibilities are in
  `docs/v1/02-architecture.md` §Package layout. Create modules there, not
  elsewhere.
- Work on a branch per change, cut from `main` — `feat/<task-id>` for a
  task, a short descriptive name (`docs/readme-badges`) for anything
  else — and land it through a pull request on `origin`
  (`artificer-ai/athanore`) once the PR's CI is green (D68, D260). The
  PR is merged with a merge commit, so `main` reads as one merge per
  change with its work underneath. `main` is never committed to or
  pushed to directly, and nothing lands without a PR, prose included:
  the PR list is the record of what landed and why, however automated
  the work was. The steps are under *Landing a change*.
- The dev stack (`compose.yaml`, `docker/dev/`, `scripts/`) is here, not in
  a separate repository as T000 assumed (D64). It is dev machinery: no
  task may make `athanore/` depend on it.

## Working a task

1. Take the next unfinished task in `docs/v1/17-serial-task-plan.md`. A
   finished task carries a `**Status.** Done.` line; add one to the task
   you finish, in the same commit, so the plan says where the build is
   without anyone reading the log (name the commit only when you already
   know its sha — `git log --grep "^T012:"` finds it otherwise). Tasks are
   serial: do not skip ahead and do not have two half-finished.
2. Read the task's **Do**, **Tests**, and **Done** blocks and every spec
   section it cites, plus `docs/plans/<task-id>*.md` if one exists — that
   is the implementation plan for the task, and it fences the scope
   against the tasks either side. Do only that task.
3. Implement, adding tests at the lowest layer that can express the
   behaviour (`docs/v1/13-testing.md` §Pyramid).
4. Run the gate until it is green (see Commands). The run that counts
   is CI on the pull request, which is the gate on a runner (`ci.yml`);
   run it locally while iterating, in full or `-k` narrowed, so the PR
   does not go red for something a minute at the keyboard would have
   caught. A change that touches only prose the gate neither builds nor
   tests — `docs/v1/`, `docs/plans/`, `AGENTS.md`, `CLAUDE.md`,
   `TODO.md` — needs no local gate; `docs/site/`, `skills/` and
   `README.md` are built or tested by it and do.
5. One commit per task, on the task's branch, message prefixed with the
   task id: `T012: ...`. The merge commit onto `main` carries the same
   prefix. **The message is plain.** No `Co-Authored-By`, no
   `Claude-Session`, no "Generated with", no attribution line of any
   kind, whatever tool wrote the code; the author and committer are the
   operator's own git identity. A harness that adds such lines is to be
   configured not to, not humoured.
6. Definition of done (`docs/v1/13-testing.md`): tests pass;
   `tests/snapshots/openapi.json` regenerated if the wire contract changed;
   a row in `15-decisions.md` if a choice was made; the document that
   specifies the behaviour updated if it changed.

## Landing a change

Every change, a task or a one-line README edit, lands the same way. The
commands are the whole procedure; an agent runs them as written.

```sh
git checkout -b feat/T012 main             # or docs/<topic>, fix/<topic>
# ...commit on the branch...
git push -u origin HEAD
gh pr create --fill                        # title = the commit subject, body = its message
gh pr checks --watch                       # CI is the gate; wait for it
gh pr merge --merge --delete-branch \
  --subject "$(gh pr view --json title -q .title)" \
  --body "$(gh pr view --json body -q .body)"  # a merge commit, never squash or rebase
git checkout main && git pull origin main  # the branch is gone; main has the merge
```

- **CI green is the condition for merging.** `gh pr merge` on a red or
  still-running PR is not done. If CI is red, fix it on the branch, push,
  and wait again; the PR carries the history of the attempt.
- **Merge commits only.** Squash would flatten the task's commit;
  rebase would lose the merge that says where a change starts and ends.
  `--subject` and `--body` give the merge commit the PR's title and
  body — GitHub's own default is `Merge pull request #N from ...`,
  which is why they are not optional — so the title carries the
  `Txxx:` prefix when the change is a task.
- **The PR body is plain**, like the commit message: what changed and
  why, no attribution lines, no checklists, no template.
- **Delete the branch on merge.** `main` plus the PR list is the whole
  record; a merged branch adds nothing to it.
- `main` after the pull is the only place to start the next branch
  from. An agent that finds itself on `main` with uncommitted work
  branches first (`git switch -c`), it does not commit.

## Commands

Everything runs in the dev stack: one image (`docker/dev/Dockerfile`)
behind every service in `compose.yaml`, so the gate a human runs and the
gate an agent runs are the same gate.

The `scripts/` wrappers work in both places. On the host they hand the
work to the container; inside the container they do it. One command is
therefore correct wherever you are, and an agent never has to know which
side of the boundary it is on.

```sh
./scripts/run.sh                           # serve the app on 127.0.0.1:4002
./scripts/docs.sh                          # serve the docs on 127.0.0.1:8000
./scripts/docs.sh build                    # ...or build them, as the gate does
./scripts/test.sh                          # the gate
./scripts/test.sh -k settings              # arguments reach pytest
./scripts/dev.sh "uv run ruff check ."     # any one command, in the container
./scripts/dev.sh                           # an interactive shell in it
./scripts/agent.sh pi                      # an ACP agent on stdin/stdout
./scripts/build.sh                         # rebuild after editing the image
./scripts/build.sh --reset                 # ...and drop a wedged venv/cache
```

First use writes `.env` (paths, uid/gid, the docker gid — all derived
from the machine) and builds the image. `.env` is git-ignored;
`.env.example` documents every key. **Secrets never go in it**: the
agents read `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` and
`CLAUDE_CODE_OAUTH_TOKEN` from the shell that starts compose.

### In the container

`./scripts/dev.sh` opens a shell at the checkout with uv and a managed
Python 3.13, node 22, pnpm, git, sqlite3, jq, ripgrep, the docker CLI,
and both agents on `PATH`. In there, run the tools directly:

```sh
uv sync --all-packages --all-groups --all-extras   # deps (workspace incl. examples/)
uv run pytest -q                           # Python tests
uv run ruff check . && uv run ruff format --check .
uv run pyright                             # strict on graph, engine, store
uv run lint-imports                        # layering contracts (from T005)
uv run mkdocs build --strict -f docs/site/mkdocs.yml   # the docs site, as the gate builds it
uv run mkdocs serve -f docs/site/mkdocs.yml            # 127.0.0.1:8000, live reload
uv run scripts/gen_docs.py                 # the site's generated reference
```

There is no compose service for the docs site and none is wanted:
`./scripts/docs.sh` hands the work to the container like every other
wrapper, and every service uses host networking, so the site it serves
is at `127.0.0.1:8000` from the host whichever side you start it from.
`docs/site/` is the published site, for whoever is *using*
Athanore; `docs/v1/` is the specification and is deliberately not
published (D214).

`./scripts/test.sh` runs exactly this set, skipping the steps whose
config does not exist yet and naming what it skipped. **It is the
definition of green** — no task adds a separate `scripts/gate.sh`
(D74). It does hand over to `./scripts/gate.sh` if one exists, so you
can drop a local override in beside it, but nothing in the plan
creates one.

From T007 onward (`web/` scaffold):

```sh
pnpm -C web install
pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test && pnpm -C web build
pnpm -C web gen:theme                      # regenerate theme.css from docs/v1/design/nocturne.css
docker compose --profile web up web        # Vite on 127.0.0.1:5173, from the host
```

From T068a onward the gate also runs the Playwright suite, which starts
an `athanore serve` per test with `FakeACPAgent` behind every agent:

```sh
pnpm -C web exec playwright test           # all of web/e2e
pnpm -C web exec playwright test run.spec.ts --workers=1
```

From T008 onward (OpenAPI contract):

```sh
uv run scripts/dump_openapi.py && pnpm -C web gen
git diff --exit-code tests/snapshots web/src/api/gen
```

From T014 onward (the Postgres store variants):

```sh
docker compose --profile pg up -d postgres # ATHANORE_TEST_PG_URL is already set
./scripts/dev.sh "uv run pytest -m postgres"
```

Three things about the container are load-bearing:

- **The checkout is mounted at its own host path**, and every service
  uses host networking. A `cwd` and a task API URL therefore mean the
  same thing on both sides — which is what lets a workflow on the host
  spawn an agent in a container, or the reverse.
- **uv's environment and cache live outside the checkout**
  (`/home/agent/venv`, named volumes), so a host `.venv` — useful for
  your editor — and the container's environment never collide. The gate
  only ever uses the container's.
- **Files the container writes are yours.** The image is built with your
  uid/gid, so a commit made by an agent in the container is a normal
  file on the host.

And one about git worktrees. The wrappers tell the checkout that owns
the stack (`ROOT`: `.env`, the compose project, the volumes) from the
tree the work is in (`TREE`), and they differ inside a worktree of this
repository: `git worktree add .worktrees/<name>` gives you a second
tree on its own branch, and `./scripts/test.sh` run from it tests
*that* tree, in the container, in a uv environment of the worktree's
own (`/home/agent/venvs/<name>`, on the `athanore-venvs` volume). A
worktree must be under the checkout — `.worktrees/` is git-ignored for
it — because that is what the container mounts. The build workflows
work this way (D263): every run gets a worktree, so your checkout is
never checked out, dirtied or merged into by a run, and you can keep
working in it while one is in flight.

### Dispatching agents into the container

`./scripts/agent.sh <pi|claude>` speaks ACP (JSON-RPC over stdio) with an
agent inside the container. It is a command line, so it is also what an
`ACPAgent` subclass sets:

```python
class Builder(ACPAgent):
    command = ["./scripts/agent.sh", "pi"]      # or "claude"
```

That one line works from either side. A workflow running on the host gets
a sibling container per agent (`docker compose run --rm -T agent-pi`); the
same workflow running under `./scripts/run.sh` spawns the adapter as an
in-process subprocess. The container is the guardrail either way, so these
agents run with `permission_policy="auto_allow"` (05 §User-land adapters).
`compose.yaml` is the one definition of that sandbox, so there is
nothing to keep in step.

Every service, the agents included, mounts your `~/.gitconfig`, so a
commit an agent makes carries your identity and nothing else — the
work log and the `Txxx:` prefix say what a run did; the history does
not name the tool. `.claude/settings.json` in the checkout (git-ignored,
per machine) turns Claude Code's own `Co-Authored-By` trailer off for
the containerised agent, which reads it because its `cwd` is the
checkout.

Authenticating them, once each:

- **pi** reads `OPENROUTER_API_KEY` from the shell. `docker/dev/pi/` holds
  the baked `models.json` / `settings.json` (OpenRouter by default, a LAN
  llama-server as the free-but-flaky alternative); edit those and rebuild
  to change models.
- **Claude Code** keeps its own credentials on the `athanore-claude`
  volume — the host `~/.claude` is deliberately *not* mounted. Run
  `./scripts/dev.sh "claude setup-token"` once, or export
  `ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN` before starting compose.

### The build workflows

`python -m workflows` serves two seats that maintain this repository
(`workflows/feature/`, `workflows/quick/`), each in a worktree of its
own, each landing through a pull request as §Landing a change says:

```sh
athanore submit feature "T090" "..."     # rewrite, plan, implement, gate, review, QA, publish, merge
athanore submit quick "MIT license" "..."  # implement (sonnet), gate, publish, merge
```

`feature` is for a change worth judging three times before `main`;
`quick` is for one that is not — a file, a badge, a config line — and
its only verdicts are the gate and CI. Neither pushes anything until
its verdicts are in: `publish` — the push, the PR and the CI wait — is
the step after the last of them (D269). Which one a change is, is the
operator's call at submission; a `quick` run that turns out to need a
plan or a review stops with its worktree and branch intact, to be
resubmitted as a `feature`. What the build workflows have in common —
the sandbox, the deterministic steps, the agent base class — is
`workflows/shared/`, which no workflow package is imported by and none
imports another. A finished run removes its worktree and
branch; a failed or halted one leaves both to be read, and its PR if it
got as far as `publish`.

Verify the wire without a workflow:

```sh
echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' \
  | ./scripts/agent.sh pi
```

Host `~/.pi/agent/sessions` is mounted in, so pi's session JSONL is
readable and `[stats]` lines carry real token counts (05 §Stats).

## Architecture rules that must hold

- **Three rules only.** Signature is the graph, return value is the
  routing, exception is the failure policy. New capability attaches to an
  existing seam (node metadata, an object awaited inside a body, a
  declaration on the workflow). Never add a fourth rule.
- **Layering, arrows point down only:**
  `api, cli, plugins.builtin` over
  `plugins.mount` over `plugins.context` over
  `engine, requests, agents, plugins.registry` over
  `store, events, graph, settings, logging, plugins.decl`. Every name in a tier is an
  **independent sibling**: peers within a tier may not import each other,
  and the only imports allowed are arrows down a tier. `graph` imports
  nothing from the package. `store` never imports `engine`. `agents` reaches the store only
  through `TaskContext`. `workflow.py` and `plugins.registry` are the
  only modules that import both `graph` and `plugins.decl`. Enforced by
  import-linter.
- **Small core.** Nothing in `athanore/` depends on pi, Claude, or Docker.
  Vendor adapters and example workflows live in `examples/`.
- **One wire contract.** The HTTP + SSE API is the only way in for the SPA,
  the CLI, agents, and plugins. OpenAPI is generated from code; the
  TypeScript client is generated from OpenAPI and committed.
- **Durable by default.** Every state change is a transaction. Every
  transaction that matters emits an event from the vocabulary in
  `events/names.py`, mirrored to a TypeScript union. A UnitOfWork never
  spans an await on a node body, an agent, or a request wait.
- **Local first.** Loopback binds need no operator auth. Non-loopback binds
  require the operator token. Task tokens are header-only and never appear
  in operator responses.
- **Real data only.** Stats and status never zero-fill or estimate. Unknown
  is omitted.
- **Retries belong to the engine** (rule 3). Clients get connection-level
  httpx retries at most. Never retry inside a node body's agent call on the
  engine's behalf.
- **Agent prompts are inlined text** on agent classes. No templates. The
  kickoff, ask, submission, and repair blocks are byte-exact per
  `docs/v1/19-agent-prompts.md`; the fake ACP agent parses them.
- **Agents never move tasks.** They submit values; the node body routes.

## Stack

Fixed by `docs/v1/02-architecture.md` §Library choices. Do not substitute.

- Python 3.11+ (D66; the dev stack and CI's default are 3.13). `StrEnum`
  and `asyncio.timeout` set the floor — do not reach below them, and do
  not use a 3.12+ feature (PEP 695 generics, `@override`) without moving
  the floor first. uv, hatchling. FastAPI + uvicorn, pydantic v2,
  pydantic-settings (`ATHANORE_*` env, `athanore.toml`).
- SQLAlchemy 2.0 **Core** (async, no ORM) + Alembic; aiosqlite by default,
  asyncpg behind the `postgres` extra. SQLite in WAL mode.
- sse-starlette, httpx, `agent-client-protocol`, `mcp`, python-ulid,
  structlog, typer + rich.
- Tests: pytest, pytest-asyncio (`asyncio_mode = "auto"`), hypothesis,
  respx, freezegun. `FakeACPAgent` is the only agent CI runs.
- Lint and types: ruff (line length 88, `E,F,I,UP,B,ASYNC`), pyright
  (standard; strict on `graph`, `engine`, `store`), import-linter.
- Frontend: Vite, React 19, TypeScript strict, TanStack Router + Query,
  Tailwind v4, shadcn/ui, react-hook-form + zod, RJSF, cmdk, Phosphor icons,
  JetBrains Mono, Vitest + Testing Library, Playwright. Package manager
  is pnpm.

## Conventions

- "Operator" is the human running Athanore. "Agent" is an ACP subprocess.
  "Node body" is the Python function a node runs. A "seam" is an existing
  extension point.
- IDs are ULIDs. Event names, error codes, and status values are enums on
  both the Python and TypeScript sides.
- The design mock in `docs/v1/design/` is the reference for layout and
  copy; `docs/v1/10-frontend.md` §Design system is the normative spec.
  `web/src/styles/theme.css` is generated from `nocturne.css`; never
  hand-edit it.
- Do not commit secrets. `operator_token` lives in `.athanore/token`
  (git-ignored) and is refused in `athanore.toml`.
- Commit messages carry no agent attribution — no `Co-Authored-By`,
  `Claude-Session` or "Generated with" lines — and no trailers at all
  beyond what git itself writes. Whoever runs the tool is the author.
- `docs/v1/20-carried-findings.md` holds the ACP findings and permission
  decisions the other documents cite, so `docs/v1/` is self-contained.
