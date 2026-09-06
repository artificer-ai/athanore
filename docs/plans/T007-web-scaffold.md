# T007 — `web/` scaffold and the Nocturne theme

**Task.** `docs/v1/17-serial-task-plan.md` § `### T007`.
**Specs.** `docs/v1/10-frontend.md` §Design system and §Tokens → shadcn
(normative); `docs/v1/design/nocturne.css` (the token source);
`docs/v1/design/Athanore.dc.html` (the layout and copy reference);
`docs/v1/02-architecture.md` §Library choices (the fixed frontend stack).

## What this task is

The SPA's skeleton and its theme pipeline. After this commit the gate
grows four steps — `./scripts/test.sh` runs `pnpm typecheck`, `pnpm
lint`, `pnpm test` and `pnpm build` as soon as `web/package.json`
exists — so all four have to pass, not just `build`.

## What this task is not

- **No application UI.** `App.tsx` renders the brand mark on
  `--color-bg` and nothing else. The dashboard, the run views, the
  graph and the inbox are T057 onward.
- **No API client.** T008 owns `web/src/api/gen` and the OpenAPI
  pipeline. Do not hand-write a fetch layer here.
- **No hand-editing `web/src/styles/theme.css`.** It is generated; the
  generator is the deliverable. A hand edit is a defect the reviewer
  will reject on sight (`AGENTS.md` §Conventions).

## Steps

1. `pnpm-workspace.yaml` with `packages: ["web"]`.
2. Scaffold with `pnpm create vite web --template react-ts`; React 19;
   TS strict plus `noUncheckedIndexedAccess` and
   `exactOptionalPropertyTypes`.
3. Tailwind v4 through `@tailwindcss/vite`; `pnpm dlx shadcn@latest init`
   with style `new-york` and CSS variables on;
   `@fontsource-variable/jetbrains-mono`; `@phosphor-icons/react`.
4. `web/scripts/gen-theme.mjs`: read `docs/v1/design/nocturne.css`, copy
   every `--color-*`, `--space-*`, `--shadow-*` and `--ath-*` token into
   `web/src/styles/theme.css` under `:root`; append the shadcn mapping
   block from 10 §Tokens → shadcn, the `@theme inline` block that
   exposes them to Tailwind, and the app type scale (12 px base,
   JetBrains Mono). No `--radius` override — Nocturne's 8 px stands
   (D71). Wire it as `pnpm gen:theme`.
5. Staleness check: regenerating must produce no diff, and CI must fail
   when it does. Same shape as T008's contract check.
6. `vite.config.ts`: `build.outDir = "../athanore/web/dist"`,
   `emptyOutDir: true`, `server.proxy["/api"] → http://127.0.0.1:4002`.

## Dev stack

`pnpm` runs **inside the `dev` container** and `node_modules` lives on a
named volume, so every install goes through `./scripts/dev.sh` or
`pnpm -C web` in a container shell. Running `pnpm install` on the host
writes a `node_modules` the gate will not use.

## Verification

```sh
./scripts/dev.sh "pnpm -C web install && pnpm -C web gen:theme && git diff --exit-code web/src/styles/theme.css"
./scripts/dev.sh "pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test && pnpm -C web build"
ls athanore/web/dist/index.html
./scripts/dev.sh "uv build && unzip -l dist/*.whl | grep web/dist"
./scripts/test.sh                      # now includes the four web steps
```

Then open it: `docker compose --profile web up web` and load
`http://127.0.0.1:5173` — the brand mark on the Nocturne background,
JetBrains Mono, no default Vite artwork left anywhere.

## Done

- `pnpm build` writes `athanore/web/dist/index.html`; the wheel contains
  it.
- `pnpm gen:theme` is idempotent and `theme.css` is generated, never
  hand-edited.
- `./scripts/test.sh` green with the web steps now running.
- `**Status.** Done.` on `### T007`, in the same commit.

## Files

```
pnpm-workspace.yaml
web/**                       (scaffold, config, App.tsx, scripts/gen-theme.mjs)
web/src/styles/theme.css     (generated)
athanore/web/dist/           (build output, git-ignored except .gitkeep)
docs/v1/17-serial-task-plan.md
```
