# docs site — MkDocs Material under `docs/site/`, generated reference, published from `main`

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `AGENTS.md` §Quality bar (no stubs, no demo-grade paths, no
narrowed scope), §What this repository is (the docs are the spec),
§Architecture rules that must hold (small core — nothing in `athanore/`
grows a dependency for this; one wire contract), §Commands (the gate is
`./scripts/test.sh`, D74), §Conventions;
`docs/v1/README.md` (what `docs/v1/` is: the specification, RFC 2119, for
whoever is *building* Athanore — the reader this site is deliberately not
for);
`docs/v1/01-vision-and-scope.md` §What Athanore is, §The three rules
(unchanged), §MVP feature inventory (what v1 MUST preserve) — the site's
feature narrative is drawn from here;
`docs/v1/02-architecture.md` §Package layout, §Public API
(`athanore/__init__.py`), §Configuration and §`athanore.toml` layout (the
settings table this change generates), §Observability;
`docs/v1/04-engine.md` §Graph DSL, §Routing interpretation, §Fan-in (join
nodes), §Scheduling, §Running an attempt, §Waiting on a human, §Operator
operations (`engine.ops`), §Recovery on startup, §Programmatic host;
`docs/v1/05-agents.md` §Agent classes, §Tooling tiers: how an agent
reaches its task, §Policies, §Submissions, §Stats entry, §Testing doubles
(`athanore.testing`), §User-land adapters (examples, not shipped);
`docs/v1/06-requests.md` §The model, §Surfaces;
`docs/v1/07-storage.md` §Migrations, §Retention, §Backups (the deployment
page);
`docs/v1/08-api.md` §Conventions, §Authentication (12 has the model),
§Endpoints (and its `### Events (SSE)`), §OpenAPI, §Sizes, §Versioning;
`docs/v1/09-plugins.md` §Declarations, §Registration and validation,
§Mounting, §Wire contract, §Builtins are plugins, §Discovery;
`docs/v1/10-frontend.md` §Design system (normative) — for the palette the
site borrows, and for the line this change must not cross: the design
system is normative for the SPA, and `web/src/styles/theme.css` is
generated and never hand-edited;
`docs/v1/11-cli.md` §Server, §Client connection, §Verbs, §Exit codes;
`docs/v1/12-security.md` §Posture: a local tool, §Operator token (network
binds only), §Task tokens, §Beyond the LAN, §Hygiene (the deployment
page);
`docs/v1/13-testing.md` §Pyramid, §Contract tests, §CI, §Definition of
done for a feature;
`docs/v1/18-event-payloads.md` §Envelope (what the generated event page
renders);
D74 (the gate is one command), D178 (a check only CI runs is a check that
never runs, because this repository has no runner), D191 (1) (what
belongs to the gate and what belongs to CI alone), D211 (`plugin_cdns`),
D213 (the six things `skills/` decides — this change is its sibling and
reuses its machinery).

**The precedent this change copies, end to end**, is the one D213 named:
`scripts/dump_openapi.py` renders → `tests/snapshots/openapi.json` is
committed → `tests/test_openapi_snapshot.py` asserts the committed bytes
are what the renderer writes → CI's `contract` job regenerates and runs
`git diff --exit-code`. `scripts/gen_skills.py`, `skills/*/reference/`
and `tests/test_skills.py` are the second application of it. This is the
third. **Read all three before writing a line**, and read
`scripts/gen_skills.py` twice: half of this task is factoring its
renderers out so that the site and the skills are one generator with two
front ends, which is the question `TODO.md` asked to be settled before
either of them was built and which shipped unsettled with `skills/`.

## What this change is

A built, navigable, searchable documentation site for **someone who has
just installed Athanore** — install, quickstart, writing a workflow,
dispatching agents, asking a human, running and steering runs, writing a
plugin, the CLI, the HTTP and SSE API, deployment — plus a reference
section that is generated from the code and the committed OpenAPI
snapshot rather than written by hand. It lives at `docs/site/`, builds
with MkDocs and Material, is a step of `./scripts/test.sh`, and publishes
to GitHub Pages on every push to `main`.

The constraint that decides every other question, and the sibling of the
one D213 turned on: **the site restates no rule.** `docs/v1/` is the
specification; a site that paraphrased a MUST would be a second
specification, and the second one drifts. So the split is hard and there
is nothing in between:

- **Every fact with a default, a name, a signature, a field list, a
  status code or a wire shape is generated** into
  `docs/site/src/reference/` by `scripts/gen_docs.py`, from the package
  and from `tests/snapshots/openapi.json`, and is gated the way the
  OpenAPI snapshot is.
- **Every hand-written page is narrative**: it shows how to do a thing,
  with runnable examples, and it states no default and no field list of
  its own — where the exact vocabulary is wanted it links to the
  reference page beside it.
- **`docs/v1/` is not published and is not linked from any page.** One
  nav entry, defined in `mkdocs.yml` and not in a page, points at the
  design documents in the repository for the reader who wants the spec.

