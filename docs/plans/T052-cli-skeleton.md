# T052 — CLI skeleton, client, output

**Task.** `docs/v1/17-serial-task-plan.md` § `### T052`.
**Specs.** `docs/v1/11-cli.md` §Structure, §Config resolution, §Exit
codes; `AGENTS.md` §Architecture rules — clients get connection-level
retries at most.

## What this task is

The CLI's spine: a typer app, an httpx client that speaks the same API
as everything else, and one place that decides how output is rendered
and what the exit code is.

## What this task is not

- No verbs yet — T053 onward.
- **The CLI is an API client.** It does not import the engine or the
  store, and it does not reach into a database. One wire contract.
- No request-level retry logic. `HTTPTransport(retries=2)` is
  connection-level and that is the ceiling.

## Steps

1. `athanore/cli/__init__.py` — the typer `app`.
2. `cli/verbs.py`: `RESERVED = {serve, db, token, login, submit, ls,
   show, logs, stream, workflows, requests, answer, permit, deny, pause,
   resume, cancel, rm, rerun, retry, move, set-status, edit, position,
   open}` — T051 checks workflow names against this, so it lives where
   both can import it without a cycle. **Already written**, by T051,
   which is its first reader (D141): the file is there and holds exactly
   this set, so this step is done.
3. `cli/client.py`: `Client(url, token)` over httpx with
   `transport=HTTPTransport(retries=2)`, the bearer header, and an
   `events(after, names)` SSE iterator **shared with the tests**.
   Config resolution order: `--url/--token`, then
   `ATHANORE_URL`/`ATHANORE_TOKEN`, then
   `~/.config/athanore/config.toml`.
4. `cli/output.py`: `emit(data, table_spec, json_flag)` — a rich table
   or JSON — and a `main()` wrapper mapping exceptions onto exit codes
   0/1/2/3 (`ApiClientError`, `typer.BadParameter`,
   `httpx.ConnectError`).

## Verification

`tests/cli/test_client.py`:

- each exit code, driven by the matching failure;
- `--json` output parses as JSON and contains the same data the table
  renders;
- the config resolution order, including the file.

## Done

- Tests pass.
- `**Status.** Done.` on `### T052`, in the same commit.

## Files

```
athanore/cli/{__init__.py,verbs.py,client.py,output.py}
tests/cli/test_client.py
docs/v1/17-serial-task-plan.md
```
