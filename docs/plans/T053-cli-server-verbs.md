# T053 — CLI server-side verbs: `serve`, `db`, `token`, `login`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T053`.
**Specs.** `docs/v1/11-cli.md` §Server verbs; `docs/v1/12-security.md`
§Token storage (the file mode); `docs/v1/14-migration-and-phasing.md`
§Importing v0.

## What this task is

The verbs that run or repair an installation, as opposed to the ones
that drive a running server.

## What this task is not

- No discovery yet — T072 fills the hook `serve` leaves.
- No operator verbs (T054).
- The token file is **not** a config value. It lives in
  `.athanore/token`, mode `0600`, and is refused in `athanore.toml`
  (`AGENTS.md` §Conventions).

## Steps

1. `serve [targets...] --host --port --workers --db --no-discover
   --public-url --open`: load `module:attr` or `path.py:attr` targets,
   call the discovery hook, read `[pools]` and `[workflows]` from
   `athanore.toml`, build a `Server`, print the URL, and
   `webbrowser.open` on `--open`.
2. `db upgrade | current | backup <path> | import-v0 <file>` — the
   backup through `sqlite3.Connection.backup` (a consistent copy of a
   live WAL database, which `cp` is not).
3. `token show | rotate` — create `.athanore/` and write the file
   `0600`.
4. `login <url>` — prompt for the token and store it.

## Verification

`tests/cli/test_serve.py`:

- `serve path.py:wf --port 0` starts and answers `/api/health`, run as a
  **subprocess with a timeout** so a hang fails the test rather than the
  suite;
- `token rotate` produces mode `0600` — assert the bits, on a fresh
  directory and on an existing one;
- `db import-v0` against T018's fixture;
- `db backup` produces a file that opens and has the same run count.

## Done

- Tests pass.
- `**Status.** Done.` on `### T053`, in the same commit.

## Files

```
athanore/cli/serve.py
athanore/cli/db.py
athanore/cli/token.py
tests/cli/test_serve.py
docs/v1/17-serial-task-plan.md
```
