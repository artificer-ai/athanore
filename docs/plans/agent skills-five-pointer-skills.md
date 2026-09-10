# agent skills — five pointer skills, one generator, one gate

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `AGENTS.md` §Quality bar (no stubs, no demo-grade paths),
§What this repository is (the docs are the spec), §Architecture rules
that must hold (three rules, layering, small core, one wire contract),
§Commands (the gate is `./scripts/test.sh`, D74);
`docs/v1/README.md` (the document map and the MUST/SHOULD conventions —
the skills are an index *into* this map, and this is the file whose job
they extend);
`docs/v1/01-vision-and-scope.md` §The three rules (unchanged),
§Design principles for v1;
`docs/v1/02-architecture.md` §Package layout (what may and may not be
created inside `athanore/`), §Layering rule, §Public API, §Configuration;
`docs/v1/04-engine.md` §Graph DSL, §Node options (metadata seam),
§Routing interpretation, §Fan-in (join nodes), §Scheduling, §TaskContext,
§Waiting on a human, §Programmatic host;
`docs/v1/05-agents.md` §Agent classes, §Tooling tiers: how an agent
reaches its task, §Policies, §Submissions, §Stats entry, §Testing doubles
(`athanore.testing`), §User-land adapters (examples, not shipped);
`docs/v1/06-requests.md` §The model, §Surfaces;
`docs/v1/08-api.md` §Conventions, §Authentication (12 has the model),
§Endpoints, §Events (SSE), §OpenAPI, §Versioning;
`docs/v1/09-plugins.md` §Declarations, §Panel kinds (the renderer
vocabulary), §Slots, §Context and scopes, §Escape hatch: web components,
§Registration and validation, §Mounting, §Builtins are plugins,
§Discovery;
`docs/v1/10-frontend.md` §Stack, §Layout (from the mock), §Panes (cycle
order), §Overlays, §Keyboard, §Realtime and caching, §Plugin renderers,
§Design system (normative);
`docs/v1/11-cli.md` §Server, §Client connection, §Verbs, §Exit codes;
`docs/v1/12-security.md` §Operator token (network binds only), §Task
tokens, §Plugins;
`docs/v1/13-testing.md` §Pyramid, §Contract tests, §CI, §Definition of
done for a feature;
`docs/v1/18-event-payloads.md` §Envelope, §Typing;
`docs/v1/19-agent-prompts.md` §Assembly;
D74 (the gate is one command), D178 (a check only CI runs is a check that
never runs, because this repository has no runner), D180 (the packaging
check enforces an order rather than writing it down), D191 (1) (what
belongs to the gate and what belongs to CI alone).

The precedent this change copies, end to end, is the OpenAPI contract:
`scripts/dump_openapi.py` renders, `tests/snapshots/openapi.json` is
committed, `tests/test_openapi_snapshot.py` asserts the committed bytes
are what the renderer writes, and CI's `contract` job regenerates and
runs `git diff --exit-code`. Read those three files before writing a
line of this task.

## What this change is

A new top-level directory, `skills/`, holding five agent skills — one per
surface someone can build against: workflows, plugins, api, cli, web.
Each is a directory with a `SKILL.md` in the Anthropic Agent Skills
format (YAML frontmatter, `name` and `description`, markdown body), and
each exists so that an agent asked to write a workflow, a plugin, an API
client, a CLI invocation or a change to the SPA can be handed *one short
file* that tells it which of the twenty-one design documents to open and
which shipped code to read — instead of being pointed at `docs/v1/` cold
and reading 9,600 lines to find the four sections it needed.

The constraint that decides every other question: **a skill is a pointer,
never a copy.** `AGENTS.md` says the documents are the spec; a skill that
restates a rule becomes a second spec that drifts, and a drifted skill is
worse than no skill because an agent believes it. So this change is
really the design of an anti-drift contract, and the skills are what it
protects:

- **A `SKILL.md` is hand-written and states no fact that is written down
  somewhere else.** It names things and cites where they are defined. It
  contains no event names, no field lists, no signatures, no endpoint
  tables, no option defaults.