That is the audience separation, and it is machine-checked rather than
remembered: no page under `docs/site/src/` may contain the string
`docs/v1`, and no page may carry an RFC 2119 keyword in the capitalised
form `docs/v1/README.md` §Conventions gives them.

## The six open questions, settled

These become one row in `docs/v1/15-decisions.md` — **D214**, the next
number (D213 is the last). Write it as a numbered row in the style of
D191 and D213, with the seven parts below (the six questions, plus the
generator-sharing answer `TODO.md` asked for).

### 1. Tool: MkDocs with Material for MkDocs. Not Zensical, not Sphinx, not Starlight

`mkdocs>=1.6` and `mkdocs-material>=9.5`, in a new `docs` dependency
group. It is the boring choice and it is the right one here: Python
native, so `uv sync --all-groups` — which the gate already runs — is the
whole install and no second node application enters the tree; it renders
the markdown this repository already writes; it has search, navigation
and anchors out of the box; and its `--strict` mode with mkdocs 1.6's
`validation:` block turns a broken internal link, a missing anchor and a
file that is not in the nav into a non-zero exit, which is what makes the
gate step below worth having.

**Zensical is refused for now, with a reason that is a date and not a
judgement**: it is the same team's successor to Material and it is at
`0.0.60` on PyPI — pre-1.0, with a plugin and hooks story that is still
moving. A gate step is not the place for that. The migration is cheap
when it is ready, and this plan keeps it cheap: everything under
`docs/site/src/` is plain markdown, the generated pages are markdown
files on disk rather than a build-time plugin, and the only Zensical-
shaped work would be `mkdocs.yml` and the one hook. Say exactly that in
D214, so the next person does not re-litigate it.

Sphinx is refused because the Python API is explicitly not the
centrepiece here (see 5), and Starlight/Docusaurus because a second pnpm
application in the tree buys a closer visual match to Nocturne at the
cost of a second toolchain in the gate.

### 2. Location: `docs/site/`, self-contained, like `web/`

```
docs/site/mkdocs.yml          the config; docs_dir: src, site_dir: build
docs/site/hooks/openapi.py    one hook: publish the OpenAPI snapshot at /openapi.json
docs/site/src/**              the pages (hand-written) and reference/ (generated)
docs/site/build/              the built site, git-ignored
```

Not a root `mkdocs.yml`: the root already carries `pyproject.toml`,
`compose.yaml`, `pnpm-workspace.yaml`, `AGENTS.md`, `CLAUDE.md`,
`DESIGN.md`, `README.md` and `conftest.py`, and `web/` is the precedent
for a self-contained subtree with its own config and its own build
output. `docs/` is the documentation root of this repository —
`docs/v1/` the spec, `docs/plans/` the plans, `docs/site/` the published
site — and one more sibling there says what the tree means better than
one more file at the root.

`docs_dir: src` rather than `docs/site/docs`, because `docs/site/docs/`
is a path nobody can say out loud.

### 3. Gate: mandatory, in `./scripts/test.sh`

A `docs` step runs `mkdocs build --strict`, between `lint-imports` and
the `web/` block, probed for its config the way every other step of that
file is probed for its table:

```sh
step docs "$([ -f docs/site/mkdocs.yml ] && echo yes || echo no)" \
  uv run --no-sync mkdocs build --strict -f docs/site/mkdocs.yml
```

The probe is the file's convention (a checkout without the config names
the skip rather than failing); in this tree the config exists, so the
step always runs. This is not the Playwright case: Playwright is probed
for a *browser*, which is a 100 MB download a bare checkout may not
have, and `mkdocs` is in the environment `sync_python` already prepared.
D178's reason applies with full force — this repository has no runner, so
a docs build only `ci.yml` performs is a docs build that first goes red
in front of a reader.

The freshness of the generated pages is not this step's job: it is
`tests/test_docs_site.py`'s, in the `pytest` step, exactly as
`tests/test_skills.py` covers `skills/`.

### 4. Publish: every push to `main`, from a new `.github/workflows/pages.yml`

Not release tags. The site documents the code on `main`; a tag-only site
is stale between releases, and this repository tags rarely enough that
the gap would be measured in months. `workflow_dispatch` too, so a
publish can be forced without a commit.

The build in `pages.yml` is the same command the gate and CI run, and
`ci.yml` gets its own `docs` job so the build is checked on pull requests
as well — a publish workflow that runs only on `main` is not a check.

### 5. Auto-generation: nine pages, and the line is "any fact with a shape"

Generated into `docs/site/src/reference/`, committed, freshness-gated:

| Page | From |
|---|---|
| `python-api.md` | `athanore.__all__` — names, signatures, one-line summaries |
| `node-options.md` | the `@wf.node()` keyword options |
| `agents.md` | `Agent` / `ACPAgent` attributes and methods, `AgentResult` |
| `events.md` | `athanore/events/names.py` + `athanore/events/payloads.py` |
| `plugins.md` | `athanore/plugins/decl.py` declarations + `PluginContext` |
| `cli.md` | the typer command tree |
| `http-api.md` | `tests/snapshots/openapi.json` |
| `errors.md` | `athanore/api/errors.py` |
| `settings.md` | `AthanoreSettings` and `Retention` |

