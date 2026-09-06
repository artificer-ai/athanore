# T065 — Token screen and 401 handling

**Task.** `docs/v1/17-serial-task-plan.md` § `### T065`.
**Specs.** `docs/v1/12-security.md` §Auth; `docs/v1/10-frontend.md`
§Overlays.

## What this task is

What the SPA does when the server wants a token: one overlay, one place
that stores it, and the SSE URL that carries it.

## What this task is not

- **Nothing on loopback.** With `auth === "off"` this never appears;
  T059's gate already decides that.
- No token in application state beyond prefs, and never in a logged
  URL.

## Steps

1. `TokenScreen` overlay using the same backdrop and panel idiom as the
   other overlays: an input, save to prefs, retry `/api/me`.
2. Shown when `auth === "token" && !authenticated`, or after any 401
   (T059's interceptor sets the flag).
3. The SSE URL gains `access_token` — the one sanctioned query-param use
   (T043, T060).

## Verification

Vitest:

- a 401 shows the screen;
- the token is stored and sent on the next request;
- clearing it returns to the screen.

Then the real check the task names: run
`athanore serve --host 0.0.0.0` with a rotated token and use the SPA
against it, including the event stream.

## Done

- Tests pass; verified against a non-loopback server.
- `**Status.** Done.` on `### T065`, in the same commit.

## Files

```
web/src/components/TokenScreen.tsx
web/src/api/client.ts
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
