# remove reference to docs/ — no path into `docs/v1/` or `docs/plans/` in the README, the package, or the SPA source

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence.

**Specs.** `AGENTS.md` §Quality bar (no narrowed scope — every one of the
hits below is rewritten, not the easy ones; and the narrowing this plan
*does* make is written down, not silent), §Architecture rules that must
hold (small core — nothing behavioural in `athanore/` changes; agent
prompts are byte-exact, so `athanore/api/mcp.py` and
`athanore/agents/base.py` change a comment and a docstring and not one
prompt byte), §Conventions (`web/src/styles/theme.css` is generated from
`nocturne.css`; never hand-edit it — which is why the one generated file
in scope is changed through its generator), §Commands (the gate is
`./scripts/test.sh`, D74);
`docs/v1/13-testing.md` §Pyramid (the guard is a pytest test over the
tree, the lowest layer that can express "this string appears nowhere
under these paths"; the precedent is `tests/test_docs_site.py::
test_no_page_names_the_design_documents` and `tests/test_skills.py`'s
twin, both over `tests/_prose.py`'s `SPEC`);
`docs/v1/10-frontend.md` §Design system (theme.css is generated from
the design's token sheet — the coupling is real, so the *code* that
reads `docs/v1/design/nocturne.css` stays and only the comments that
cite it change);
D214 (6) and (7) (the audience separation is machine-checked, not
remembered; the site strips the package's parenthesised
`(05 §Agent classes)` citations at render time — the short-form
convention this plan leaves alone is the one D214 already names);
D215 (1) (no citation of `docs/v1/` survives under `skills/`, asserted
by test — the same shape, applied here to three more trees).

Read `README.md`, the three Python hits, `web/scripts/gen-theme.mjs`
lines 535–560, `web/src/styles/theme.test.ts`, `tests/_prose.py` and
`tests/test_docs_site.py` lines 278–296 before writing a line.

## What this change is

`docs/v1/` is the specification and `docs/plans/` the per-task plans.
Both are for whoever is *building* Athanore; the operator wants neither
named from the places a *user* reads — the README — nor from source
code comments. After this change:

- `README.md` names no path under `docs/v1/` or `docs/plans/`. It keeps
  every pointer to the published site (`docs/site/`), to `skills/`, to
  `AGENTS.md` and to `DESIGN.md`. `AGENTS.md` is the developer's front
  door and already maps the design documents; the README reaches them
  through it and not directly.
- No `.py` file under `athanore/` contains the string `docs/v1` or
  `docs/plans`. Three files do today.
- No file under `web/src/` contains either string, with one code-level
  exemption (below). 121 files, 157 lines do today.
- A pytest test asserts all three, so the boundary is checked rather
  than remembered — the shape D214 (6) and D215 (1) already use for the
  site and the skills.
- `AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `tests/`, `scripts/`,
  `web/e2e/`, `web/scripts/`, `web/*.config.ts`, `docker/`,
  `workflows/`, `.github/` and `docs/site/mkdocs.yml`'s one nav link are
  untouched: developer-facing, build tooling, or the test fixtures that
  *read* the specification on purpose.

**What a "reference" is here.** The string `docs/v1` or `docs/plans` —
a path a reader could open. The tree also carries a second, shorter
citation form: `10 §Layout`, `06 §Service`, `D49`, `T057` — the
document's number and section, with no path. There are 1,148 such
lines under `web/src/` and 1,172 under `athanore/`, against 157 and 3
of the path form. **The short form is out of scope for this task** and
stays. Reasons, so the narrowing is a decision and not an omission:

1. The brief's outcome is worded as citations *of `docs/v1/` and
   `docs/plans/`*, and its Python list — four files — is the result of
   a grep for the path, not for the convention.
2. Rewriting ~2,300 comment lines is a different task, several times
   this one, and most of those sentences are built around the citation
   (`10 §Graph pane's "jumps to the log pane filtered to that node"`)
   — a rewrite that has to keep the quoted behaviour is per-line
   judgement, not a rule an implementer can apply and a reviewer can
   check by grep.
3. D214 (7) already treats that form as the package's citation
   convention and strips it at the one boundary a user crosses (the
   generated reference pages). Nothing a user is shown carries it.

If the operator wants the short form gone as well, that is a follow-up
feature with its own plan; this plan records the choice as **D219** so
it is visible and reversible.

## The open questions, settled

**1. Drop the citation, or drop the line?** Drop the citation and keep
the descriptive text, rewriting the sentence so it stands alone. A
docblock's first sentence is what the file *is* ("The run list on the
left"); the parenthetical after it is what this task removes. Never
delete a whole comment line for carrying a citation, and never replace
a path with its short form (`docs/v1/10-frontend.md` §Layout →
`10 §Layout` is refused: it would satisfy the grep while keeping every
pointer, which is the letter of the request without its point). Where
the citation *was* the sentence's subject ("The keyboard map of
`docs/v1/10-frontend.md` §Keyboard, as data."), the rewrite names the
thing instead ("The keyboard map, as data."). The rule, with worked
examples, is in §The rewrite rule below.

**2. Module-to-module cross-references?** Untouched. `App.tsx` naming
`components/Footer.tsx`, a test naming the module it tests
(`` (`../bridge.ts`, ...) ``), `AGENTS.md §Conventions`, `web/scripts/
gen-theme.mjs`, `tests/api/test_mcp.py` — these are pointers into the
code and into the developer files the brief keeps. Only the path into
`docs/v1/` or `docs/plans/` leaves a parenthetical; whatever else was
in it stays.

**3. The three questions the brief did not ask, found in the code:**

- **Functional references stay.** `web/src/styles/theme.test.ts:19`
  `resolve(WEB, '../docs/v1/design/nocturne.css')` is code that reads
  the token sheet to compare it with the generated stylesheet. The
  token sheet is not moving (out of scope), so the line is true and
  stays; it is the guard test's one exemption, written as an exact
  `(path, line-content)` pair so the exemption cannot widen. Everything
  else under `web/src/` that names `nocturne.css` is a comment about
  where the theme comes from and is rewritten to name the *command*
  (`pnpm -C web gen:theme`) rather than the path — the generator is the
  one place that knows the path, and `AGENTS.md` §Conventions says the
  rest.
- **The generated file is changed through its generator.**
  `web/src/styles/theme.css` carries a header naming
  `docs/v1/design/nocturne.css` and `docs/v1/10-frontend.md`. The
  header is a template literal in `web/scripts/gen-theme.mjs`
  (`renderTheme`, lines 541–560). Edit the template, run
  `pnpm -C web gen:theme`, commit both; `theme.test.ts` runs
  `--check` and fails if they disagree. The generator's *own* leading
  comment (lines 1–30) and its `@param` docstring are a build script's
  and stay — `web/scripts/` is outside `web/src/`.
- **`athanore/settings.py` needs no edit.** The brief lists it; it
  contains neither string. What it cites is
  `docs/site/src/reference/settings.md` — the published site, which
  stays by the brief's own out-of-scope list — and the short form
  (`02 §Configuration`). Do not invent an edit there.

Two smaller ones:

- **README's version paragraph** (lines 33–39) cites the task plan as
  the definition of "v1.0.0". The clause goes; while the sentence is
  being rewritten it is also made true — there is no `v1.0.0` tag
  (`git tag` lists `v1.0.0a1` and `v1.1.0`) and `pyproject.toml` says
  `1.2.0` — by not naming a version at all. Wording below.
- **README's Layout block** lists `docs/v1/` and `docs/plans/` beside
  `docs/site/`. The line is deleted, not reworded: the block is a map
  for a user, and the two directories it would name are the ones the
  user is told not to need. `docs/site/`'s line stays.

## Files and what each does

### `README.md` — six hits, prose only

The skills re-publish this file's Python fences as excerpts
(`tests/test_skills.py::test_a_fence_that_is_not_in_the_file_it_names_is_caught`
and the `<!-- from: README.md -->` markers under `skills/`), and
`tests/test_docs_site.py::test_the_site_has_a_wrapper_of_its_own`
asserts `./scripts/docs.sh` is named in it. **No code fence changes and
the Development section keeps `./scripts/docs.sh`.** Every edit is to
prose:

1. **Lines 33–39**, the tagged-version paragraph. Replace the whole
   paragraph with:

   > **v1 is tagged in this repository and nowhere else**: there is no
   > git remote and nothing has been uploaded, so PyPI still carries
   > the v0 MVP (`0.0.12`) and the `uv add` lines above will fetch that
   > until v1 is published. Until it is, install from a checkout — see
   > [Development](#development).

2. **Line 174–175**, "Full reference: [`docs/v1/11-cli.md`](…)". The
   published site has the generated CLI reference. Replace with:

   > Every read verb takes `--json`, so the CLI composes with `jq`. Full
   > reference: [`docs/site/src/reference/cli.md`](docs/site/src/reference/cli.md).

3. **Line 196**, the Layout block's `docs/v1/ … docs/plans/ …` line.
   Delete the line. The block's alignment is unchanged (every other
   line keeps its column).

4. **Lines 201–203**, "See [`docs/v1/02-architecture.md`](…) for the
   per-module breakdown and the layering rule. Nothing in `athanore/`
   depends on pi, Claude, or Docker: …". Replace the first sentence:

   > The per-module breakdown and the layering rule are in
   > [`AGENTS.md`](AGENTS.md). Nothing in `athanore/` depends on pi,
   > Claude, or Docker: vendor adapters are user-land, in `examples/`.

5. **Lines 243–247**, the two Documentation bullets for
   `docs/v1/README.md` and `docs/v1/15-decisions.md`. Delete both
   bullets. The list keeps, in order: `docs/site/`, `skills/README.md`,
   `AGENTS.md`, `DESIGN.md`. Do not add a sentence to the `AGENTS.md`
   bullet about where the design documents are — that is the hop the
   boundary is for, and `AGENTS.md` already makes it.

Re-wrap any paragraph you touched to the file's existing ~76-column
prose width. Then `grep -n 'docs/v1\|docs/plans' README.md` prints
nothing.

### `athanore/` — three hits, no behaviour

- **`athanore/__init__.py:3–4`**, the package docstring — the first
  thing `help(athanore)` shows a user:

  > The package's front door: the public API, and nothing else. An
  > author writes

- **`athanore/agents/base.py:22–25`**, the module docstring:

  > **The blocks are normative.** :data:`_KICKOFF`, :data:`_HTTP_TIER`,
  > :data:`_ASK` and :data:`_SUBMIT` are copies of the fenced blocks of
  > the agent-prompts specification, and ``tests/agents/test_prompt.py``
  > compares them against that document rather than against a second
  > copy.

  Not one byte of `_KICKOFF`, `_HTTP_TIER`, `_ASK`, `_SUBMIT` or the
  repair block changes; `tests/agents/test_prompt.py` still compares
  them to the document and still passes.

- **`athanore/api/mcp.py:174–180`**, the comment block over the tool
  descriptions. The block's own heading two lines up is "19's wording,
  per tool" and its first sentence quotes 08 §MCP, so the referent is
  already on the page:

  ```python
  # 08 §MCP: "Tool descriptions carry the same wording as the 19 kickoff so
  # the model's instructions and its tools agree." Every line below is a
  # line of the kickoff prompt — the sentence that names the capability,
  # with the curl mechanics that belong to the `http` tier left out,
  # because in this tier the tool *is* the mechanics.
  # `tests/api/test_mcp.py` reads the document back and checks that each
  # line is still in it, so a change to 19 cannot leave these behind.
  ```

  The `*_DESCRIPTION` constants below it are byte-exact prompt text and
  do not change.

`athanore/settings.py`: no edit (see above). Then
`grep -rn 'docs/v1\|docs/plans' athanore --include='*.py'` prints
nothing.

### `web/scripts/gen-theme.mjs` — the emitted header only

In `renderTheme`, the template literal starting at line 541. Change the
header to:

```
/* GENERATED by web/scripts/gen-theme.mjs — do not edit by hand.
 *
 * Built from nocturne.css, the design system's token sheet; the
 * generator names where it lives. Regenerate with
 * `pnpm -C web gen:theme`; the gate fails while this file and its
 * source disagree (web/src/styles/theme.test.ts).
 *
 * Four layers:
 *   1. the Nocturne tokens, copied verbatim from the source
 *   2. the shadcn/ui variables, mapped onto them
 *   3. the Tailwind `@theme inline` exposure, the type base and the
 *      four sizes the font-size chooser picks between
 *   4. the utilities the mock styles from: the status colours, the type
 *      scale, the two mixed surfaces and the two animations
```

(the backticks are escaped in the template as they are today, and
everything from "Every utility here reads a token" on is unchanged).
Layer 2's "(§Tokens → shadcn)" goes with the citation it hung off. Run
`pnpm -C web gen:theme` and commit the regenerated
`web/src/styles/theme.css`; `tokens.gen.ts` is regenerated by the same
command and should come out byte-identical (its header names no
document). Nothing else in `gen-theme.mjs` changes.

### `web/src/` — 157 lines in 121 files

The worklist is `grep -rn 'docs/v1\|docs/plans' web/src`; work it to
zero, then run the guard test. Every hit is one of these shapes; the
first is 140-odd of them, the rest are named individually.

**(a) A docblock citation.** The docblock's parenthetical (or the
sentence's object) is a path plus the `§Section` names and `Dnn`/`Tnnn`
numbers that hang off it, sometimes continued onto the next line
without repeating the path (`RequestPanel.tsx:3–4`, `sse.ts:3–4`,
`CustomElementHost.tsx:3–4`, `taskDrawer.ts:3–4`, `DeleteRun.test.tsx:
2–4`, `GraphCanvas.tsx:3–5`, and the like). Apply §The rewrite rule.

**(b) The design mock**, `docs/v1/design/Athanore.dc.html`, named in
`useKeymap.ts:26`, `Tokens.tsx:5`, `GraphCanvas.tsx:5`, `Overview.tsx:
4`, `Log.tsx:4`, `AgentStream.tsx:4`, `Requests.tsx:6`,
`fixtures.ts:194` and `fixtures.ts:326–327` (where the path is split
over two lines). The tree already calls it "the mock" without a path
in a hundred places; do the same: "the mock's `isGraph` block", "in the
order the mock applies them:", "the mock's own first run
(`a4c81f20b91e`)".

**(c) The token sheet**, `docs/v1/design/nocturne.css`, in comments
about generation: `index.css:4`, `reactflow.css:4`, `theme.test.ts:2`,
`Tokens.tsx:11`, and the rendered string at `Tokens.tsx:129–130`.
Name the command, not the path:

- `index.css`: "Everything token-shaped lives in ./styles/theme.css,
  which `pnpm gen:theme` generates from the design system's token
  sheet. … Theme values do not belong here — edit the token sheet and
  regenerate."
- `reactflow.css`: "Unlike its neighbour theme.css, which
  `pnpm gen:theme` generates, this file is hand-written."
- `theme.test.ts:1–7`: "theme.css is generated by
  `web/scripts/gen-theme.mjs` and never hand-edited (AGENTS.md
  §Conventions). …" — the rest of the sentence as it is. Line 19, the
  `resolve(...)`, **stays** (it is the exemption).
- `Tokens.tsx:4–5`: "There is no Storybook: this is where the theme is
  checked by eye against the design mock before any screen is built on
  it."; line 11: "so a token added to the token sheet shows up here
  without an edit"; lines 129–130, the `<span>` text: "every token and
  utility in src/styles/theme.css, generated by `pnpm gen:theme`".
  `Tokens.test.tsx` asserts on tokens and utilities, not on this text.

**(d) Fixture strings.** `overlays/__tests__/newRun.test.ts:53` and
`:97` both carry `description: 'see docs/v1/11-settings.md'` — a value
the test POSTs and then asserts was POSTed. Change both to
`'see the settings reference'`; they must stay equal to each other.

**(e) Bare-document citations with no section**: `search.ts:49`
"(`docs/v1/03-data-model.md`)" after "task ids are positive integers"
— delete the parenthetical; `answer.ts:173` "(`docs/v1/10-frontend.md`
§Keyboard, `docs/v1/20-carried-findings.md`)" — delete the
parenthetical; `Tokens.tsx:4` "(docs/v1/17-serial-task-plan.md §
T057)" — covered in (c).