- **Every fact a skill would otherwise have restated is generated** into
  `skills/<skill>/reference/*.md` by one script, `scripts/gen_skills.py`,
  from the code and from the committed OpenAPI snapshot — and is gated
  the way `tests/snapshots/openapi.json` is: a pytest test asserts the
  committed bytes are what the renderer writes, and CI's `contract` job
  regenerates and diffs.
- **Every pointer a `SKILL.md` makes is checked by a test.** A cited path
  must exist in the tree; a cited section must be a real heading in the
  document it names; a code fence must be a verbatim excerpt of a file it
  names. A pointer that rots fails the gate in the same run that rots it.

That third bullet is the load-bearing one. Generation alone would only
protect the half of a skill that is machine-derivable; the interesting
half — *which section answers which question* — is judgement, and cannot
be generated. Making the citation form machine-checkable is what keeps
that half honest, and it is why this plan fixes the citation syntax (an
architectural decision) while leaving headings, ordering and wording to
the implementer (a detail one).

## The four open questions, settled

These become one row in `docs/v1/15-decisions.md` — **D213**, the next
number (D212 is the last). Write it as a numbered row in the style of
D191, with the six parts below.

### 1. `skills/` is repo-only. It ships in the sdist and not in the wheel, and `pyproject.toml` is not touched

A skill in this design is a set of paths into `docs/v1/`, `examples/`,
`workflows/`, `athanore/` and `web/`. The wheel carries `athanore/` and
`athanore/web/dist` and nothing else, so a skill installed from a wheel
would be a directory of dangling pointers — precisely the failure mode
the whole design exists to prevent. Making the pointers resolve from a
wheel would mean force-including `docs/v1/**` (924 KB of markdown,
including the 4,000-line build order and the per-task plans) into the
package, and creating paths under `athanore/` that
`docs/v1/02-architecture.md` §Package layout does not name — a
specification change this task is fenced against.

