# T080 — Re-import the design and regenerate the theme

**Task.** `docs/v1/17-serial-task-plan.md` § `### T080`.
**Specs.** `docs/v1/21-design-refresh.md` §Re-import (normative);
`docs/v1/10-frontend.md` §Design system (the sections to sync);
`docs/v1/design/README.md` (the current import's provenance and
curation); D150 (the generator's guarantees), D198 (the stop-and-ask
triggers).

## Precondition (read first)

The refreshed artifacts are not in the repository and DesignSync is not
authorized on this machine. Before doing anything else, check, in order:

1. Did the operator drop refreshed `Athanore.dc.html` / `nocturne.css`
   into `docs/v1/design/` (does `git log` show them changed since
   2026-09-05, or did the run's instructions say so)? Use those.
2. Otherwise, try one read-only DesignSync `list_files` against project
   `b7cb5192-4374-44e3-ae8f-2563907fa4ea`. If it succeeds, the operator
   has run `/design-login`; fetch the two files.
3. Otherwise **stop and report blocked** — ask the operator to run
   `/design-login` once from an interactive session or to provide the
   files. Do not synthesize "refreshed" artifacts, and do not close the
   task as done-with-nothing-changed.

## What this task is

The import refresh and everything downstream of it that is mechanical:
the regenerated theme, the synced spec, and the decision rows for
whatever the app deliberately does not follow.

- Replace the two files **verbatim** from the source, keeping the
  current curation of `nocturne.css` (only the `:root` token blocks, the
  application overrides and the keyframes — its header comment is the
  rule). Update the import date in `docs/v1/design/README.md`.
- `pnpm -C web gen:theme` — the *only* way any change reaches
  `web/src/styles/theme.css` and `tokens.gen.ts`.
- Diff old→new `nocturne.css` and account for **every** hunk: value
  changes flow through the regen; anything the app will not follow gets
  a row in `15-decisions.md` saying why (D71 is the model). A reviewer
  must be able to check the mapping is total.
- Update `docs/v1/10-frontend.md` §Design system wherever a token or
  treatment changed (the tokens → shadcn table, §Status colours, §Type
  and density values).

## Stop-and-ask triggers (D198)

Stop and ask the operator — do not reconcile silently — if the refreshed
artifacts:

- add or remove an `--ath-status-*` name (the generator refuses anyway;
  the answer decides the utility list and 10's table);
- add a second theme or mode (changes the theme architecture and D150);
- change token *families* (a new ramp, a removed ramp) rather than
  values;
- prescribe a mobile layout or a font-size control that differs from
  `21` §Narrow layout / §Type scale — T082/T083/T081 build to 21, and
  only the operator can rule that the mock supersedes it.

## What this task is not

- **Never hand-edit `theme.css` or `tokens.gen.ts`** (AGENTS.md
  §Conventions). If the regen output looks wrong, the fix is in
  `gen-theme.mjs` or in the source file.
- No component changes, no new utilities, no generator features. If a
  refreshed value breaks a component visually, note it for the operator;
  restyling is not this task.
- Not the rem ramp (T081), not the breakpoint (T082). If the refreshed
  `--ath-font-size` changed, the value flows through and T081's
  multipliers pick it up later — do not anticipate.
- No change under `athanore/`, `web/src/` (beyond the two generated
  files), or the snapshot.

## Verification

```sh
./scripts/dev.sh "pnpm -C web gen:theme && git diff --exit-code web/src/styles"
./scripts/test.sh
git diff --exit-code tests/snapshots
git diff v1.0.0 -- docs/v1/design/nocturne.css   # the diff the mapping must cover
```

Open `/__tokens` (`docker compose --profile web up web`) and compare
against the refreshed `Athanore.dc.html` by eye — palette, type, the
surfaces — and say what you saw.

## Done

- `docs/v1/design/` carries the refreshed artifacts and the new date.
- The regenerated theme is committed; a second `gen:theme` is a no-op.
- Every old→new `nocturne.css` difference is in the theme or in a
  decision row.
- 10 §Design system agrees with the regenerated theme.
- Gate green; `tests/snapshots/openapi.json` byte-identical.
- `**Status.** Done.` on `### T080`, in the same commit.

## Files

```
docs/v1/design/Athanore.dc.html      (refreshed, verbatim)
docs/v1/design/nocturne.css          (refreshed, verbatim)
docs/v1/design/README.md             (import date)
web/src/styles/theme.css             (generated)
web/src/styles/tokens.gen.ts         (generated)
docs/v1/10-frontend.md               (§Design system sync)
docs/v1/15-decisions.md              (one row per deviation)
docs/v1/17-serial-task-plan.md       (Status line)
```
