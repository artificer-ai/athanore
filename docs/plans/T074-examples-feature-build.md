# T074 — `examples/` and porting `feature_build`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T074`.
**Specs.** `docs/v1/11-cli.md` §Programmatic form;
`docs/v1/05-agents.md` §Agent classes;
`AGENTS.md` §Architecture rules (small core).
**Reference.** v0's `workflow/` package — the behavioural reference,
never copied (D65).

## What this task is

The first real workflows, written fresh in the v1 API, living outside
the package where vendor knowledge belongs.

## What this task is not

- **Nothing lands in `athanore/`.** If an example needs a core change,
  that is a finding, not an import.
- No unpinned agent commands. `pi-acp@X.Y.Z` pinned to the version in
  `uv.lock` / the current install — a floating adapter is exactly the
  risk the stack section calls out.
- No prompt templates: prompts are inlined text on the agent classes
  (`AGENTS.md`), byte-exact where 19 specifies them.

## Steps

1. Write `examples/{feature_build,gamedev,...}` fresh against the v1
   API, using v0's `workflow/` as the behavioural reference.
2. `examples/pyproject.toml` gains
   `[project.entry-points."athanore.workflows"]` for each — that is how
   T072's discovery finds them.
3. `feature_build`: `Workflow`, `ACPAgent` with the pinned command,
   `stats_provider=PiSessionStats()` (T040), and **node options**
   (`retries`, `timeout`) where v0 used ad-hoc retry code — the whole
   point of T019's options.
4. `examples/__main__.py` builds a `Server` programmatically.

## Verification

`examples/tests/test_feature_build.py`:

- the graph shape (nodes, edges, the loop-back);
- prompts inlined on the classes, not loaded from files;
- output models declared where the workflow routes on them.

Then: `athanore serve` discovers `feature_build` without being told
about it.

## Done

- Tests pass; discovery finds the workflow.
- `**Status.** Done.` on `### T074`, in the same commit.

## Files

```
examples/feature_build/**
examples/pyproject.toml
examples/__main__.py
examples/tests/test_feature_build.py
docs/v1/17-serial-task-plan.md
```
