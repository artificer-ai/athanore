# T079 — Audits, coverage gates, release

**Task.** `docs/v1/17-serial-task-plan.md` § `### T079`.
**Specs.** `docs/v1/13-testing.md` §Gates;
`docs/v1/14-migration-and-phasing.md` §Release.

## What this task is

The last task: turn on the audits, run the store suite against a real
Postgres, build the wheel, prove it works from a clean machine, and tag.

## What this task is not

- No new features, no last-minute fixes. Something that fails here is a
  finding that gets its own task.
- **No push without a remote.** T006 established there is none; if that
  is still true, tag locally and say so rather than inventing one.

## Steps

1. CI: `pip-audit`, `pnpm audit --audit-level high`, the coverage gates
   enforced, and the nightly Postgres job running the store suite **for
   real** — remove the skip that made it a no-op.
2. `uv build`; install the wheel into a clean venv; run
   `athanore serve examples...:feature_build --port 0`; browse it.
3. Bump the version to `1.0.0`, tag, and push if a remote exists.

## Verification

```sh
./scripts/dev.sh "uv run pip-audit"
./scripts/dev.sh "pnpm -C web audit --audit-level high"
docker compose --profile pg up -d postgres
./scripts/dev.sh "uv run pytest -q -m postgres"
./scripts/dev.sh "uv build"
# clean venv install, serve, and drive msgtest on FakeACPAgent
```

The final check is the one that matters: a wheel on a clean machine
serves the SPA and runs `msgtest` on `FakeACPAgent`. Report what you
actually observed, screen by screen.

## Done

- Audits clean or their findings reported; gates enforced; Postgres
  suite green for real.
- Tag `v1.0.0` exists; the clean-machine check passed.
- `**Status.** Done.` on `### T079`, in the same commit.

## Files

```
.github/workflows/{ci.yml,nightly.yml}
pyproject.toml
docs/v1/17-serial-task-plan.md
```
