# skills stand alone — self-contained skills, republished from the site and the code

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `AGENTS.md` §Quality bar (no stubs, no narrowed scope — every
one of the five is rewritten, not the easy four), §What this repository
is (the docs are the spec, and *this* task is about the reader who does
not have them), §Architecture rules that must hold (small core: nothing
in `athanore/` changes for this), §Commands (the gate is
`./scripts/test.sh`, D74);
`docs/v1/README.md` (what `docs/v1/` is, and who it is for — the reader
a skill is *not* for);
`docs/v1/13-testing.md` §Contract tests and §CI (the snapshot-and-diff
pattern every generated tree here follows, and the sentence that already
names the skills beside the site's reference in the `contract` job);
D74 (the gate is one command), D178 (a check only CI runs is a check
that never runs), D213 (the six things `skills/` decided — this task
amends (2), (3) and (4) and keeps (1), (5) and (6)), D214 (the seven
things the site decided — this task amends (7), and leans on (5) and
(6): the site is for whoever is *using* Athanore, it names no design
document, and it is machine-checked for both).

**The precedent this change copies** is the one D213 and D214 both
copied: a generator renders, the output is committed, a pytest test
asserts the committed bytes are what the generator writes, and CI's
`contract` job regenerates and runs `git diff --exit-code`. All of that
machinery already exists for `skills/` — `scripts/gen_skills.py`,
`tests/test_skills.py`, the `skills` argument of the diff in
`.github/workflows/ci.yml`. **Nothing about the gate changes.** What
changes is what the generator writes and what the hand-written half is
allowed to say. Read `scripts/gen_skills.py`, `scripts/gen_docs.py`,
`scripts/_reference.py`, `tests/test_skills.py` and
`tests/test_docs_site.py` before writing a line, and read every page
under `docs/site/src/guide/` once as the reader it is for: those pages
are about to become the narrative half of four skills.

## What this change is

`skills/` was built on a wrong premise and its content is inverted here.
The layout stays — five directories, `SKILL.md` plus `reference/`, and a
`README.md` — and the gate stays. What changes is that **each skill
stands alone**: it is installed into somebody else's coding agent,
working on their own project, with no checkout of this repository on
disk. So a skill may not point at `docs/v1/`, may not point at
`workflows/feature/`, and may not say "nothing here is normative — open
the spec". It carries the facts an agent needs to write a workflow, a
plugin, an API client or a command line against Athanore, and it carries
them in the directory that was copied.

The constraint that decides every other question is the one D213 and
D214 both turned on, read for this reader: **a skill that restates a
rule by hand drifts, and a drifted skill is worse than no skill because
an agent believes it.** Citation is no longer available as the fix —
there is nothing on the reader's disk to cite. Generation is. So:

- **The narrative half is the documentation site's guide pages,
  republished.** `docs/site/src/guide/` already exists, is already
  hand-written for exactly this reader (D214: someone *using* Athanore),
  already names no design document and carries no RFC 2119 keyword, and
  already has every Python example checked. `scripts/gen_skills.py`
  copies the pages each skill needs into that skill's `reference/`,
  rewrites their links to resolve inside the skill, and stamps them with
  its marker. One hand-written narrative, one place to edit it, and the
  gate holds the copies to it.
- **The fact half is the site's generated reference pages, republished
  the same way.** `scripts/gen_docs.py` already renders the public API,
  the node options, the agents, the events, the plugin declarations and
  context, the command tree, the full HTTP reference, the error codes
  and the settings table, from the code and the committed OpenAPI
  snapshot. The skills stop rendering their own framings of the same
  bodies and take those pages as they are, links rewritten. This retires
  the last place a generated file cited `docs/v1/`.
- **`SKILL.md` is hand-written and is the minimum to act**: what the
  surface is, one complete worked example, the handful of rules an agent
  gets wrong on its first attempt, and a map of the skill's own
  `reference/` saying which file answers which question. It is capped in
  length and it is held to the same rules as a site page: no `docs/v1`,
  no RFC 2119 keyword, every code fence an excerpt of a file in this
  tree, every Python fence a module that parses.

`skills/README.md` changes with them: copying is the install, the
symlink is how a checkout stays current, and `npx skills` is the
convenience. Nothing in `athanore/` changes. Nothing in `docs/site/`
changes except, where a sentence reads wrongly once its link is gone, a
wording fix that the site's own tests still pass.

## The open questions, settled

These become one row in `docs/v1/15-decisions.md` — **D215**, the next
number — written in the numbered style of D213 and D214, with the parts
below. D213 (2), (3) and (4) and D214 (7) are amended by it; say so in
the row.

### 1. No citation of `docs/v1/` survives, in any file under `skills/`, for any skill — including `athanore-web`

The brief asked whether a citation may remain as "normative reference".
No. A path the reader cannot open teaches nothing, and a rule that
admits exceptions is a rule the next editor extends. The check is the
one the site already has, applied to the whole of `skills/`: the string
`docs/v1` appears in no file there, `skills/README.md` included (it can
say "the design documents" when it needs to say why a skill does not
cite them). `(05 §Agent classes)`-style parentheticals in docstrings are
the same dead pointer in another spelling, and they are already stripped
by `gen_docs.py`'s `_uncited`; the skills now inherit that stripping by
taking the site's pages.

`athanore-web` is the one skill whose reader is, by definition, in this
checkout — the SPA exists nowhere else — so it keeps pointing at code
under `web/` and at `AGENTS.md`, and those pointers stay gate-checked.
It still loses every `docs/v1` citation: what it used to send the reader
to `docs/v1/10-frontend.md` for, it now states in a line or points at
the module that implements it. The mock and the normative design-system
document are reached through `AGENTS.md`, which the SPA's contributor
has to have read anyway.

### 2. Verbosity: `SKILL.md` is terse and capped at 150 lines; `reference/` is where an agent goes to understand

"Minimum to act" is taken literally. A `SKILL.md` has, in order: the
frontmatter; two or three sentences saying what the surface is; **one**
complete worked example; the rules an agent gets wrong first time, as
bullets; and the map of `reference/`. It explains nothing the guide
page beside it explains — a rule in the `SKILL.md` is one line, and the
*why* is in the guide. `tests/test_skills.py` asserts the cap
(150 lines including the frontmatter — every skill fits in about 100),
because "keep them short" is a rule that only holds if something holds
it.

### 3. Worked examples: small, complete, inlined, and still excerpts

"Inlined" means the example is *in* the `SKILL.md`, not cited. It does
not mean `workflows/feature/` — a thousand lines of this repository's
own machinery, running on pools and paths that exist nowhere else. Each
`SKILL.md` carries one example of about twenty lines that a reader can
save and run: the two-node `hello` workflow, the route-action-panel
plugin, the `curl` against the event stream and the error object, the
`serve`-and-drive shell session, the SPA's commands.

The excerpt rule of D213 (4) stays, because it is what keeps an inlined
example true: every fence in a `SKILL.md` is preceded by
`<!-- from: path -->` and its text appears in that file, verbatim or
uniformly indented. The sources are now `README.md`,
`docs/site/src/quickstart.md`, the guide pages under
`docs/site/src/guide/`, and `AGENTS.md` — files whose fences are
themselves checked. **Every ` ```python ` fence in a `SKILL.md` must
also parse as a module** (`ast.parse`, the site's rule), so a fragment
like the two-line `play` signature the workflows skill excerpts today is
no longer allowed: an example is a module or it is not there. The
`from:` marker is an HTML comment naming a checkout path; it is for the
gate, not the reader, and it is not a citation.

### 4. Generated preambles name what a page is generated from, in words, and cite nothing

The site's ledes already do this — "Generated from `athanore.__all__`,
with the file each name is defined in" — and the skills take them
unchanged. A preamble that says a page is read off `EventName` is a
fact about provenance a reader can trust; a preamble that cites the
document fixing the vocabulary is a pointer to nothing. The
`scripts/_reference.py` machinery that existed only to choose between
the two wordings — `Note`, `cite`, `plainly`, and the `note=` parameter
of `declarations()` and `context()` — is deleted, and the plain wording
is inlined. `gen_docs.py`'s output does not change by a byte.

### 5. The narrative is republished, not rewritten: one guide, N skills

The alternative — hand-writing a second narrative per skill — is the
drift this task exists to end. So the four portable skills carry copies
of the site's pages, made by `scripts/gen_skills.py`, and the bundles
are:

| Skill | Guide pages (→ `reference/guide-<name>.md`) | Reference pages (→ `reference/<name>.md`) |
|---|---|---|
| `athanore-workflows` | `workflows`, `agents`, `human-in-the-loop`, `runs` | `python-api`, `node-options`, `agents`, `events` |
| `athanore-plugins` | `plugins` | `plugins`, `events`, `settings` |
| `athanore-api` | `http-api` | `http-api`, `errors`, `events`, and `openapi.json` (see below) |
| `athanore-cli` | `cli`, `deployment` | `cli`, `settings` |
| `athanore-web` | — | — (D213 (6) stands) |

`events` appears three times and `settings` twice **because no skill
may depend on another being installed** (D213 (2), which this keeps):
a generated file is free, and a cross-skill pointer is a dangling one
the moment a user installs one skill. `quickstart.md`, `install.md` and
`index.md` are not bundled — the `SKILL.md` is the quickstart, and the
install line it needs is one sentence.

`athanore-api` additionally carries `reference/openapi.json`: the
committed `tests/snapshots/openapi.json`, byte for byte, as the one
non-markdown target. The site publishes that document beside its pages
(`docs/site/hooks/openapi.py`) and both the HTTP guide and the HTTP
reference link it as `../openapi.json`; bundling it means those links
resolve inside the skill and the sentences around them stay true, and
it is what a client author hands to a code generator when no server is
running yet. In `gen_skills.py` it is the site-root page `openapi.json`
whose text is the snapshot read from disk, so `home()` and the link
rule need no special case for it. It carries no marker — JSON has no
comment — and the marker test exempts it by suffix; the byte-for-byte
test holds it to the snapshot.

Links inside a republished page are rewritten by one rule, in
`gen_skills.py`, and the rule is unit-tested against text: a link to a
page **in this skill's bundle** becomes a link to that file
(`../reference/node-options.md` → `node-options.md`, `workflows.md#rule-3…`
→ `guide-workflows.md#rule-3…`, fragment kept); a link to a page **in
another skill's bundle** becomes its text followed by the skill that
carries it — `[The command line](cli.md)` → `The command line (see the
athanore-cli skill)` — so the reader learns what to install rather than
finding a broken link; a link to **anything else** (`index.md`,
`install.md`, `quickstart.md`) becomes its text alone; external (`://`) and fragment-only (`#…`) links are untouched. A
page is otherwise copied byte-for-byte, so an implementer who finds a
sentence that reads wrongly once its link is text (a "see [x](y)" whose
referent is now another skill, or "this site" where the reader has a
directory) fixes the *guide* so it reads correctly in both places — the
guide is the source — and never the copy. A generated page's wording
lives in `gen_docs.py` and is left alone: with `openapi.json` bundled,
nothing in a reference page reads wrongly.