Everything else is narrative. The rule that draws the line: **if a
reader could be wrong about it after a release, it is generated.**
Defaults, field lists, signatures, endpoint tables, event names, error
codes and option names all qualify; "what a join node is for" does not.

**No `mkdocstrings`**, and no Python API beyond the index above: full
docstring rendering is out of scope in the brief, and the public surface
of `athanore/__init__.py` is fourteen names — an index with signatures
and first lines is what a workflow author needs, and it is what the
renderer already in `scripts/gen_skills.py` produces.

### 6. Audience separation: the site is narrative, `docs/v1/` is not published, and both halves are checked

Stated above and enforced in `tests/test_docs_site.py`. Nothing in
`docs/v1/` is copied, excerpted, or partially regenerated into the site.
The overlap that does exist — the root `README.md`'s quickstart — is
resolved by keeping `README.md` the short form and making the site the
long one, with `README.md` linking to the site.

### 7. The generator is shared: `scripts/_reference.py`, two front ends

`TODO.md` asked whether the skills and the site share a generator "before
building any of them", and `skills/` shipped before the answer. The
answer is **yes, at the body**: the facts are the same facts and only the
framing differs, so the rendering of each fact set moves into
`scripts/_reference.py` and each script supplies its own marker, its own
H1 and its own lede.

- `scripts/_reference.py` (new) holds the helpers and one body renderer
  per fact set, each returning `list[str]` with no title and no lede.
- `scripts/gen_skills.py` keeps `MARKER`, `TARGETS`, `render()` and
  `main()` and its ledes, and calls into `_reference` for the bodies.
- `scripts/gen_docs.py` (new) does the same with its own marker and
  ledes, plus the two renderers that are the site's alone (the detailed
  HTTP reference and the settings table).

**Hard constraint: the refactor changes no byte under `skills/`.**
`uv run scripts/gen_skills.py && git diff --exit-code skills` must be
clean on the first run after it. If a body renderer cannot be moved
without changing its output, the move is wrong, not the output.

## Files and what each does

### 1. `pyproject.toml` — the `docs` dependency group

```toml
[dependency-groups]
docs = [
    "mkdocs>=1.6",
    "mkdocs-material>=9.5",
]
```

A group of its own rather than more names in `dev`, so `uv sync --group
docs` is a sentence and the group is named in `AGENTS.md`. The gate and
every CI job already sync `--all-groups`, so nothing else changes. Run
`uv lock` and commit `uv.lock`. Note in D214 that `pip-audit` now covers
these two trees as well.

### 2. `docs/site/mkdocs.yml` — the config

Fixed by this plan (the implementer chooses wording, not shape):

- `site_name: Athanore`; `site_description` is `pyproject.toml`'s
  `description`, verbatim: *Code-defined AI agent workflows over the
  Agent Client Protocol*.
- `site_url: https://scrussell24.github.io/athanore/` and
  `repo_url: https://github.com/scrussell24/athanore`,
  `repo_name: scrussell24/athanore`. **This is a guess and the one guess
  in this plan**: the checkout has no git remote today (`git remote -v`
  is empty) and `README.md` says v1 is tagged here and uploaded nowhere.
  The owner is taken from the operator's git identity. Both values are
  in one file; say so in D214 so that a real remote is a two-line change.
  `edit_uri: ""` — no per-page edit links until the remote is real.
- `docs_dir: src`, `site_dir: build`, `strict: true`.
- `validation:` — `nav.omitted_files: error`, `nav.not_found: error`,
  `links.absolute_links: error`, `links.unrecognized_links: error`,
  `links.anchors: error`. This is what makes the gate step mean
  something.
- `theme: name: material`, dark only (`palette.scheme: slate`, no
  toggle — a light theme is out of scope in the brief), `font.text:
  Inter` and `font.code: JetBrains Mono` to match Nocturne
  (`docs/v1/design/nocturne.css` `--font-body`, `--ath-font-mono`),
  features `navigation.sections`, `navigation.top`, `navigation.tracking`,
  `toc.follow`, `content.code.copy`, `search.suggest`, `search.highlight`.
- `plugins: [search]`. No others.
- `markdown_extensions:` `admonition`, `attr_list`, `md_in_html`,
  `tables`, `toc` (with `permalink: true`), `pymdownx.details`,
  `pymdownx.superfences`, `pymdownx.highlight` (with
  `anchor_linenums: true`), `pymdownx.inlinehilite`, `pymdownx.tabbed`
  (with `alternate_style: true`).
- `extra_css: [assets/extra.css]`, `hooks: [hooks/openapi.py]`.
- `nav:` explicit and complete, in the order below.

**Constraint: no `!!python/name:` YAML tags** (so no `pymdownx.emoji`
config block and no custom `superfences` fences). `tests/test_docs_site.py`
reads this file with `yaml.safe_load`, and a config only mkdocs can parse
is a config no test can check.