**(f) Generated output**: `styles/theme.css` — through the generator,
above. `web/src/api/gen/` is generated from OpenAPI and carries neither
string; it does not change (`git diff --exit-code web/src/api/gen`
after `pnpm -C web gen`, as the gate already checks).

## The rewrite rule

For every hit of shape (a), in this order:

1. **Delete the path token** — `` `docs/v1/NN-name.md` `` with its
   backticks — and with it every `§Section`, `Dnn`, `Tnnn` and
   "item N" that was part of *the same citation* (the same
   parenthetical, or the same comma-separated list), including the part
   carried onto the next comment line. Everything in the parenthetical
   that is not a citation — a module path, a route, a quoted phrase, a
   URL — stays.
2. **If the parenthetical is now empty, remove it** with the space
   before it, and fix the punctuation that was outside it (a sentence
   ending "… body (X)." ends "… body.").
3. **If the sentence has lost its subject or object, name the thing.**
   "The keyboard map of X §Keyboard, as data." → "The keyboard map, as
   data." "The overlay chrome of X §Overlays, as three …" → "The overlay
   chrome, as three …". "the one overlay X §Keyboard marks '(with
   confirm)'" → "the one overlay the keyboard map marks '(with
   confirm)'" — keep the quoted words; they are the behaviour.
