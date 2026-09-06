# T057 — Theme mapping is the first commit

**Task.** `docs/v1/17-serial-task-plan.md` § `### T057`.
**Specs.** `docs/v1/10-frontend.md` §Design system (normative — the
status colour table and the type scale);
`docs/v1/design/nocturne.css` (the token source);
`docs/v1/design/Athanore.dc.html` (the visual reference).

## What this task is

Finishing the generator T007 scaffolded, so every later SPA task styles
from tokens rather than inventing values. This is the commit that
decides whether the app looks like the mock.

## What this task is not

- **Never hand-edit `web/src/styles/theme.css`** (`AGENTS.md`
  §Conventions). The deliverable is the generator.
- No components beyond the token page.
- No Storybook. `web/src/dev/Tokens.tsx` at `/__tokens`, dev only.

## Steps

Extend `gen-theme.mjs`'s output with:

1. Status colour utilities (`.text-status-ok` …) from 10's table.
2. The type scale: `text-metric` 15/500, `text-body` 12, `text-row`
   11.5, `text-secondary` 11, `text-kicker` 10.5 uppercase with
   `.12em` tracking.
3. Surfaces: `bg-chrome` =
   `color-mix(in srgb, var(--color-surface) 45%, var(--color-bg))`,
   `bg-zebra` at 60 %.
4. `ath-pulse` and `ath-caret` keyframes **guarded by
   `prefers-reduced-motion`** — the guard is part of the deliverable,
   not a later accessibility pass.

The mock carries no `text-shadow` glow, no scan or flicker, and no
`--radius` override (D71): Nocturne's 8 px radius stands. If you find
yourself adding a glow utility because the mock "looks flat", check
`docs/v1/design/Athanore.dc.html` — it is the reference, and it does not
have one.

Then `web/src/dev/Tokens.tsx`, rendering every token and component
primitive at `/__tokens` in dev only.

## Verification

```sh
./scripts/dev.sh "pnpm -C web gen:theme && git diff --exit-code web/src/styles/theme.css"
docker compose --profile web up web     # then open /__tokens
```

Compare `/__tokens` against `docs/v1/design/Athanore.dc.html` side by
side — the palette, the type scale, the surfaces. This one is checked by
eye, and the QA node should be told to open the page and say what it saw
rather than only asserting the file exists.

## Done

- `pnpm gen:theme` is idempotent; the file is generated, never edited.
- `/__tokens` matches the mock's palette.
- `**Status.** Done.` on `### T057`, in the same commit.

## Files

```
web/scripts/gen-theme.mjs
web/src/styles/theme.css     (generated)
web/src/dev/Tokens.tsx
docs/v1/17-serial-task-plan.md
```
