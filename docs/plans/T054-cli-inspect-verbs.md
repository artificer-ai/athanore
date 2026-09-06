# T054 — CLI inspect verbs

**Task.** `docs/v1/17-serial-task-plan.md` § `### T054`.
**Specs.** `docs/v1/11-cli.md` §Inspect verbs and §Tables.
**Reference.** v0's `tests/test_cli_entry.py` (read half).

## What this task is

The read-only half of the CLI: submit a run and then look at things.
Plus the bare-workflow alias, which is the ergonomic trick that makes
`athanore feature_build "title"` work.

## What this task is not

- No state-changing verbs — T054a.
- No direct store access. Everything goes through the API client.

## Steps

1. `submit`, `ls [--status --workflow --watch]`, `show`, `logs [-f]`,
   `stream [-f]`, `workflows`, `requests [run]`, `open [run]`.
2. The bare-workflow alias: a first positional that is **not** in
   `RESERVED` and **is** present in `GET /api/workflows` is treated as a
   submit. Both halves of that check matter — a typo'd workflow name
   must produce a clean error, not a mystery.
3. `--watch` and `-f` use T052's SSE iterator with `after=` on
   reconnect, so a dropped stream resumes rather than replaying from
   zero.
4. Table specs per verb; `--json` emits the API shape unchanged, so a
   script can pipe it to `jq` without learning a second format.

## Verification

`tests/cli/test_inspect_verbs.py`, against a live `Server` on a free
port:

- every verb once in table form and once as `--json`;
- the alias;
- `logs -f` observes a live event;
- exit code 3 when the server is down.

## Done

- Tests pass.
- `**Status.** Done.` on `### T054`, in the same commit.

## Files

```
athanore/cli/inspect.py
tests/cli/test_inspect_verbs.py
docs/v1/17-serial-task-plan.md
```
