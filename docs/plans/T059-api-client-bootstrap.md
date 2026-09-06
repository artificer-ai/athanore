# T059 — API client bootstrap, `/api/me`, query provider

**Task.** `docs/v1/17-serial-task-plan.md` § `### T059`.
**Specs.** `docs/v1/10-frontend.md` §Data layer;
`docs/v1/12-security.md` §Auth (what the SPA must and must not store).

## What this task is

Wiring the generated client into the app: base URL, the auth
interceptor, the query provider's defaults, and the gate that decides
whether to show the token screen.

## What this task is not

- **No hand-written API calls.** The client is generated from the
  OpenAPI snapshot and committed (T008); using `fetch` directly anywhere
  in the SPA defeats the one-wire-contract rule.
- No token screen yet — T065. `AppGate` just decides when it is needed.
- No polling. SSE (T063) is how the SPA stays current.

## Steps

1. `web/src/api/client.ts`: configure the generated fetch client with
   `baseUrl: ""`; an auth interceptor adding `Authorization` from prefs
   **only when `/api/me.auth === "token"`**; and a 401 interceptor
   setting `useUi.needsToken = true`.
2. `QueryClientProvider` with `staleTime: 5000`, `retry: 1`. Low retry
   on purpose: the SPA is talking to localhost, and a retry storm
   against a paused server helps nobody.
3. `useMe()`, and `AppGate` rendering the token screen when needed, else
   the shell.

## Verification

Vitest with a mocked fetch:

- no `Authorization` header on a loopback server reporting `auth: off`;
- the header present when `auth: token` and a token is stored;
- a 401 flips `needsToken`;
- `staleTime` and `retry` defaults are what the provider was given.

Then, on a loopback dev server: the data-free shell renders **without
prompting for a token**, which is the whole point of the loopback rule.

## Done

- The shell loads unprompted on loopback.
- `**Status.** Done.` on `### T059`, in the same commit.

## Files

```
web/src/api/client.ts
web/src/app/{AppGate.tsx,providers.tsx}
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