4. **If a later sentence leaned on the citation, rewrite it too** so it
   no longer points at a section that is no longer named. `lib/keys.ts:
   4` "That section is one sentence long and exhaustive — …" → "The
   specification's keyboard map is one sentence long and exhaustive —
   …". This is the one case that needs reading past the hit line: scan
   the rest of the docblock for "that section", "that document",
   "the section", "it says", "10 says" *when the referent was the
   deleted path*.
5. **Do not introduce a short-form citation.** No path becomes `10
   §Layout`. A short form that was already on the line and was not part
   of the deleted citation stays (`ActionForm.tsx:6` "(02 §Library
   choices)" is untouched; `ActionForm.tsx:3` "(X §Plugin renderers,
   D49)" is deleted whole because `D49` was inside the same
   parenthetical as the path).
6. **Re-wrap the docblock** to the file's existing width so no line is
   left short or long; oxlint (`pnpm -C web lint`) and prettier do not
   rewrap comments for you.

Worked examples, before → after:

- `App.tsx:2–3` "The app shell: the four regions of
  `docs/v1/10-frontend.md` §Layout — header, run list, detail, footer."
  → "The app shell: its four regions — header, run list, detail,
  footer."
- `components/RunList/RunList.tsx:2` "The run list on the left
  (`docs/v1/10-frontend.md` §Layout)." → "The run list on the left."