The sdist already carries `skills/` for free: hatchling's default sdist
is everything the tree holds that git does not ignore, which is how
`docs/`, `AGENTS.md` and `README.md` are in it today. Nothing in
`pyproject.toml` is added, changed or removed by this task. `README.md`
says v1 is installed from a checkout ("there is no git remote and nothing
has been uploaded"), and a checkout is exactly where these pointers
resolve, so the decision costs nothing today. Record the revisit
condition in the row: if athanore is published with a docs site or a
public remote, the pointer form (not the skills) is what changes.

### 2. You install a skill by copying or symlinking its directory into your agent's skills directory

No CLI verb, no entry point, no environment variable, no submodule.
`docs/v1/11-cli.md` §Verbs is a closed list and adding to it is a
specification change; an entry point would make skill discovery a runtime
feature of the package, which the brief puts out of scope; an environment
variable would be a discovery mechanism this repository invented for
agents that do not read it.

What every skill-aware agent does read is a directory. So the install is
one line, and `skills/README.md` is where it is written:

```sh
ln -s "$PWD/skills/athanore-workflows" ~/.claude/skills/athanore-workflows
```

...or a `cp -r` for an agent that will not follow a symlink, or the same
two paths under a project's `.claude/skills/`. The symlink is the form to
lead with, because a symlink into the checkout is what keeps a skill's
pointers pointing at the checkout it was installed from — which is the
one thing an installed copy can get wrong.

Two consequences the implementer must honour:

- **Every path in a `SKILL.md` is written relative to the checkout root**
  (`docs/v1/09-plugins.md`, `workflows/feature/files.py`), never relative
  to the skill file and never absolute. Each `SKILL.md` says so once, in
  a single line near the top, and says where that root is: the directory
  two levels above the skill directory in the checkout the skill was
  installed from.
- **A skill directory is the unit of installation**, so it must be usable
  when it is the only one installed. Its `reference/` files are its own;
  cross-skill pointers are allowed (they are checkout-relative, so they
  resolve exactly as well as the doc pointers do), but no skill may
  *depend* on another being installed.

### 3. Both: hand-written pointers in `SKILL.md`, generated facts in `reference/`

The split is the rule stated above, and it is what makes "never a copy"
enforceable rather than aspirational. A hand-written list of event names
in a skill is a copy that drifts silently; a generated one cannot drift,
because the gate regenerates it. So the answer is not "pointers only" —
that would make the skills thin to the point of uselessness — but
"pointers, plus a generated appendix, and nothing in between".

### 4. A `SKILL.md` carries four kinds of content, and the plan fixes the contract, not the layout

The brief puts headings, section names and style out of scope, and they
stay out of scope: the implementer chooses them. What this plan fixes is
what must be *in* the file, because that is what the reviewer and the
test check:

1. **Frontmatter**: `name`, equal to the directory name; `description`,
   one sentence that says both what the skill covers and when an agent
   should load it (this is the only part of the file most agents read
   before deciding to open it, so it is the highest-value sentence in the
   skill).
2. **What the surface is, in a few sentences, naming its three core
   concepts.** No normative language: an assertion here is a citation
   with prose around it.
3. **The seams** — the named extension points of that surface, one line
   each, each ending in a citation. `AGENTS.md` says new capability
   attaches to an existing seam, so the list of seams is the most
   valuable thing a skill can hand an agent that is about to invent a
   fourth rule.
4. **Where to read and what to copy**: the citation table (a question an
   author actually asks → the section that answers it) and the paths to
   working code in the tree. The citation table is the skill's real
   payload. Write the rows as questions, not as a table of contents —
   "how do I fan out and join?" → `docs/v1/04-engine.md` §Fan-in (join
   nodes) is worth ten times "04 is the engine".

### 5. Skill directories carry the `athanore-` prefix

`skills/athanore-workflows/`, `athanore-plugins`, `athanore-api`,
`athanore-cli`, `athanore-web`. Two reasons, and they are the same
reason: a skill name is global in the agent that installs it, so a skill
called `workflows` or `api` in a user's `~/.claude/skills` says nothing
about whose it is and collides with the next tool that ships one; and the
format wants `name` to match the directory, so a prefixed name with an
unprefixed directory would have to be renamed on install — which is a
step to get wrong. Prefixed on both sides, the install is a copy with no
rename. This is a departure from the brief's literal
`skills/{workflows,plugins,api,cli,web}` and it is the only one; record
it in the row.

### 6. `skills/athanore-web` has no generated `reference/`

The other four surfaces are Python-introspectable or OpenAPI-derived. The
SPA's facts — the pane cycle, the renderer registry, the keyboard map —
live in TypeScript, and a Python script that parsed `web/src` to restate
them would be a second, weaker copy of what `docs/v1/10-frontend.md` and
the source already say. The web skill is therefore pointers only, and it
points at two things that are *already* generated and already gated:
`web/src/api/gen` (from the OpenAPI snapshot) and
`web/src/styles/theme.css` (from `docs/v1/design/nocturne.css`, via
`pnpm -C web gen:theme`). Say in the skill that both are generated and
must never be hand-edited — that is a fact about the tree an agent will
otherwise get wrong on its first edit.

## Files and what each does

### 1. `skills/README.md` — what a skill is here, and how to install one

The directory's front door and the only place the install commands are
written. It says: what these are (pointers into `docs/v1/`, not a second
spec); the five skills with one line each and a link to each `SKILL.md`;
the install command in its symlink and copy forms, for a user directory
and for a project directory; the anti-drift contract in three sentences
(hand-written pointers are checked, facts are generated, the gate
enforces both) and the one command that regenerates,
`uv run scripts/gen_skills.py`; and a "do not restate the spec here"
instruction to whoever edits a skill next.

`tests/test_skills.py` asserts every skill directory is linked from this
file, so a sixth skill that nobody can find is a red gate.

### 2. `skills/athanore-workflows/SKILL.md` — the authoring surface

The one someone writing their first workflow loads. Its three core
concepts are the three rules of `docs/v1/01-vision-and-scope.md` §The
three rules (unchanged) — signature is the graph, return value is the
routing, exception is the failure policy — and the guardrail that there
is never a fourth.

Seams to name (each with its citation): node options
(`docs/v1/04-engine.md` §Node options (metadata seam)); `join=True`
(§Fan-in (join nodes)); pools and priority (§Scheduling); an object
awaited inside a body — an agent (`docs/v1/05-agents.md` §Agent classes),
`human_input()` (`docs/v1/06-requests.md` §The model), the narrow
services on `TaskContext` (`docs/v1/04-engine.md` §TaskContext); the
declarations a workflow carries (pointing at the plugins skill); and
`Workflow.run()` / `Server` (§Programmatic host).

Questions its citation table must answer, at minimum: how edges are
inferred; what a return value may be and what each form does; what
happens when a node raises, and what `NonRetryable` changes
(§Failure classes (rule 3, refined)); which clock a timeout uses
(§Timeouts (which clock, which error)); how a fan-out is joined; how an
agent is declared and what `output_model` buys (`docs/v1/05-agents.md`
§Submissions); how an agent reaches its own task
(§Tooling tiers: how an agent reaches its task); what an agent may and
may not do (it never moves a task); how to ask a human; how to test a
workflow without a model (§Testing doubles (`athanore.testing`) and
`docs/v1/13-testing.md` §Fakes).

Working code to point at: `README.md` §A first workflow (two nodes, no
agents); `workflows/rps.py` (this repository's own smallest workflow —
`human_input`, a loop-back edge, a real output, no agent anywhere);
`workflows/feature/` (the multi-node workflow with agents, pools, a join
and plugins that builds this repository); `examples/pi/agent.py`
and `examples/claude_acp/`, `examples/docker_acp/` (vendor `ACPAgent`
subclasses, user-land by `docs/v1/05-agents.md` §User-land adapters
(examples, not shipped)); `athanore/testing/` (the doubles).
Say plainly which of these ship (`examples/` is a distribution) and which
are this repository's own operating workflows (`workflows/`).

### 3. `skills/athanore-plugins/SKILL.md` — the plugin surface

Three core concepts, from `docs/v1/09-plugins.md`: the four declarations
(§Declarations); scope follows ownership (§Context and scopes — a
workflow's panels show on its runs, its actions validate against its
runs, its routes mount under its name); and `PluginContext` as the one
thing a handler is handed.

Seams: `@wf.route`, `@wf.action`, `wf.panel(...)`, `@wf.on(...)`; the
panel kinds and the `custom` escape hatch with `assets=`
(§Escape hatch: web components); the slots and `placement`
(§Slots); `services` and `ops` on the context; the `plugin.` event
namespace (`docs/v1/18-event-payloads.md` §Typing); entry-point discovery
(§Discovery).

Questions: which declaration to reach for; what a panel `source` must
return for each kind; where a panel appears and when a `node` slot is
live; what a handler gets in `workflow`/`global` scope and which services
refuse there; why an out-of-scope id is a 404 and never a 403; how a
custom element reaches its routes (`window.athanore`); how a plugin is
authenticated (`docs/v1/12-security.md` §Plugins — a plugin has no auth
model of its own).

Working code: `athanore/plugins/builtin/` (the built-in panes are
plugins, `docs/v1/09-plugins.md` §Builtins are plugins);
`workflows/feature/files.py` and `workflows/feature/static/files.js`
(four routes and two `custom` panels — the whole escape hatch, with the
element on the other side of it); `workflows/feature/cron.py` and
`workflows/feature/static/cron.js`.

### 4. `skills/athanore-api/SKILL.md` — the wire contract

Three core concepts: one wire contract, generated (OpenAPI from the code,
the TypeScript client from OpenAPI, both committed — `docs/v1/08-api.md`
§OpenAPI); two credentials, an operator bearer and a header-only task
token that reaches one task (§Authentication (12 has the model),
`docs/v1/12-security.md` §Task tokens); and the event stream as the only
push (§Events (SSE)).

Seams: nothing here is extended by adding a route to `athanore/api` — a
new surface is a plugin route (point at the plugins skill). What this
skill offers instead is *use*: the endpoint groups, the error shape and
its `code` enum, ids and pagination (§Conventions), the size caps
(§Sizes), the versioning rule (§Versioning), and the two ways an agent
reaches the API (the REST routes and `/mcp/agent`).

Questions: how to authenticate as an operator on a loopback bind versus a
network bind; what a task token may do; how to subscribe to events and
resume with `after=`; what an error body looks like; what to regenerate
after a route changes, and that `tests/snapshots/openapi.json` and
`web/src/api/gen` are generated and gated.

Working code: `tests/snapshots/openapi.json` (the whole contract, in one
file); `web/src/api/client.ts` and `web/src/api/gen/`;
`athanore/cli/client.py` (a working Python client of this API);
`examples/pi/extensions/athanore.ts` (an agent-side client of the agent
surface).

### 5. `skills/athanore-cli/SKILL.md` — the operator command line

Three core concepts, from `docs/v1/11-cli.md`: `athanore serve` takes
`module:wf` targets and is the composition root's command line (§Server);
every other verb is a client of the HTTP API and finds its server the
same way (§Client connection); every read verb takes `--json`, so the CLI
composes with `jq` (§Verbs).

Questions: how to serve one workflow and how to serve several; where the
database and `athanore.toml` are looked for (`docs/v1/02-architecture.md`
§Configuration and §`athanore.toml` layout); how to declare pools; how to
answer a request from a terminal, and how `answer` resolves its argument
against the request's mode; what each exit code means (§Exit codes); what
is deliberately not there (§Not in v1).

Working code: `README.md` §The CLI; `athanore/cli/`;
`workflows/__main__.py` (a real `serve` target registering the repository's
own workflows on their pools).

### 6. `skills/athanore-web/SKILL.md` — the SPA

Three core concepts, from `docs/v1/10-frontend.md`: one screen with a
pane cycle (§Layout (from the mock), §Panes (cycle order)); everything
realtime is SSE invalidating query caches, never a second source of truth
(§Realtime and caching); and the design system is normative, generated
from the mock's tokens (§Design system (normative), and
`docs/v1/21-design-refresh.md` §Type scale for what a call site may
write).

