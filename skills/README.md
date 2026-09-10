# Agent skills

Five skills, one per surface you can build against. Each is a directory
holding a `SKILL.md` in the Agent Skills format plus a `reference/` of
everything it needs, so you can install one into your own coding agent —
working on your own project, with no copy of this repository on disk —
and have it know how to write a workflow, a plugin, an API client or a
command line against Athanore.

| Skill | For someone who is |
|---|---|
| [athanore-workflows](athanore-workflows/SKILL.md) | writing a workflow: nodes, routing, agents, human input, joins, pools |
| [athanore-plugins](athanore-plugins/SKILL.md) | giving a workflow its own routes, actions, panels and event handlers |
| [athanore-api](athanore-api/SKILL.md) | driving the HTTP API and the event stream from a client of their own |
| [athanore-cli](athanore-cli/SKILL.md) | serving and steering Athanore from a terminal |
| [athanore-web](athanore-web/SKILL.md) | changing the SPA in `web/` — the one skill for a contributor to this checkout |

## Installing one

A skill directory is the unit of installation, and each stands alone:
install one, or all five, in any order. Copy it:

```sh
cp -r skills/athanore-workflows ~/.claude/skills/athanore-workflows
```

A copy works because nothing in a skill points outside its own
directory: every link in a `SKILL.md` and in every file under its
`reference/` resolves inside the directory you copied. For one project
rather than one user, the same command against that project's
`.claude/skills/`:

```sh
mkdir -p .claude/skills
cp -r skills/athanore-api .claude/skills/athanore-api
```

If you work from a checkout of this repository and want the skill to
follow it, symlink instead, and the copy in your agent is whatever the
checkout says today:

```sh
ln -s "$PWD/skills/athanore-workflows" ~/.claude/skills/athanore-workflows
```

The [`skills` CLI](https://www.npmjs.com/package/skills) knows where
each coding agent keeps its skills, so it can install one without you
looking that up:

```sh
npx skills add <owner>/<repo> --skill athanore-workflows
```

The GitHub form needs this repository to have a remote, which today it
does not; the CLI also takes a local path and a URL.

## What a skill is here

**Self-contained, and generated where it can be.** A skill is read by an
agent that cannot open this repository, so it may not cite the design
documents, may not point at a file in the tree, and may not say "open
the specification". What it needs, it carries — and what it carries is
generated, because a fact restated by hand drifts and a drifted skill is
worse than no skill, since an agent believes it.

- A `SKILL.md` is **hand-written** and is the minimum to act: what the
  surface is, one complete worked example, the rules an agent gets
  wrong on its first attempt, and a map of the skill's own `reference/`
  saying which file answers which question. It is at most 150 lines.
- The skill's `reference/` is the documentation site, **republished**:
  the narrative guide pages under `docs/site/src/guide/` and the
  reference pages that `scripts/gen_docs.py` generates from the code
  and the committed OpenAPI snapshot, copied into each skill by
  `scripts/gen_skills.py` with their links rewritten to resolve inside
  it. One narrative, one place to edit it, and the gate holds the
  copies to it. `athanore-api` also carries the OpenAPI document
  itself, byte for byte, so a client can be generated with no server
  running. Regenerate with:

```sh
uv run scripts/gen_skills.py
```

- Both halves are **gated**. `tests/test_skills.py` asserts that the
  committed files under `reference/` are byte-for-byte what the script
  writes and equal to the site's pages modulo links; that no file under
  `skills/` names the design documents or carries an RFC 2119 keyword;
  that every link in a skill resolves inside it; and that every fence
  in a `SKILL.md` is a marked excerpt of a file in this tree. CI's
  `contract` job regenerates and runs `git diff --exit-code` over
  `skills/` beside `tests/snapshots`, `web/src/api/gen` and
  `docs/site/src/reference`.

`skills/athanore-web` has no `reference/` of its own: the SPA's facts
are TypeScript, and a Python script restating them would be the second,
weaker copy this design exists to prevent. Its reader is a contributor
to this checkout, so it is the one skill that points at files in the
tree — under `web/` and at `AGENTS.md` — and every path it names is
checked to exist.

## Editing one

To change what a skill's `reference/` says, change the guide page under
`docs/site/src/guide/` it was copied from, or the renderer in
`scripts/gen_docs.py` or `scripts/_reference.py`, then run
`uv run scripts/gen_skills.py`. Never edit a file under `reference/`:
the next regeneration overwrites it, and the test fails until then.

To change a `SKILL.md`, keep to what the test holds it to:

- It names no design document and no path in this checkout (the
  `athanore-web` skill excepted, where every path has to exist), and
  carries no capitalised RFC 2119 keyword.
- Every file it names under `reference/` exists, and every file under
  `reference/` is named by it — a generated file the front door never
  mentions is one an agent never loads.
- Every code fence is preceded by a source marker naming the file it
  was taken from — `<!-- from: README.md -->` — and its text appears in
  that file, verbatim or uniformly indented; every ` ```python ` fence
  parses as a module. The marker is for the gate, not the reader. This
  README is the exception: its fences are install commands, which are
  excerpts of nothing.
- It is at most 150 lines, frontmatter included. A skill nobody
  finishes reading is a skill that does not work.

Skills ship in the sdist and not in the wheel, and `pyproject.toml` says
nothing about them: a wheel is what `uv add athanore` installs into a
project, and a skill is installed into an agent, by the commands above.