- `components/RequestPanel.tsx:2–4` "`RequestPanel`: the controls that
  answer one request (`docs/v1/06-requests.md` §Surfaces,
  `docs/v1/10-frontend.md` §Panes item 3 and item 4)." →
  "`RequestPanel`: the controls that answer one request."
- `components/ActionForm.tsx:2–3` "`ActionForm`: a form generated from
  a JSON Schema, in the app's own idiom (`docs/v1/10-frontend.md`
  §Plugin renderers, D49)." → "`ActionForm`: a form generated from a
  JSON Schema, in the app's own idiom."
- `panes/kinds/GraphCanvas.tsx:2–5` "The graph pane: the run's shape as
  a React Flow canvas (`docs/v1/10-frontend.md` §Graph pane and §Panes
  item 5, over `GET /api/runs/{id}/graph` of `docs/v1/08-api.md` §Graph
  semantics, and the mock's `isGraph` block in
  `docs/v1/design/Athanore.dc.html`)." → "The graph pane: the run's
  shape as a React Flow canvas, over `GET /api/runs/{id}/graph`, drawn
  as the mock's `isGraph` block draws it." (the route is not a
  citation and stays; the mock stays by name).
- `lib/useIsNarrow.ts:2–3` "Whether the viewport is below the SPA's
  one breakpoint (`docs/v1/21-design-refresh.md` §Narrow layout,
  D194)." → "Whether the viewport is below the SPA's one breakpoint."
