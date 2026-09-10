# Agent skills

Five skills, one per surface you can build against. Each is a directory
holding a `SKILL.md` in the Agent Skills format, so you can install one
into your own coding agent and have it know which of the twenty-one
documents under `docs/v1/` to open — and which shipped code to read —
instead of being pointed at the design cold.

| Skill | For someone who is |
|---|---|
| [athanore-workflows](athanore-workflows/SKILL.md) | writing a workflow: nodes, routing, agents, human input, joins, pools |
| [athanore-plugins](athanore-plugins/SKILL.md) | giving a workflow its own routes, actions, panels and event handlers |
| [athanore-api](athanore-api/SKILL.md) | driving the HTTP API and the event stream from a client of their own |
| [athanore-cli](athanore-cli/SKILL.md) | serving and steering Athanore from a terminal |
| [athanore-web](athanore-web/SKILL.md) | changing the SPA in `web/` |

## Installing one

A skill directory is the unit of installation, and each is self-contained:
install one, or all five, in any order.

```sh
ln -s "$PWD/skills/athanore-workflows" ~/.claude/skills/athanore-workflows
```

The symlink is the form to lead with. Every path a skill cites is
relative to the checkout root, so a symlink into the checkout keeps a
skill's pointers pointing at the checkout it was installed from — which
is the one thing a stale copy gets wrong. For an agent that will not
follow a symlink, copy instead:

```sh
cp -r skills/athanore-workflows ~/.claude/skills/athanore-workflows
```

...and for one project rather than one user, the same two commands
against that project's `.claude/skills/` directory:

```sh
mkdir -p .claude/skills
ln -s "$PWD/skills/athanore-api" .claude/skills/athanore-api
```

## What a skill is here

**A pointer, never a copy.** `AGENTS.md` says the documents are the
specification; a skill that restated a rule would be a second
specification that drifts, and a drifted skill is worse than no skill,
because an agent believes it. So the split is hard, and there is nothing
in between:

- A `SKILL.md` is **hand-written** and states no fact that is written
  down somewhere else. It names things and cites where they are defined.
  It carries no event names, no field lists, no signatures, no endpoint
  tables and no option defaults.
- Everything it would otherwise have restated is **generated** into the
  skill's own `reference/` directory — `skills/athanore-workflows/reference/`
  and its three siblings — by `scripts/gen_skills.py`, from the code and
  from the committed OpenAPI snapshot. Regenerate with:

```sh
uv run scripts/gen_skills.py
```

- Both halves are **gated**. `tests/test_skills.py` asserts that the
  committed reference files are byte-for-byte what the script writes and
  that every pointer in a hand-written file resolves; CI's `contract` job
  regenerates and runs `git diff --exit-code` over `skills/` beside
  `tests/snapshots` and `web/src/api/gen`.

`skills/athanore-web` has no `reference/` of its own: the SPA's facts are
TypeScript, and a Python script restating them would be the second,
weaker copy this design exists to prevent. It points at
`web/src/api/gen` and `web/src/styles/theme.css` instead, both of which
are generated and gated already.

## Editing one

Do not restate the specification here. Add a citation, and if the fact
you wanted is machine-readable, add it to `scripts/gen_skills.py` so it
cannot drift. Three citation forms are what the test parses, and it
holds you to all three:

- **A path** is an inline-code span, written relative to the checkout
  root and never absolute: `docs/v1/09-plugins.md`,
  `workflows/feature/files.py`. Every one that begins with a top-level
  directory of the checkout must exist. Something that is code rather
  than a path — `wf.node(...)`, `run.completed`, `/api/health` — does not
  match, and should stay that way rather than gain an escape.
- **A section** is a path followed by `§` and the heading, as in
  `docs/v1/04-engine.md` §Fan-in (join nodes). It runs to the end of the
  line, a comma, a semicolon, an unmatched closing parenthesis or a
  trailing full stop, and it must be a real heading in the document cited
  beside it. To cite two sections of one document, write two citations:
  one `§` each, so there is no ambiguity to resolve.
- **A code fence** in a `SKILL.md` must be preceded by a source marker
  naming the file it came from — `<!-- from: workflows/rps.py -->` — and
  its text must appear in that file, verbatim or uniformly indented. This
  file is the exception: its fences are install commands, which are
  excerpts of nothing.

Skills ship in the sdist and not in the wheel, and `pyproject.toml` says
nothing about them (D213): a skill is a set of paths into `docs/v1/`,
`examples/`, `workflows/`, `athanore/` and `web/`, and a wheel carries
none of those, so a wheel-installed skill would be a directory of
dangling pointers.