Seams: a plugin panel is how a workflow gets UI (§Plugin renderers, and
the plugins skill); a pane kind is the renderer vocabulary; a custom
element is the escape hatch. Say what is *not* a seam: hand-editing
`web/src/api/gen` or `web/src/styles/theme.css`, both generated.

Questions: which commands run the SPA and its suites (`AGENTS.md`
§Commands); where a pane lives and how one is added; how the keyboard map
is defined (§Keyboard); what the accessibility floor is
(§Accessibility and quality); how auth works in the browser
(§Auth in the browser); how to regenerate the client and the theme.

Working code: `web/src/panes/kinds/` (one file per renderer),
`web/src/realtime/`, `web/src/plugins/`, `web/e2e/`.

### 7. `scripts/gen_skills.py` — the one generator

Mirrors `scripts/dump_openapi.py` in shape and in docstring style: a
module-level `render()` per output (or one `render(target)` returning the
exact text of a named file, plus a `TARGETS` mapping path → renderer),
and a `main()` that writes every one of them and prints what it wrote.
The test loads this file by path, exactly as `tests/test_openapi_snapshot.py`
loads the dumper, so the renderer under test is the one CI runs.

Determinism is the whole point, as it is there: no timestamps, no version
numbers, no absolute paths, no dictionary ordering that can vary between
runs. Enum members keep declaration order (it is meaningful, and the
OpenAPI snapshot already treats it as contract); everything else is
sorted. Every file ends with a trailing newline and **begins with one
marker line**:

```
<!-- Generated by scripts/gen_skills.py. Do not edit. -->
```

`scripts/` is dev machinery, not a package, and nothing in `athanore/`
may import it. It imports `athanore` and reads
`tests/snapshots/openapi.json`; it must not start a server, touch a
database or reach the network.

The outputs, exactly:

**`skills/athanore-workflows/reference/`**

- `public-api.md` — every name in `athanore.__all__`, with what it is
  (class, function), its signature from `inspect.signature`, and the
  first line of its docstring. Resolve through the module `__getattr__`
  (D148), and do not include the deprecated aliases: they are not in
  `__all__` precisely because they are names you had to have typed.
- `node-options.md` — the keyword parameters of `Workflow.node()` with
  their types and defaults, and `Pool`'s fields. This is the metadata
  seam of `docs/v1/04-engine.md` §Node options, read off the code that
  implements it.
- `agents.md` — the class attributes an `Agent` / `ACPAgent` subclass may
  set, with types and defaults, and the fields of `AgentResult`. Read
  from the annotations, not written out.
- `events.md` — every `EventName` member, grouped by the comment blocks
  of `athanore/events/names.py` or by name prefix, each with the field
  names and types of its payload model from `athanore/events/payloads.py`
  (`ENVELOPES` is the mapping to walk). One line per event. This is the
  vocabulary `docs/v1/03-domain-model.md` §Event vocabulary fixes and
  `docs/v1/18-event-payloads.md` types; the api and web skills cite this
  file rather than generating a second copy.