The nav:

```yaml
nav:
  - Home: index.md
  - Install: install.md
  - Quickstart: quickstart.md
  - Guide:
      - Writing a workflow: guide/workflows.md
      - Dispatching agents: guide/agents.md
      - Asking a human: guide/human-in-the-loop.md
      - Runs, retries and capacity: guide/runs.md
      - Writing a plugin: guide/plugins.md
      - The command line: guide/cli.md
      - Driving the API: guide/http-api.md
      - Deployment: guide/deployment.md
  - Reference:
      - Python API: reference/python-api.md
      - Node options: reference/node-options.md
      - Agents: reference/agents.md
      - Events: reference/events.md
      - Plugins: reference/plugins.md
      - Command line: reference/cli.md
      - HTTP API: reference/http-api.md
      - Error codes: reference/errors.md
      - Settings: reference/settings.md
  - Design documents: https://github.com/scrussell24/athanore/tree/main/docs/v1
```

That last entry is the **only** place `docs/v1` is named anywhere in the
site, and it is in the config rather than in a page precisely so the "no
`docs/v1` in `src/`" test can be exact.

### 3. `docs/site/hooks/openapi.py` — the snapshot, published

An `on_files` hook that adds `tests/snapshots/openapi.json` to the built
site as `openapi.json`, using `File.generated(config, "openapi.json",
abs_src_path=...)`. Fifteen lines and a docstring saying why it is a hook
and not a committed copy: the snapshot is 200 KB of generated JSON that
changes with every wire change, and a second copy in the tree would
double that diff and add a way for the two to disagree. If the snapshot
is missing, raise — a site that silently ships no `openapi.json` is worse
than a red build.

The generated `reference/http-api.md` links to it as `../openapi.json`,
which mkdocs resolves against the file the hook added.

### 4. `docs/site/src/**` — the nine hand-written pages

The implementer writes the copy; this plan fixes the page list, the remit
of each page and the rules every page obeys. **Rules, all four checked by
`tests/test_docs_site.py`:**

1. No capitalised RFC 2119 keyword (`MUST`, `MUST NOT`, `SHOULD`,
   `SHOULD NOT`, `SHALL`, `REQUIRED`, `RECOMMENDED`, `MAY`, `OPTIONAL`).
   The site describes; it does not specify.
2. No occurrence of the string `docs/v1`.
3. Every ` ```python ` fence is a complete module that `ast.parse`
   accepts. Use `...` for elided bodies rather than prose inside code.
4. No default value, no field list, no endpoint table, no event name
   list, no error code list and no signature table in a hand-written
   page. Link to the reference page instead. (Rules 1–3 are asserted;
   rule 4 is the reviewer's, and it is the one that keeps the site from
   drifting.)

Where a pattern already has a working demonstration, the page shows *that*
example and names it — `examples/` carries six workflows and the vendor
ACP adapters, and a page that invents a seventh is a page whose code
nothing runs.

| Page | Remit | Written from |
|---|---|---|
| `index.md` | What Athanore is, the product bet (agents produce values, code decides), the three rules, and where to go next | 01 §What Athanore is, §The three rules |
| `install.md` | `uv add` / `uv tool install` / the `postgres` extra; the Python floor; what a fresh install needs (nothing); and — until 1.0.0 is on PyPI — installing from a checkout | `README.md` §Install, 02 §Library choices, D66 |
| `quickstart.md` | The two-node `hello` workflow end to end: serve it, submit, answer the question, read the output, in both the CLI and the browser | `README.md` §A first workflow, 11 §Verbs |
| `guide/workflows.md` | Nodes and the signature-as-graph rule, payloads, routing by return value, fan-out, `join=True`, loop-backs, terminal nodes and run output, `@wf.node()` options by name (values in the reference) | 04 §Graph DSL, §Routing interpretation, §Fan-in |
| `guide/agents.md` | An agent as a class carrying its config, inlined prompts, `output_model` and structured submissions, repair turns, permission and elicitation policies, streaming, stats, tooling tiers, and that an agent never moves a task | 05 (all sections), 19 §Assembly |
| `guide/human-in-the-loop.md` | `human_input`, permissions and elicitations as one request object, answering from the SPA or CLI, durability across restarts, and that waiting releases the worker slot | 06 §The model, §Surfaces, 04 §Waiting on a human, D15 |
| `guide/runs.md` | Submitting runs, dispatch order, priorities, pools and capacity, retries and dead-letter, recovery after a restart, pause/resume/cancel/rerun/retry/move | 04 §Scheduling, §Running an attempt, §Operator operations, §Recovery on startup |
| `guide/plugins.md` | What a workflow can contribute to the UI — routes, actions, panels, event handlers, assets — the escape hatch, and that the built-in views are plugins too | 09 §Declarations, §Mounting, §Builtins are plugins |
| `guide/cli.md` | Connecting to a server, the read verbs and `--json`, the steer verbs, exit codes, `athanore login` | 11 (all sections) |
| `guide/http-api.md` | The wire contract as a client author meets it: auth (loopback, operator token, task token), the error shape, the SSE stream and reconnecting by cursor, the OpenAPI document and generating a client from it | 08 §Conventions, §Authentication, §Endpoints `### Events (SSE)`, §OpenAPI, §Versioning |
| `guide/deployment.md` | Serving beyond loopback and the operator token that turns on with it, `athanore.toml`, Postgres, migrations, retention, backups, reverse proxies and `forwarded_allow_ips`, running agents in containers | 12 §Operator token, §Beyond the LAN, §Hygiene; 07 §Migrations, §Retention, §Backups; 02 §`athanore.toml` layout |

