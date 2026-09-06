# T078 — README, docs final pass, deprecation aliases

**Task.** `docs/v1/17-serial-task-plan.md` § `### T078`.
**Specs.** `docs/v1/README.md` (the document map this updates);
`docs/v1/14-migration-and-phasing.md` §Compatibility.

## What this task is

The documentation pass: a README someone can start from, and a sweep for
statements the implementation made false.

## What this task is not

- No code changes beyond the alias check.
- Not a rewrite of `docs/v1/`. It is a **staleness** pass: the
  decisions log records what changed; this task makes the prose match.

## Steps

1. Rewrite `README.md`: install, `athanore serve`, a first workflow, and
   a link to `docs/v1`.
2. `DESIGN.md` gets a one-paragraph banner pointing at `docs/v1`.
3. Verify every `AthanoreX` alias warns **once** — not per access, and
   not never.
4. Sweep `docs/v1/*` for statements the build falsified, and add this
   plan set (`docs/plans/`) to the map in `docs/v1/README.md`.

## Verification

```sh
grep -r "ARTIFICER\|artificer" athanore     # only the deprecation shim
./scripts/dev.sh "uv run pytest -q tests/test_public_api.py"
```

For the staleness sweep, read `docs/v1/15-decisions.md` from D59 to the
end and check each row's document actually says what the row decided —
that is a finite, checkable list rather than a re-read of everything.

## Done

- README rewritten; the grep is clean; aliases warn once.
- `docs/v1/README.md` lists `docs/plans/`.
- `**Status.** Done.` on `### T078`, in the same commit.

## Files

```
README.md
DESIGN.md
docs/v1/README.md
docs/v1/**            (staleness fixes)
docs/v1/17-serial-task-plan.md
```
