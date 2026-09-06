# T047 — Static SPA, CSP, and CORS

**Task.** `docs/v1/17-serial-task-plan.md` § `### T047`.
**Specs.** `docs/v1/12-security.md` §Plugins (the CSP header, verbatim);
`docs/v1/08-api.md` §Static.
**Reference.** v0's `tests/test_web_serve.py`.

## What this task is

Serving the built SPA from the package, with the content-security policy
that keeps a plugin's assets from doing whatever they like, and CORS only
when it is explicitly configured.

## What this task is not

- No plugin asset mounting yet — T070 uses the hook this task leaves.
- **CORS is off by default.** It is enabled only when `cors_origins` is
  set; a wildcard default would undo the loopback-first posture.

## Steps

1. `athanore/api/static.py`: mount `athanore/web/dist` at `/`, with SPA
   fallback to `index.html` for non-`/api` paths.
2. The plugin assets mount hook (unused until T070).
3. The CSP header from 12 §Plugins on HTML and asset responses.
4. `CORSMiddleware` only when `cors_origins` is non-empty.
5. When `dist/index.html` is missing, serve a minimal "build the SPA"
   page rather than a stack trace — a fresh checkout without a `pnpm
   build` is the common case, not an error.

## Careful

`/api/...` must 404 as **JSON**, not as the SPA's `index.html`. A
catch-all that swallows unknown API paths turns every client typo into a
200 with HTML, which is maddening to debug from the SPA side.

## Verification

`tests/api/test_static.py`, porting v0's file:

- `/` returns HTML with the CSP header;
- `/api/nothing` is 404 **JSON**;
- with `dist` absent, `/` returns the build-the-SPA page;
- CORS headers absent by default, present with `cors_origins` set.

## Done

- Tests pass; ledger row for `test_web_serve.py` ticked.
- `**Status.** Done.` on `### T047`, in the same commit.

## Files

```
athanore/api/static.py
tests/api/test_static.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