`docs/site/src/assets/extra.css` is hand-written, small, and **not
generated from `nocturne.css`**: a second theme pipeline for a docs site
is machinery with no second consumer, and `web/src/styles/theme.css` —
which *is* generated, and which `AGENTS.md` says never to hand-edit — is
untouched by this change. It sets Material's own variables under
`[data-md-color-scheme="slate"]` from the Nocturne tokens: accent
`#9184d9` (`--md-accent-fg-color`, `--md-typeset-a-color`), background
`#161826` (`--md-default-bg-color`), surface `#232532` (code and admonition
backgrounds), text `#e9e9ed`. Say in a comment that the values are copied
from `docs/v1/design/nocturne.css` and are a borrow, not a binding: the
design system is normative for the SPA, not for this.

### 5. `scripts/_reference.py` (new) — the shared renderers

Moved out of `scripts/gen_skills.py`, verbatim in behaviour, renamed to a
module API (no leading underscore):

- Envelope and formatting: `document(lines, *, marker)`, `first_line`,
  `summary`, `signature`, `type_name`, `default`, `relative`,
  `annotated_attributes`, `dataclass_fields`, `declaration`, `members`,
  `methods`.
- Body renderers, each returning `list[str]` with **no** H1 and **no**
  lede: `public_api()`, `node_options()`, `agents()`, `events()`,
  `declarations()`, `context()`, `route_table()`, `error_codes()`,
  `commands()`, plus the pieces those need (`credential`, `parameter`,
  `command`, `event_groups`, `payload_fields`, `service_classes`).

Module docstring says what it is: the one place a fact about this package
is turned into markdown, with two front ends — `gen_skills.py` for an
agent that has the checkout open, `gen_docs.py` for a reader who has
neither the checkout nor the specs. Same determinism contract as
`gen_skills.py` today: declaration order where it is contract, sorted
everywhere else, no timestamps, no absolute paths, no version numbers.

`scripts/gen_skills.py` shrinks to `MARKER`, its ledes, `TARGETS`,
`render()`, `main()`. Its module docstring gains a sentence pointing at
`_reference.py`.

### 6. `scripts/gen_docs.py` (new) — the site's front end

Same shape as `gen_skills.py`, which is the shape to copy:

```python
MARKER = "<!-- Generated by scripts/gen_docs.py. Do not edit. -->"

TARGETS: dict[str, Callable[[], str]] = {
    "docs/site/src/reference/python-api.md": _python_api,
    "docs/site/src/reference/node-options.md": _node_options,
    "docs/site/src/reference/agents.md": _agents,
    "docs/site/src/reference/events.md": _events,
    "docs/site/src/reference/plugins.md": _plugins,
    "docs/site/src/reference/cli.md": _cli,
    "docs/site/src/reference/http-api.md": _http_api,
    "docs/site/src/reference/errors.md": _errors,
    "docs/site/src/reference/settings.md": _settings,
}
```

`render(target)` raises `KeyError` naming the script for a target it does
not own; `main()` writes every target and prints each path. Six of the
nine are `document([title, "", *lede, "", *reference.<body>()],
marker=MARKER)`; `_plugins` composes two bodies under two H2s. Ledes are
written for the site's reader: what the page is and what it is generated
from (the module or the snapshot), in one or two sentences. **No lede
cites `docs/v1` and none tells the reader to regenerate anything** — the
"do not edit" belongs in `MARKER`, which is an HTML comment and invisible
on the site.

The two site-only renderers:

**`_http_api`** — the shared route table first, then one `## <Tag>`
section per OpenAPI tag in the snapshot's `tags` order, then one
`### <METHOD> <path>` per operation carrying: summary, description,
credential, path and query parameters (name, type, required, description),
the request body (schema name, linked to the schemas section, or the
inline field table), and the responses (status, description, schema).
Then `## Schemas`: every entry of `components.schemas`, sorted by name,
as a field table (field, type, required, description). A small JSON
Schema → type-name renderer handles `$ref`, `anyOf`, `allOf`, `array`,
`enum` and the primitives; a `$ref` renders as a link to that schema's
anchor. Read the snapshot from disk, never `create_app()` — for the
reason `_routes` already gives in `gen_skills.py`: a stale snapshot must
fail one check, not two, and this script starts no application. Finish
with a line linking `../openapi.json`.