- `realtime/sse.ts:2–4` "…everything that keeps a tab open for a week
  honest (`docs/v1/10-frontend.md` §Realtime and caching, 08
  §Events)." → "…everything that keeps a tab open for a week honest."
  — `08 §Events` was in the same parenthetical and goes with it.
- `routes/search.ts:4` "`docs/v1/10-frontend.md` §Layout keeps the
  whole SPA on one route, so a view is linkable only if …" → "The whole
  SPA is one route, so a view is linkable only if …".
- `overlays/DeleteRun.tsx:2–3` "the one overlay
  `docs/v1/10-frontend.md` §Keyboard marks "(with confirm)"." → "the
  one overlay the keyboard map marks "(with confirm)"."
- `routes/__tests__/AppRoute.test.tsx:3` "(`../AppRoute.tsx`,
  `docs/v1/10-frontend.md` §Layout)." → "(`../AppRoute.tsx`)." — the
  module path is not a citation.
- `lib/keys.ts:2–8` "The keyboard map of `docs/v1/10-frontend.md`
  §Keyboard, as data. That section is one sentence long and exhaustive
  — …" → "The keyboard map, as data. The specification's keyboard map
  is one sentence long and exhaustive — …" (rule 4; "(10 §Overlays)"
  and "(T067)" further down that docblock are untouched, rule 5).