**`skills/athanore-plugins/reference/`**

- `declarations.md` — the `Route`, `Action`, `Panel` and `Handler`
  declarations from `athanore/plugins/decl.py`: field names, types,
  defaults; plus the `Slot` and `PanelKind` enum members and the
  `Placement` literals.
- `context.md` — the attributes of `PluginContext`, the services it
  exposes and their methods, and the refusals `PluginError` carries,
  from the code.

**`skills/athanore-api/reference/`**

- `routes.md` — one row per operation in `tests/snapshots/openapi.json`:
  method, path, tag, `operationId`, summary, and which credential it
  declares. Sorted by path then method. Generated from the committed
  snapshot rather than from `create_app()`, so that a stale snapshot
  fails one check (the OpenAPI one) instead of two, and so this
  generator never has to build an application.
- `error-codes.md` — the `ErrorCode` enum from `athanore/api/errors.py`,
  in declaration order.

**`skills/athanore-cli/reference/`**

- `commands.md` — the command tree of `athanore.cli.app`, walked through
  `typer.main.get_command(app)` as a click `Group`: command name,
  arguments, options with their defaults, and the one-line help. Plus the
  exit codes of `docs/v1/11-cli.md` §Exit codes if they exist as an enum
  in the code; if they do not, leave them to the `SKILL.md` as a citation
  — do not hand-write them into a generated file.

**`skills/athanore-web/reference/`** — does not exist (§6 above).

### 8. `tests/test_skills.py` — the contract, asserted

New suite, in the style of `tests/test_openapi_snapshot.py` and
`tests/test_ci_workflows.py` (both of which assert facts about the tree
rather than about a running system). It carries the same `STALE` message
pattern: a failure names the command that fixes it,
`uv run scripts/gen_skills.py`.

What it asserts:

1. **The five skills are the five skills.** The directories under
   `skills/` are exactly the five names, each holding a `SKILL.md`, and
   each is linked from `skills/README.md`.
2. **Frontmatter.** Every `SKILL.md` opens with a YAML block carrying
   `name` and `description` and nothing this plan did not name; `name`
   equals the directory name; `description` is one non-empty line within
   the format's length limit.
3. **Freshness.** Every file under a `reference/` directory is one
   `scripts/gen_skills.py` writes, its bytes equal what `render()`
   returns, and rendering twice gives the same text. No file under
   `reference/` is missing and none is orphaned.
4. **The marker.** Every generated file starts with the marker line; no
   `SKILL.md` or `skills/README.md` does.
5. **Paths resolve.** Every checkout-relative path a skill file cites
   exists in the tree.
6. **Sections resolve.** Every cited section is a heading in the document
   cited beside it.
7. **Code fences are excerpts.** Every fenced block in a `SKILL.md` is
   preceded by a source marker naming a file, and the block's text
   appears verbatim in that file. (`skills/README.md` is exempt: its
   fences are the install commands, which are not excerpts of anything.)

The citation form the test parses — fixed here because it is the
mechanism, not the styling:

- A **path citation** is a checkout-relative path in inline code:
  `` `docs/v1/09-plugins.md` ``. The test takes every inline-code span
  that looks like a path (contains `/`, no spaces) and asserts it exists.
  A span that is meant as code and not as a path — `wf.node(...)`,
  `run.completed` — will not match, and the implementer should keep it
  that way rather than adding an escape.
- A **section citation** is a path citation followed by a space and
  `§Section name`, running to the end of the line, a comma, a semicolon
  or a closing parenthesis: `` `docs/v1/04-engine.md` §Fan-in (join
  nodes)``. To cite two sections of one document, write two citations —
  one `§` per citation, so the parse has no ambiguity to resolve.
- The heading match strips the leading `#`s and surrounding whitespace,
  and compares against the heading's leading text up to a run of two or
  more spaces — `docs/v1/05-agents.md` and `docs/v1/19-agent-prompts.md`
  both carry headings with a trailing aside after a long gap
  (`## Your task                       omitted outside a task context`),
  and a citation names the heading, not the aside.