### 6. Install: `cp` leads, `ln -s` keeps a checkout current, `npx skills` is the convenience

The README's order inverts. `cp -r skills/athanore-workflows
~/.claude/skills/athanore-workflows` is the documented install: it
needs nothing, and a copy now works because nothing in it points
outside itself. The symlink stays, second, as the way to stay current
from a checkout. Third, `npx skills add <owner>/<repo> --skill
athanore-workflows` (the vercel-labs CLI, `skills` on npm), which knows
where each agent keeps its skills so the README does not have to
enumerate them — with the note, in passing, that the GitHub form needs
this repository to have a remote, which today it does not (`git remote
-v` is empty), and that the CLI also takes a local path and a URL.
`tests/test_skills.py` asserts the first install fence is the `cp`, that
an `ln -s` form is still there, and that `npx skills add` is named.

## Files and what each does

### 1. `scripts/gen_skills.py` — republish, rewrite, stamp

Rewritten. It keeps its contract with the test — `MARKER`, `TARGETS:
dict[str, Callable[[], str]]`, `render(target)`, `main()` — and loses
every per-file lede. It imports `_reference` (for `document()`, and so
that `test_the_two_generators_are_two_front_ends_over_one_renderer`'s
`generator.reference is skills.reference` still holds) and `gen_docs`
(for `render()` of the reference pages, in process — it does **not**
read `docs/site/src/reference/*.md` from disk, so the order the
`contract` job runs the two generators in stays irrelevant).

- `BUNDLES: dict[str, tuple[str, ...]]` — the table in §5, as site paths
  relative to `docs/site/src/` (`"guide/workflows.md"`,
  `"reference/events.md"`), in the order the `SKILL.md` will list them.
  The skill order is the `NAMES` order of the test.
- `filename(page)` — `guide/x.md` → `guide-x.md`, `reference/x.md` →
  `x.md`.
- `home(page)` — the first skill in `BUNDLES` order whose bundle carries
  `page`, or `None`.
- `rewrite(text, *, page, skill)` — the link rule of §5, over
  `[text](target)` with `re`, resolving `target` against the directory of
  `page` with `posixpath.normpath`. It is a pure function of its
  arguments and is what the unit tests call.
- `page_text(page)` — for `reference/*`: `gen_docs.render(f"docs/site/src/{page}")`
  with its first line — the `gen_docs` marker — replaced by `MARKER`
  and nothing else touched (do not drop the line and re-wrap with
  `document()`, which would leave a second blank after the marker);
  for `guide/*`: the file read from disk, wrapped with
  `reference.document(lines, marker=MARKER)`, so the copy is the marker,
  a blank line, then the page. `rewrite` runs over the result either
  way. Every output begins with the `gen_skills` marker, and the
  `gen_docs` marker appears nowhere under `skills/`.
- `TARGETS` is built from `BUNDLES`: `skills/<skill>/reference/<filename>`
  → a renderer closed over the page and the skill. No target under
  `skills/athanore-web/`.
- The module docstring says what this file now is: the skills are the
  site's pages, republished per skill with their links rewritten, so
  that a copied skill directory resolves every link inside itself.

Determinism is unchanged: no timestamps, no absolute paths, and every
transform is a pure function of committed files.

### 2. `scripts/_reference.py` — the two wordings become one

Delete `Note`, `cite` and `plainly`; drop the `note` parameter from
`declarations()` and `context()` and inline the plain wording where the
`note(...)` calls were. Update the module docstring (it says the skills
cite the specification; they no longer do — there is one front end that
frames, `gen_docs.py`, and the skills republish its pages). No other
body changes. `uv run scripts/gen_docs.py && git diff --exit-code
docs/site/src/reference` is clean afterwards: this is a deletion, and it
proves itself by changing no site byte.

### 3. `scripts/gen_docs.py` — two arguments go

`note=reference.plainly` is removed from the two calls in `_plugins()`.
Nothing else. Its module docstring's "one renderer, two front ends"
sentence is reworded to say the skills republish these pages.

### 4. `skills/athanore-workflows/SKILL.md`

Frontmatter `name: athanore-workflows`; `description` one line saying
what it covers (a workflow module: nodes and inferred edges, routing by
return value, failure policy, agents, human input, fan-out and joins,
pools) and when to load it (before writing or changing a workflow, a
node body or an agent class) — and no longer "to find which design
document settles the behaviour".

Body, in order: what a workflow is (one module, a `Workflow`, `async`
functions under `@wf.node()`, three rules); the `hello` example
(`<!-- from: README.md -->`, the two-node module with `human_input`,
which parses and runs with nothing configured), and the `serve` /
`submit` / `answer` / `show` lines beneath it from the same file; the
rules as bullets, one line each — signature is the graph and the
keyword-only parameter is the payload; the return forms; `NonRetryable`
dead-letters and anything else retries; a node `timeout` stops while a
person is being waited on, an agent's does not; `join=True` needs a
payload slot and waits for every branch; an agent submits a value and
the body routes on it; never retry an agent call in a body;
`output_model` makes `result.output` a validated instance; `MockAgent`
replaces the agent in a test. Then the map: `reference/guide-workflows.md`
for routing, fan-out and output; `guide-agents.md` for prompts,
submissions, tooling, policies, stats and the doubles;
`guide-human-in-the-loop.md`; `guide-runs.md` for pools, dispatch,
retries, steering; `python-api.md`, `node-options.md`, `agents.md`,
`events.md`. One line each, as "if you are asking … open …".

### 5. `skills/athanore-plugins/SKILL.md`

The workflow is the host; four declarations, and the renderer stays in
the interface; `ctx: PluginContext` is an explicit parameter, never
injected by name. The worked example is the guide's route + action +
panel + handler module (`<!-- from: docs/site/src/guide/plugins.md -->`),
which parses. Rules: scope follows ownership and an id that is not yours
is a 404, never a 403; what each panel kind's `source` returns is fixed
by the kind; a `custom` panel plus `assets=` is the escape hatch and
ships one file of browser JavaScript; a workflow's own events go under
its own name through `ctx.services.events.publish`; a packaged workflow
advertises itself as an entry point. Map: `guide-plugins.md`,
`plugins.md` (every declaration field, the slot, placement, kind and
method vocabularies, `PluginContext`, every service's methods, the two
refusals), `events.md` (what `@wf.on` may subscribe to), `settings.md`
(`plugin_cdns`).

### 6. `skills/athanore-api/SKILL.md`

One contract, generated; two credentials; one push channel. Worked
example: the `curl -N` against `/api/events` and the error object, both
from `docs/site/src/guide/http-api.md`, and the `openapi-ts` line from
the same page — a client is generated from `/openapi.json` on the
running server, or from the skill's own `reference/openapi.json`, which
is the same document. Rules: no credential on loopback, `Authorization: Bearer`
on a network bind, `X-Athanore-Token` for a task and it never appears in
an operator response; branch on `code`, never on `error`; resume the
stream with `after=` or `Last-Event-ID` and refetch on `resync`;
transcript chunks are not on the stream; a new endpoint that belongs to
a workflow is a plugin route (the `athanore-plugins` skill). Map:
`guide-http-api.md`, `http-api.md` (every operation, parameter, body,
response and schema), `errors.md`, `events.md`, `openapi.json`.

### 7. `skills/athanore-cli/SKILL.md`

One server verb, a set of client verbs over the HTTP API, `--json`
before the verb. Worked example: the `serve` block and the drive-it
block from `docs/site/src/guide/cli.md` or `README.md` §The CLI. Rules:
targets are `module:wf` or `file.py:wf`; client verbs default to
`http://127.0.0.1:4002` and `--url`/`--token`/`ATHANORE_TOKEN`/`login`
reach anything else; `db`, `token` and `login` talk to no server; the
bare `athanore <workflow> "title"` is `submit`; the four exit codes. Map:
`guide-cli.md`, `guide-deployment.md` (`athanore.toml`, network binds,
the proxy, Postgres, migrations, backups, retention, containers),
`cli.md` (every command, argument and option), `settings.md` (every
setting, its environment variable, its key and its default).

### 8. `skills/athanore-web/SKILL.md`

Rewritten with no `docs/v1` citation and no `reference/`. It keeps its
paths under `web/` and its `AGENTS.md` pointer, both gate-checked
(§1). Body: one screen with a pane cycle; realtime is SSE invalidating
query caches (`web/src/realtime/invalidate.ts` is the map) and never a
second copy of server state; the design system is generated from the
mock's tokens and `AGENTS.md` says where the mock and its normative
document are. What is not a seam: `web/src/api/gen` and
`web/src/styles/theme.css` are generated (`pnpm -C web gen`,
`pnpm -C web gen:theme`) and hand-editing either is a red gate. The
worked example is the SPA's commands block from `AGENTS.md`
(`<!-- from: AGENTS.md -->`, the `pnpm -C web …` fence). Where things
live: `web/src/panes/` (the cycle and one renderer per kind under
`kinds/`), `web/src/keys/`, `web/src/plugins/` (manifest, registry,
bridge), `web/src/overlays/`, `web/e2e/`. When a change belongs to a
plugin instead, and that the event union and the client are in
`web/src/api/gen`.

### 9. `skills/README.md`

Rewritten. What a skill is here: self-contained — a copy works, because
every link in one resolves inside its own directory — and generated
where it can be: the narrative is the site's guide pages and the facts
are the site's reference pages, both republished by
`scripts/gen_skills.py`, and the `SKILL.md` is the hand-written minimum
to act. The five, one line each with a link to each `SKILL.md`. Install:
`cp -r` first (user directory, then a project's `.claude/skills/`),
`ln -s` to stay current from a checkout, `npx skills add` with the
remote caveat of §6. Editing: change a guide under
`docs/site/src/guide/` or a renderer, then `uv run scripts/gen_skills.py`
— never a file under `reference/`; a `SKILL.md` names no checkout path,
no design document, carries no RFC 2119 keyword, keeps under 150 lines,
and every fence in it is an excerpt marked `<!-- from: path -->` (the
README itself excepted, as today). Skills still ship in the sdist and
not the wheel (D213 (1)) — say so in one sentence.

### 10. `README.md` (root)

Two places. The `## Layout` gloss for `skills/` no longer says "pointing
into docs/v1/ and the tree": "agent skills, one per surface, self-
contained; copy one into your agent". The `## Documentation` bullet for
`skills/README.md` says each stands alone and is installed by copying,
with `npx skills add` as the alternative.

### 11. Documents

- `docs/v1/15-decisions.md` — the D215 row, parts §1–§6 above, noting
  that it amends D213 (2) (copy now leads, and a skill points at
  nothing outside itself), D213 (3) (the hand-written half may state
  the minimum to act, and the generated half now carries the narrative
  too), D213 (4) (path and section citations are gone; the excerpt rule
  stays and Python fences parse) and D214 (7) (`gen_skills.py` no
  longer frames the shared bodies — it republishes `gen_docs.py`'s
  pages — and `Note`/`cite`/`plainly` are deleted).
- Nothing else under `docs/v1/` changes. `docs/v1/13-testing.md`'s
  sentence naming the skills in the `contract` job's diff is still true.

## Tests

### `tests/_prose.py` (new)

The parsers `tests/test_docs_site.py` and `tests/test_skills.py` now
share, moved out of the former: `KEYWORDS`, `KEYWORD`, `keywords()`,
`python_fences()`, `SPEC = "docs/v1"`. `tests/test_docs_site.py` imports
them and keeps every assertion and every deliberately-broken-text test
it has — the one edit besides the import is the docstring of
`test_the_two_generators_are_two_front_ends_over_one_renderer`, which
now says the skills republish the site's pages (same `_reference`
module, disjoint targets, different markers) rather than frame the same
bodies; its three assertions stand. `tests/_generators.py` is the
precedent for a shared helper module under `tests/`.

### `tests/test_skills.py` (rewritten in its hand-written half)

Keep, unchanged in meaning: the five skills are the five skills; every
skill is linked from the README; frontmatter is `name` and
`description` and `name` matches the directory; every generated file is
one the script writes; byte-for-byte; deterministic; `render` refuses a
foreign path; the web skill has no `reference/`; only generated files
carry the marker (and add: the `gen_docs` marker appears in no file
under `skills/`; `reference/openapi.json` is exempt from the marker
check by suffix and is asserted byte-equal to
`tests/snapshots/openapi.json`).

Replace the README install test: the **first** fence with an install
command in it is the `cp -r`; some fence carries `ln -s`; the text
carries `npx skills add`; the text carries `uv run scripts/gen_skills.py`.

Delete: `SECTION`, `HEADING`, `section_text`, `cited_sections`,
`headings`, `test_every_cited_section_is_a_heading_of_the_document_beside_it`,
`test_the_skills_actually_cite_something`, and the section-parser tests
(`test_an_invented_heading_is_caught`, `test_a_renamed_section_is_caught`,
`test_the_section_parse_stops_where_the_citation_does`,
`test_a_second_citation_on_one_line_is_read_too`,
`test_a_heading_inside_a_fence_is_not_a_heading`). There are no section
citations left to parse.

Add, parametrised over every `*.md` under `skills/` unless said
otherwise:

1. **No file names the design documents**: `SPEC` not in the text.
2. **No file specifies anything**: `keywords(text) == []`.
3. **A portable `SKILL.md` names no checkout path**: for the four
   portable skills, `cited_paths(text) == []` — the existing parser, now
   asserting emptiness, so a `workflows/feature/files.py` slipped into
   prose is caught. For `athanore-web/SKILL.md` and `skills/README.md`,
   the existing rule: every cited path exists.
4. **Every relative link resolves inside the skill**: every
   `[text](target)` without `://`, with any `#fragment` stripped and
   fragment-only links skipped, resolves to a file relative to the
   linking file's own directory; and every inline-code span in a
   `SKILL.md` that begins with `reference/` resolves under that skill.
   This is the check that proves the link rewriter and the bundles
   agree.
5. **Every file in a skill's `reference/` is named by its `SKILL.md`**
   (as `reference/<file>` in a span or a link) — a generated file the
   front door never mentions is one an agent never loads.
6. **Every fence in a `SKILL.md` is a marked excerpt** (kept), **and every
   ` ```python ` fence in a `SKILL.md` parses** (new). Every `SKILL.md`
   has at least one fence, so the checker has work.
7. **A `SKILL.md` is at most 150 lines.**
8. **The rewriter, against text**: an in-bundle link becomes the
   filename with its fragment kept; a link into another skill's bundle
   becomes text plus `(see the athanore-<x> skill)`; a link to an
   unbundled page becomes its text; `../openapi.json` from a page of
   the api skill becomes `openapi.json`; an external
   link and a fragment-only link are untouched; and a link whose text
   wraps a line keeps the line break, so a republished page has exactly
   the site page's line count (plus the marker and its blank line for a
   guide).
9. **A republished page is the site's page, modulo links and marker**:
   for every markdown target, the skill file with the marker dropped and every
   `[text](target)` reduced to `text` equals the site page (for a guide,
   read from disk; for a reference page, `gen_docs.render(...)` with
   its marker dropped) reduced the same way. This is what makes "one
   narrative" a checked fact rather than a described one.

Keep the deliberately-broken-text tests for the parsers that remain
(`cited_paths`, `fenced_blocks`, `is_excerpt`) and add ones for the two
new checks: a `docs/v1` in a skill is caught, a `MUST` in a skill is
caught, a relative link to a missing file is caught, a Python fence that
does not parse is caught.

### `tests/test_ci_workflows.py` and `.github/workflows/ci.yml`

Unchanged. The `contract` job already regenerates with
`scripts/gen_skills.py` and diffs `skills`; run the suite to prove it
still asserts that. `scripts/test.sh` is unchanged (D74): the pytest
byte-check is the gate's half of the freshness contract, as it is for
the snapshot and the site.

## What this change does not do

- It does not create, rename or remove a skill, and does not change the
  layout of one: `SKILL.md` plus `reference/`, `README.md` at the top.
- It does not touch `athanore/`, `pyproject.toml`, the wheel, the sdist,
  `scripts/test.sh`, `ci.yml` or `pages.yml`. No CLI verb, entry point
  or environment variable for skills.
- It does not change `docs/site/src/reference/` by a byte, and does not
  change a guide page except to fix a sentence that reads wrongly once
  its link is plain text (§5) — no new content in a guide, and the
  site's own tests stay green.
- It does not change `tests/snapshots/openapi.json` or `web/src/api/gen`.
- It does not bundle `quickstart.md`, `install.md` or `index.md`. The
  one non-markdown file it bundles is `openapi.json`, in the api skill
  alone.
- It does not add a sixth check to CI. The gate is
  `tests/test_skills.py` plus the `git diff --exit-code` that already
  covers `skills`.
- It does not add a `Txxx` row or a `**Status.** Done.` line.

## Verification

- `./scripts/test.sh` green, with the rewritten `tests/test_skills.py`
  and the unchanged `tests/test_docs_site.py` and
  `tests/test_ci_workflows.py` in the `pytest` step.
- `uv run scripts/gen_skills.py && git diff --exit-code skills` clean on
  a fresh checkout; dirty after an edit to a guide page (regenerate, see
  the copy follow, revert both).
- `uv run scripts/gen_docs.py && git diff --exit-code docs/site/src/reference`
  clean — the `_reference.py` deletion changed no site byte.
- `grep -rn "docs/v1" skills/` finds nothing. `grep -rln "Generated by
  scripts/gen_docs.py" skills/` finds nothing.
- Install one skill the way the README now says — `cp -r` into a scratch
  directory **outside** the checkout — and open it as an agent would:
  every link in the `SKILL.md` and in every file under `reference/`
  resolves inside that directory, and no file names a path that only
  exists here. Do this for `athanore-workflows` and `athanore-api`, the
  two whose bundles have the most cross-links.
- Save each `SKILL.md`'s Python example to a file and run
  `python -c "import ast, sys; ast.parse(open(sys.argv[1]).read())"` on
  it; serve the `hello` one with `athanore serve hello.py:wf` and drive
  it with the lines beneath it.
- Break each checked rule once and confirm the failure names the file:
  a `docs/v1` in a `SKILL.md`, a `MUST`, a checkout path in a portable
  skill, a link to a file that is not there, a fence with no marker, a
  Python fence that does not parse, a 151st line, a stale copy.
- `wc -l skills/*/SKILL.md` — every one under 150.
- `ruff check .`, `ruff format --check .` and `pyright` clean on
  `scripts/gen_skills.py`, `scripts/_reference.py`, `scripts/gen_docs.py`,
  `tests/_prose.py`, `tests/test_skills.py` and `tests/test_docs_site.py`.

## Exit condition

Every file under `skills/` is free of `docs/v1` and of RFC 2119
keywords; the four portable `SKILL.md` files name no path in this
checkout and every link in every skill resolves inside that skill's own
directory; each `SKILL.md` is at most 150 lines, carries one complete
worked example that is a marked excerpt and parses, and names every
file in its `reference/`; every file under `reference/` is a
republished site page written by `scripts/gen_skills.py`, byte-for-byte
what it renders, and equal to the site's page modulo links and marker;
`scripts/_reference.py` has one wording and `gen_docs.py`'s output is
unchanged; `skills/README.md` leads with `cp`, keeps `ln -s`, names
`npx skills add` and the missing remote; the root `README.md` describes
the directory as it now is; `docs/v1/15-decisions.md` carries D215; and
the gate is green with CI's `contract` job diffing `skills` exactly as
before.

## Files

```
scripts/gen_skills.py                        rewritten: bundles, rewrite, republish
scripts/_reference.py                        Note/cite/plainly deleted, wording inlined
scripts/gen_docs.py                          two note= arguments removed, docstring
skills/README.md                             rewritten
skills/athanore-workflows/SKILL.md           rewritten
skills/athanore-workflows/reference/         regenerated: guide-workflows, guide-agents,
                                             guide-human-in-the-loop, guide-runs,
                                             python-api, node-options, agents, events
skills/athanore-plugins/SKILL.md             rewritten
skills/athanore-plugins/reference/           regenerated: guide-plugins, plugins, events, settings
skills/athanore-api/SKILL.md                 rewritten
skills/athanore-api/reference/               regenerated: guide-http-api, http-api, errors, events,
                                             openapi.json
skills/athanore-cli/SKILL.md                 rewritten
skills/athanore-cli/reference/               regenerated: guide-cli, guide-deployment, cli, settings
skills/athanore-web/SKILL.md                 rewritten, no reference/
tests/_prose.py                              new: shared prose parsers
tests/test_skills.py                         hand-written half rewritten
tests/test_docs_site.py                      imports the shared parsers; assertions unchanged
README.md                                    two lines about skills/
docs/v1/15-decisions.md                      D215
docs/site/src/guide/*.md                     only if a sentence needs its link-free wording
```
