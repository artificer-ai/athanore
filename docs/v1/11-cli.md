# 11 — CLI

`athanore` is a thin client over the HTTP API plus one server verb.
Deliberately small: enough to start a server, submit work, inspect a run,
and answer a request from a shell or a script. The SPA is the full
operator surface.

Implementation: typer + rich + httpx, in `athanore/cli/`. Output is a
table or text on a TTY and JSON with `--json` everywhere, so it composes
with `jq`.

## Server

```
athanore serve [module:wf ...] [--host] [--port] [--workers N] [--db URL]
               [--no-discover] [--public-url URL] [--open]
```

Registers entry-point workflows (unless `--no-discover`) and any explicit
`module:wf` / `path/to/file.py:wf`, reads pools from `athanore.toml`, runs
migrations, and prints the URL. A non-loopback `--host` needs an operator
token (`athanore token rotate` makes one). `--open` launches the browser. Replaces `python -m workflow`
(examples keep a `__main__` that calls `Server` directly for the
programmatic form).

```
athanore db upgrade | current | backup <path> | import-v0 <file>
athanore token show | rotate
```

## Client connection

`--url` (default `http://127.0.0.1:4002`). No token is needed against a
loopback server. For a network server pass `--token`, set
`ATHANORE_TOKEN`, or store it with `athanore login <url>` in
`~/.config/athanore/config.toml`.

## Verbs

```
athanore submit <workflow> "<title>" ["<description>"]     → run id
athanore ls [--status s] [--workflow w] [--watch]          runs table
athanore show <run>                                        run + tasks + log
athanore logs <run> [-f]                                   events; -f follows via SSE
athanore stream <task> [-f]                                agent transcript
athanore workflows                                         graphs + pools
athanore requests [run]                                    pending requests
athanore answer <req> <option-id | text | json>
athanore permit <req> [option-id]     athanore deny <req>
athanore pause <run> | resume <run> | cancel <run> | rm <run>
athanore rerun <run> <node> | retry <task> | move <task> <node> | set-status <task> <status>
athanore edit <run> [--title] [--description]
athanore position <run> up|down|<index>
athanore open [run]                                        open the SPA in a browser
```

The MVP's bare `athanore <workflow> "title"` shorthand is kept as an alias
of `submit` (first positional that is not a verb and matches a registered
workflow), with the same "workflow names cannot shadow verbs" validation
at registration.

`--watch` and `-f` use the SSE feed with the same client wrapper the
tests use.

## Exit codes

0 success, 1 API error (message from the `error` field), 2 usage, 3
server unreachable.

## Not in v1

Driving plugin actions, editing pools at runtime, an interactive shell.