## Tests

**New: `tests/test_spec_citations.py`.** One module, in the style of
`tests/test_env_hygiene.py` and `tests/test_docs_site.py` (`ROOT =
Path(__file__).resolve().parent.parent`, module docstring saying what
boundary it holds and why, `from tests._prose import SPEC`). It adds a
second constant beside `SPEC` in `tests/_prose.py`:

```python
#: The per-task plans, the other developer-only tree. Named beside
#: `SPEC` wherever a user-facing tree is checked for it.
PLANS = "docs/plans"
```

and asserts:

1. `test_the_readme_names_no_design_document` — neither `SPEC` nor
   `PLANS` in `README.md`.
2. `test_no_package_module_names_a_design_document` — parametrised
   over `sorted((ROOT / "athanore").rglob("*.py"))`, ids relative to
   `ROOT`; neither string in the file. (`athanore/web/dist/` holds a
   `.gitkeep` and no `.py`; `rglob("*.py")` is the right net.)
3. `test_no_spa_source_names_a_design_document` — parametrised over
   `sorted(p for p in (ROOT / "web" / "src").rglob("*") if p.is_file())`,
   the walk `tests/test_skills.py:394` already uses (the tree is `.ts`,
   `.tsx` and `.css` only, nothing git-ignored lives under it, and
   `web/src/api/gen/` is included on purpose — it is generated and
   clean, and should stay so); neither string on any line, **except**
   the lines in `EXEMPT`:

   ```python
   #: Code that reads the specification's design source on purpose, as
   #: an exact line: the theme test compares the generated stylesheet
   #: with the token sheet it was built from, and the sheet is not
   #: moving. A comment is never exempt; a second line here needs a
   #: decision (D219).
   EXEMPT: Mapping[str, frozenset[str]] = {
       "web/src/styles/theme.test.ts": frozenset(
           {"const SOURCE = resolve(WEB, '../docs/v1/design/nocturne.css')"}
       ),
   }
   ```

   Compare the *stripped* line to the exempt set, so indentation does
   not matter but the text must match exactly.