- A **source marker** is an HTML comment on the line before a fence,
  naming one path: `<!-- from: workflows/rps.py -->`.

Write these three rules into `skills/README.md` as well: the next person
to edit a skill needs to know what the test will hold them to.

### 9. `.github/workflows/ci.yml` and `tests/test_ci_workflows.py`

The `contract` job grows one command and one path:

```yaml
      - name: regenerate
        run: |
          ...
          uv run --no-sync scripts/gen_skills.py
      - name: snapshot and client are fresh
        run: git diff --exit-code tests/snapshots web/src/api/gen skills
```

`tests/test_ci_workflows.py::test_contract_job_checks_the_generated_client_is_fresh`
asserts that diff line verbatim and must be updated in the same commit;
add `scripts/gen_skills.py` to `test_the_contract_jobs_generators_exist`
beside the other generators. Keep the job unconditional — a step with an
`if` fails `test_contract_work_is_not_conditional`.

**`scripts/test.sh` is not changed.** The gate's coverage of freshness is
the pytest test, exactly as it is for the OpenAPI snapshot: pytest
already runs, and D74 says the gate is one command. The CI job's `git
diff` is the second half of the same check, and D178's requirement — that
no check exist only on a runner — is satisfied by the pytest test being
the one that can fail locally.

### 10. `README.md` (root) — one line in the layout, one bullet in the docs

`skills/` is a new top-level directory; nothing currently tells a reader
it exists. Add it to the `## Layout` tree with a one-line gloss, and a
bullet under `## Documentation` pointing at `skills/README.md` and saying
what it is in one sentence. That is a pointer, not a restatement, and it
is how anyone finds the directory at all.

**`AGENTS.md` is not changed.** These skills are for someone building
*against* athanore; `AGENTS.md` is for someone building athanore, and it
already routes that reader to `docs/v1/` and the task plan. Adding a
second index there would be the drift this change exists to prevent.
**No file in `docs/v1/` is changed except `15-decisions.md`**, which
gains the D213 row and nothing else.

## What this change does not do

- It does not add a CLI verb, an entry point, an environment variable or
  any runtime discovery of skills. Nothing in `athanore/` is imported by
  the skills and nothing in `athanore/` learns they exist.
- It does not touch `pyproject.toml`, the wheel or `scripts/check_wheel.py`.
- It does not add, move or edit anything under `examples/`, `workflows/`
  or `web/`; those are cited, not modified.
- It does not edit any specification document. A skill that finds a
  document wrong or silent raises it — it does not fix it here, and it
  does not route around it by writing the answer into the skill.
- It adds no sixth skill and no per-document skill. Five surfaces, five
  skills; the map of the twenty-one documents stays `docs/v1/README.md`'s
  job.

## Verification

- `./scripts/test.sh` green, with `tests/test_skills.py` in it.
- `uv run scripts/gen_skills.py && git diff --exit-code skills` clean on
  a fresh checkout, and dirty after a deliberate edit to a `reference/`
  file (check it, then revert).
- A deliberately broken citation — a renamed section, a deleted path, an
  invented heading — fails `tests/test_skills.py` with a message that
  names the file and the citation. Do this once for each of the three
  kinds before you call the suite done; a checker that passes everything
  is the one failure mode this design cannot survive.
- Install one skill the way `skills/README.md` says, in a scratch
  directory outside the checkout, and open it as an agent would: every
  path in it resolves from the checkout root, and the frontmatter
  `description` is enough to decide whether to load it.
- `ruff check .`, `ruff format --check .` and `pyright` clean on
  `scripts/gen_skills.py` and `tests/test_skills.py`.

## Exit condition

`skills/` holds a `README.md` and five skill directories; every fact in
them is generated by `scripts/gen_skills.py` and every pointer in them is
checked by `tests/test_skills.py`; the gate is green; CI's `contract` job
regenerates the skills and diffs them beside the OpenAPI snapshot and the
TypeScript client; `docs/v1/15-decisions.md` carries D213 with the six
choices above; and the root `README.md` says the directory exists.