**`_settings`** — one row per field of `AthanoreSettings` in declaration
order, then a second table for `Retention` under a heading for the
`[retention]` table, then the `athanore.toml` shape.
Columns: setting, environment variable (`ATHANORE_` + the upper-cased
name), `athanore.toml` key (the name, or *refused* for `operator_token`
and `agent_command`, which `_TomlSource._REFUSED_KEYS` rejects), type,
default, description. Defaults come from the model: `None` renders
`unset`, a `default_factory` is called and its value rendered, and a
`Path` default renders as *the working directory* — `root_path`'s factory
is `Path.cwd`, and rendering its value would put an absolute path into a
committed file and make the output machine-dependent. `tests/test_docs_site.py`
asserts the property that rule exists for: the rendered page contains no
absolute path. Descriptions come from the model (see 7), which is the
whole point — three of these defaults are computed in
`_compute_derived_defaults` and their description is where "unset means
`sqlite+aiosqlite:///{root_path}/athanore.db`" is written down once.

### 7. `athanore/settings.py` — a `description` on every field

Every field of `AthanoreSettings` and `Retention` gains
`Field(..., description=...)`, worded from the Notes column of
`docs/v1/02-architecture.md` §Configuration, and the three computed
defaults (`db_url`, `public_url`, `log_format`) say in their description
what unset resolves to. This is the only change to `athanore/` in the
task, it adds no dependency and no import, and it is what makes the
generated settings table possible without a hand-maintained second table
beside it.

It changes no default and no validator, so it must change **no byte of
`tests/snapshots/openapi.json`** — `AthanoreSettings` is not a response
model. Check that explicitly (`uv run scripts/dump_openapi.py && git diff
--exit-code tests/snapshots`).

Add one sentence to `docs/v1/02-architecture.md` §Configuration saying
the table there is the specification and the descriptions on the model
are what the published reference renders, so the two are edited together.

### 8. `scripts/test.sh` — the `docs` step

As in question 3 above, placed after `lint-imports` and before the
`if [ -f web/package.json ]` block, with a comment in the file's voice
saying why it is mandatory (D178: no runner here, so a docs build only CI
performs is one that first goes red in front of a reader) and why
`--strict` (the `validation:` block is the check; without it the build
"succeeds" over a broken link).

### 9. `.github/workflows/ci.yml` — a `docs` job, and two lines in `contract`