4. `test_every_exemption_is_still_needed` — every exempt line is
   present in its file, so an exemption cannot outlive the line it
   excuses.
5. Two self-checks in the style of `tests/test_docs_site.py:414–428`
   — `test_a_path_into_the_specification_is_caught` and
   `test_a_path_into_the_plans_is_caught` — asserting the two constants
   catch `"see \`docs/v1/04-engine.md\` §Routing"` and
   `"the plan is \`docs/plans/T012-foo.md\`"`, so the test fails for
   the right reason if the constants are ever edited.

The guard runs in `uv run pytest -q` and so in `./scripts/test.sh` and
CI's `pytest` job with no change to either. It shells out to nothing.

**Existing tests that read the edited files**, all of which must still
pass without edits: `tests/agents/test_prompt.py` (prompt blocks
against the document — no prompt byte changed), `tests/api/test_mcp.py`
(descriptions against the document — no description changed),
`tests/test_skills.py` (README fences as excerpts — no fence changed),
`tests/test_docs_site.py::test_the_site_has_a_wrapper_of_its_own`
(`./scripts/docs.sh` still named in the README), `web/src/styles/
theme.test.ts` (`--check` against the regenerated stylesheet),
`web/src/dev/Tokens.test.tsx`, `web/src/overlays/__tests__/newRun.test.ts`
(both fixture strings changed together). No snapshot changes: the wire
contract is untouched, so `tests/snapshots/openapi.json` and
`web/src/api/gen/` are byte-identical.

## What this change does not do

- Does not touch the short-form citations (`10 §Layout`, `D49`,
  `T057`) anywhere — see §What this change is. D219 records it.
- Does not touch `AGENTS.md`, `CLAUDE.md`, `DESIGN.md` (a one-paragraph
  redirect into `docs/v1/`, linked from the README as "where the MVP's
  design document went" — that link stays: it names no path into the
  hierarchy and the brief keeps developer files), `tests/`,
  `scripts/`, `web/e2e/`, `web/vite.config.ts`,
  `web/playwright.config.ts`, `web/scripts/gen-theme.mjs` beyond the
  one emitted template, `docker/`, `workflows/`, `.github/`,
  `docs/site/mkdocs.yml` (its nav entry is the one place the site may
  name the specification, D214 (6)), or anything under `docs/v1/` or
  `docs/plans/` except the two files this plan names.
- Does not move, rename or split `docs/v1/design/nocturne.css` or the
  design mock. The build's dependency on the token sheet is real and
  stays where it is; only the comments describing it change.
- Does not change one byte of an agent prompt, a tool description, a
  settings description, an error message, a CLI help string or the
  OpenAPI document.
- Does not add a sentence anywhere saying where the design documents
  went. The README points at `AGENTS.md`; `AGENTS.md` points at
  `docs/v1/`. That is the boundary.

## Decision to record

Add to `docs/v1/15-decisions.md`, after D218:

