# T029 — Phase 1 checkpoint

**Task.** `docs/v1/17-serial-task-plan.md` § `### T029`.
**Specs.** `docs/v1/13-testing.md` §Definition of done.

## What this task is

A checkpoint, not a feature. Prove Phase 1 hangs together, write down
the two details the phase decided implicitly, and tag.

## What this task is not

- **No new code.** If the checkpoint finds a defect, that is a finding
  to report, not licence to fix it here — fixing it silently at a
  checkpoint hides which task shipped the bug.
- No push. The tag is local; there is no remote (see T006).

## Steps

1. Run the whole gate and read the output rather than glancing at the
   exit code: `./scripts/test.sh`.
2. Confirm `lint-imports` passes with the layering contracts now that
   `engine` and `store` are populated — this is the first checkpoint
   where the contracts have real code to constrain.
3. Update `docs/v1/04-engine.md` with the two details Phase 1 decided:
   - an **empty list** return is terminal with `value=[]` (T021);
   - a `None` payload **is** passed to the body rather than omitted
     (T024).
   If T021 and T024 already updated 04, verify the text says what the
   code does and say so; do not duplicate it.
4. `git tag v1.0.0a1` locally.

## Verification

```sh
./scripts/test.sh
./scripts/dev.sh "uv run lint-imports"
git tag -l v1.0.0a1
```

Then read `docs/v1/04-engine.md` against `athanore/engine/routing.py`
and `runner.py` — the checkpoint's real work is confirming the document
and the code still say the same thing.

## Done

- Gate green; contracts pass; 04 accurate; tag exists locally.
- Anything that looks wrong is written up in the TaskReport rather than
  fixed here.
- `**Status.** Done.` on `### T029`, in the same commit.

## Files

```
docs/v1/04-engine.md
docs/v1/17-serial-task-plan.md
```
