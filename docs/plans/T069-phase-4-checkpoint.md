# T069 — Phase 4 checkpoint

**Task.** `docs/v1/17-serial-task-plan.md` § `### T069`.
**Specs.** `docs/v1/13-testing.md` §Definition of done;
`docs/v1/14-migration-and-phasing.md` §Packaging.

## What this task is

The checkpoint that proves the SPA actually ships inside the wheel — the
one integration nothing else tests.

## What this task is not

- No new code, no UI changes. Deviations are recorded, not fixed.

## Steps

1. CI runs `pnpm build` **before** `uv build`, so the wheel contains a
   fresh SPA rather than whatever was last built locally.
2. Confirm the wheel contains it, and that `athanore serve` from a
   **clean venv** shows the UI — not the dev server, and not a
   source checkout.
3. Update `docs/v1/10-frontend.md` with any deviations found while
   building the SPA, and record each in `docs/v1/15-decisions.md`.

## Verification

```sh
./scripts/dev.sh "pnpm -C web build && uv build && unzip -l dist/*.whl | grep web/dist"
./scripts/dev.sh "python -m venv /tmp/clean && /tmp/clean/bin/pip install dist/*.whl \
  && /tmp/clean/bin/athanore serve --port 0 &"   # then curl the printed URL
```

The clean-venv step is the one that catches a wheel that builds but does
not serve.

## Done

- The wheel carries the SPA; a clean install serves it.
- 10 updated, deviations in 15.
- `**Status.** Done.` on `### T069`, in the same commit.

## Files

```
.github/workflows/ci.yml
docs/v1/{10-frontend.md,15-decisions.md}
docs/v1/17-serial-task-plan.md
```