> | D219 | **No path into `docs/v1/` or `docs/plans/` in `README.md`, in any `.py` under `athanore/`, or in any file under `web/src/`; asserted by `tests/test_spec_citations.py`.** The README reaches the design documents through `AGENTS.md` and not directly, and points the CLI section at the published `docs/site/src/reference/cli.md`; docstrings and comments that cited a document by path are rewritten to stand without it, never abbreviated to the short form. Two things are deliberately kept: (1) code that *reads* the token sheet (`web/src/styles/theme.test.ts`'s `resolve(...)` — one exact line, the test's only exemption) and the generator that builds `theme.css` from it, because the dependency is real and the sheet is not moving; (2) the tree's short-form citations — `10 §Layout`, `06 §Service`, `D49`, `T057` — some 1,150 lines under each of `web/src/` and `athanore/`, which are the package's citation convention (D214 (7) strips them at the one boundary a user crosses) and whose removal is a separate, several-times-larger task with its own plan if the operator wants it. `AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `tests/`, `scripts/`, `web/e2e/`, the build configs and `mkdocs.yml`'s one nav link keep theirs: they are for the reader who has the specification | **new (2026-09-11)** | The operator asked that the specification and the plans stay — they are how features get built — but stop being named from the README and from source comments, where a reader is using the software rather than building it. The path form is what a reader could open and find themselves inside a specification written for an implementer; it is also what a grep can hold to zero, which is the shape D214 (6) and D215 (1) already gave this boundary for the site and the skills. The short form is left because removing it is not this task and because a comment built around a quoted rule loses the rule when the citation is cut by rule rather than by hand |

The D219 row is the only edit under `docs/v1/`.

## Verification

In the container (`./scripts/dev.sh`), in this order:

```sh
grep -rn 'docs/v1\|docs/plans' README.md athanore --include='*.py' ; echo "^ must be empty"
grep -rn 'docs/v1\|docs/plans' web/src | grep -v "theme.test.ts:19" ; echo "^ must be empty"
pnpm -C web gen:theme && git diff --stat web/src/styles     # theme.css header only; tokens.gen.ts unchanged
uv run pytest -q tests/test_spec_citations.py tests/test_skills.py tests/test_docs_site.py tests/agents/test_prompt.py tests/api/test_mcp.py
pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test
./scripts/test.sh                                            # the gate, green
git diff --exit-code tests/snapshots web/src/api/gen         # nothing
```

Then read `git diff -- web/src | grep '^[-+]' | grep -v '^[-+][-+]'`
once, top to bottom, as a reader who has never seen the specification:
every `+` line should read as a sentence. A line that says "of §Layout"
or "(item 4)" with nothing before it is a rule-1 miss.

## Exit condition

- `README.md`, every `.py` under `athanore/` and every file under
  `web/src/` contain neither `docs/v1` nor `docs/plans`, with
  `web/src/styles/theme.test.ts:19` as the one exact-line exemption;
  `tests/test_spec_citations.py` says so and is green.
- `web/src/styles/theme.css` is what `pnpm -C web gen:theme` writes
  (`theme.test.ts --check` green) and its header names no document.
- No agent prompt byte, tool description, settings description, error
  string, CLI help string, OpenAPI document or README code fence
  changed; `tests/snapshots` and `web/src/api/gen` are byte-identical.
- `docs/v1/15-decisions.md` carries D219.
- The gate (`./scripts/test.sh`) is green.
- One commit on `feat/remove-reference-to-docs`, under this plan's
  commit, message `remove reference to docs/: no path into docs/v1 or
  docs/plans in the README, the package or the SPA source`; landed
  `--no-ff` on `main`.

## Files

```
README.md                                        six prose edits, no fence
athanore/__init__.py                             package docstring, line 3
athanore/agents/base.py                          module docstring, lines 22–25
athanore/api/mcp.py                              comment block, lines 174–180
web/scripts/gen-theme.mjs                        the emitted theme.css header only
web/src/styles/theme.css                         regenerated
web/src/**                                       121 files, 157 lines — the grep is the list
tests/_prose.py                                  PLANS beside SPEC
tests/test_spec_citations.py                     new — the guard
docs/v1/15-decisions.md                          D219
docs/plans/remove reference to docs/-literal-paths-out-of-readme-and-source.md   this file
```