New `docs` job, last: checkout, `astral-sh/setup-uv@v6` on 3.13,
`uv sync --all-packages --all-groups --all-extras`, then the same
`mkdocs build --strict -f docs/site/mkdocs.yml` the gate runs. No probe
— the config exists as of this change, and a contract check that can skip
itself is not one (the `contract` job's comment already says this).

In the existing `contract` job: add `uv run --no-sync scripts/gen_docs.py`
to the `regenerate` step, **after** `scripts/dump_openapi.py` (it reads
the snapshot, same as `gen_skills.py` and same as D213's ordering note),
and add `docs/site/src/reference` to the `git diff --exit-code` paths.

### 10. `.github/workflows/pages.yml` (new) — build and publish

```yaml
name: pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
```

Two jobs: `build` (checkout, setup-uv 3.13, `uv sync --all-packages
--all-groups --all-extras`, `mkdocs build --strict -f
docs/site/mkdocs.yml`, `actions/upload-pages-artifact@v3` with `path:
docs/site/build`) and `deploy` (`needs: build`, `environment:
name: github-pages, url: ${{ steps.deployment.outputs.page_url }}`,
`actions/deploy-pages@v4`).

`cancel-in-progress: false` is deliberate and is the documented Pages
pattern: cancelling a deployment mid-flight can leave the site
half-published.

Head the file with a comment saying the two things a reader needs and
cannot see from it: the build command is the gate's, verbatim, and
publishing needs *Settings → Pages → Source: GitHub Actions* enabled once
on a repository that does not exist yet (`git remote -v` is empty today).

### 11. `.gitignore` — the build output

```
# The built docs site (docs/site/mkdocs.yml `site_dir`). The `build/`
# rule above already matches it; named here because a reader looking for
# where the site goes should find it in this file.
docs/site/build/
```

### 12. Documents

- **`docs/v1/15-decisions.md`** — **D214**, one row, seven numbered
  parts: the six questions above plus the shared-generator answer.
  Status `**new (2026-09-10)**`. The reason column carries the
  constraint that decides them all, in the register D213's does: the
  site is for whoever is *using* Athanore, `docs/v1/` is for whoever is
  *building* it, and a site that restates a rule becomes a second
  specification that drifts — so the facts are generated and the
  separation is machine-checked rather than remembered. Record the
  `site_url` / `repo_url` guess there too.
- **`docs/v1/13-testing.md` §CI** — the list of what CI runs gains the
  docs build, and the paragraph gains a sentence: the `pages` workflow
  publishes on push to `main` and is not a check (nothing gates on its
  outcome), which is why the same build also runs in `ci.yml` and in the
  gate.
- **`docs/v1/02-architecture.md` §Configuration** — the sentence from 7.
- **`AGENTS.md` §Commands** — the docs commands, in the "In the
  container" block:

  ```sh
  uv run mkdocs build --strict -f docs/site/mkdocs.yml   # what the gate runs
  uv run mkdocs serve -f docs/site/mkdocs.yml            # 127.0.0.1:8000, live reload
  uv run scripts/gen_docs.py                             # the generated reference
  ```

  No new compose service: every service already uses host networking, so
  `./scripts/dev.sh "uv run mkdocs serve -f docs/site/mkdocs.yml"` is
  reachable at `127.0.0.1:8000` from the host.
- **`README.md`** — §Layout gains `docs/site/`; §Documentation gains the
  site as its first bullet, described as the place to start for someone
  using Athanore, with `docs/v1/` kept as the specification below it.
- **`TODO.md` is not touched.** It is git-ignored (`.gitignore`), it is
  the operator's scratch list, and moving its own item to "Promoted" is
  the operator's edit, not this task's.

## Tests

### `tests/test_docs_site.py` (new)

Module docstring in the register of `tests/test_skills.py`: what the two
halves are and why the checker is itself checked.

Generated half (the `skills/` suite's shape, applied to `gen_docs`):

- every target of `TARGETS` exists and is byte-for-byte what `render()`
  writes, with a `STALE` message naming `uv run scripts/gen_docs.py`;
- no file under `docs/site/src/reference/` is missing from `TARGETS` and
  none is an orphan;
- `render()` twice returns the same text;
- `render()` refuses a path it does not own;
- only generated pages carry `MARKER`;
- the settings page names every field of `AthanoreSettings` and
  `Retention`, and contains no absolute path (`str(ROOT)` is absent);
- every field of `AthanoreSettings` and `Retention` has a non-empty
  `description` — the rule that stops the table from going blank as
  fields are added;
- the HTTP page names every operation of `tests/snapshots/openapi.json`
  and every entry of `components.schemas`;
- the events page names every member of `EventName`.

Hand-written half (the audience separation, machine-checked):

- no page under `src/` contains a capitalised RFC 2119 keyword;
- no page under `src/` contains the string `docs/v1`;
- every ` ```python ` fence in every page parses with `ast.parse`;
- `mkdocs.yml` loads with `yaml.safe_load`, its `docs_dir`/`site_dir`
  are `src`/`build`, `strict` is true and the five `validation:` keys
  are all `error`;
- every markdown file under `src/` appears exactly once in the nav, and
  every nav entry that is not an absolute URL resolves to a file
  (`--strict` also catches this; the test names the file, which a build
  log does not, and it runs in the `pytest` step where the rest of this
  suite is).

The checker is exercised against deliberately broken text as well as
against the tree — a hand-written page fragment carrying `MUST`, one
carrying `docs/v1`, and a python fence that does not parse must each be
caught. `tests/test_skills.py` is the model for how to do that without
writing to the tree.

### `tests/_generators.py` (new)

`load_script(name)` — the loader `tests/test_skills.py` has inline today,
moved so both suites use it, and extended by one line: `scripts/` goes on
`sys.path` before the module is executed, because `gen_skills.py` and
`gen_docs.py` now `import _reference` and `spec_from_file_location` does
not put a script's own directory on the path the way running it does.
`tests/test_skills.py`'s `generator` fixture calls it; its docstring
keeps saying why the real file is loaded rather than a copy.

### `tests/test_ci_workflows.py` (extended)

- the job list assertion becomes `["python", "web", "contract",
  "package", "docs"]` (rename the test to match);
- the gate and the `docs` job run the same `mkdocs build --strict`
  command — the D74/D178 correspondence test, in the shape
  `test_the_gate_runs_the_playwright_suite_too` already has;
- the `contract` job regenerates the docs reference **after** the
  snapshot it reads, and diffs `docs/site/src/reference` — beside the
  existing assertion for `skills`;
- `scripts/gen_docs.py` exists and `docs/site/mkdocs.yml` exists (the
  `test_the_contract_jobs_generators_exist` shape);
- `pages.yml` parses, triggers on push to `main` and
  `workflow_dispatch`, declares `pages: write` and `id-token: write`,
  sets `concurrency.cancel-in-progress: false`, builds with the same
  command as the gate, and uploads `docs/site/build`;
- the module docstring and the `CI` / `NIGHTLY` constants gain `PAGES`,
  and the docstring gains a sentence: `pages.yml` is a publisher rather
  than a check, which is why the same build is also a job of `ci.yml`
  and a step of the gate.

### `tests/test_skills.py` (touched, not rewritten)

Only the fixture moves to `tests/_generators.py`. Every assertion, and
every byte under `skills/`, is unchanged — that is the constraint from
question 7 and it is what proves the refactor was a move.

## What this change does not do

- It does not publish `docs/v1/`, and does not regenerate any part of it
  as user-facing content. One nav entry links the design documents in the
  repository and no page mentions them.
- It does not add a light theme, a PDF export, translations, or
  versioned docs (`mike`). Single version, dark only.
- It does not add `mkdocstrings` or render docstring bodies. The Python
  reference is the fourteen names of `athanore.__all__` with signatures
  and first lines.
- It does not touch `web/`, `web/src/styles/theme.css`, or the design
  system. The site borrows four colours and two font names from Nocturne
  through a hand-written `extra.css`; there is no second theme pipeline.
- It does not add a compose service or a `scripts/gate.sh`. The gate is
  one command (D74) and every service uses host networking, so a served
  site is reachable from the host with no service of its own.
  ~~It does not add a `scripts/docs.sh`.~~ **Overridden by the operator
  mid-task:** every other recurring job here has a wrapper, so the site
  gets one too — `./scripts/docs.sh` serves it on `127.0.0.1:8000` and
  `./scripts/docs.sh build` builds it, host or container, in the shape of
  `run.sh` and `test.sh`. Everything else in this plan stands.
- It does not change the wire contract. `tests/snapshots/openapi.json`
  and `web/src/api/gen` are byte-identical when the task is done.
- It does not change a byte under `skills/`.
- It does not add a `Txxx` row or a `**Status.** Done.` line.

## Verification

- `./scripts/test.sh` green, with the new `docs` step in it and
  `tests/test_docs_site.py` in the `pytest` step.
- `uv run scripts/gen_docs.py && git diff --exit-code docs/site/src/reference`
  clean on a fresh checkout, and dirty after a deliberate edit to a
  generated page (check it, then revert).
- `uv run scripts/gen_skills.py && git diff --exit-code skills` clean —
  the refactor moved code and changed no output.
- `uv run scripts/dump_openapi.py && git diff --exit-code tests/snapshots`
  clean — the settings descriptions did not reach the wire.
- `uv run mkdocs serve -f docs/site/mkdocs.yml` and read the site as the
  reader it is for: search finds a term from each guide page, every nav
  entry resolves, the reference pages render their tables, and
  `/openapi.json` is served.
- Break each checked rule once and confirm the failure names the file: a
  `MUST` in a guide page, a `docs/v1` link, a python fence that does not
  parse, a page not in the nav, a stale generated page. A checker that
  passes everything is the failure mode this design cannot survive.
- `ruff check .`, `ruff format --check .` and `pyright` clean on
  `scripts/_reference.py`, `scripts/gen_docs.py`, `tests/_generators.py`,
  `tests/test_docs_site.py` and `athanore/settings.py`.
- Confirm the built site is self-contained: `grep -r "docs/v1"
  docs/site/build` finds only the one nav link.

## Exit condition

`docs/site/` holds an MkDocs Material site whose nine reference pages are
generated by `scripts/gen_docs.py` from the package and the committed
OpenAPI snapshot, and whose eleven narrative pages carry no RFC 2119
keyword, no link into `docs/v1/`, and no python example that does not
parse; `scripts/_reference.py` is the one place a fact about this package
becomes markdown, with `gen_skills.py` and `gen_docs.py` as its two front
ends and `skills/` byte-identical to before; `./scripts/test.sh` builds
the site with `--strict` and is green; `ci.yml` has a `docs` job and its
`contract` job diffs the generated reference beside the snapshot, the
client and the skills; `.github/workflows/pages.yml` publishes to GitHub
Pages on every push to `main`; `docs/v1/15-decisions.md` carries D214
with the seven choices above; and `README.md`, `AGENTS.md`,
`docs/v1/13-testing.md` and `docs/v1/02-architecture.md` say the site
exists and how it is built.

## Files

```
pyproject.toml                          the docs dependency group
uv.lock                                 relocked
.gitignore                              docs/site/build/
docs/site/mkdocs.yml                    new
docs/site/hooks/openapi.py              new
docs/site/src/index.md                  new
docs/site/src/install.md                new
docs/site/src/quickstart.md             new
docs/site/src/guide/workflows.md        new
docs/site/src/guide/agents.md           new
docs/site/src/guide/human-in-the-loop.md new
docs/site/src/guide/runs.md             new
docs/site/src/guide/plugins.md          new
docs/site/src/guide/cli.md              new
docs/site/src/guide/http-api.md         new
docs/site/src/guide/deployment.md       new
docs/site/src/assets/extra.css          new
docs/site/src/reference/*.md            new, generated (nine files)
scripts/_reference.py                   new, moved out of gen_skills.py
scripts/gen_docs.py                     new
scripts/gen_skills.py                   thinned; output unchanged
scripts/test.sh                         the docs step
athanore/settings.py                    a description on every field
tests/_generators.py                    new
tests/test_docs_site.py                 new
tests/test_skills.py                    fixture moved
tests/test_ci_workflows.py              the docs job, the pages workflow
.github/workflows/ci.yml                the docs job; contract regenerates and diffs
.github/workflows/pages.yml             new
README.md                               layout and documentation
AGENTS.md                               the docs commands
docs/v1/15-decisions.md                 D214
docs/v1/13-testing.md                   §CI
docs/v1/02-architecture.md              §Configuration
```
