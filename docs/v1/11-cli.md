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
token (`athanore token rotate` makes one). `--open` launches the browser,
at the URL that was printed — which on `--port 0` is knowable only once
the socket is bound. Replaces `python -m workflow` (examples keep a
`__main__` that calls `Server` directly for the programmatic form).

```
athanore db upgrade | current | backup <path> | import-v0 <file>
athanore token show | rotate
```

`db` acts on `--db` if it is given and otherwise on the configured
database, so `athanore db upgrade` in a project directory migrates what
`athanore serve` there would open. `backup` is the SQLite backup API (07
§Backups) and refuses another backend, an absent database, and a
destination that already exists. `token rotate` writes
`{root_path}/.athanore/token` mode `0600`, creating `.athanore/` mode
`0700`, and narrows a file that was already wider; `token show` prints
the effective token and where it came from.

## Client connection

`--url` (default `http://127.0.0.1:4002`). No token is needed against a
loopback server. For a network server pass `--token`, set
`ATHANORE_TOKEN`, or store it with `athanore login <url>` in
`~/.config/athanore/config.toml`. `login` prompts for the token with the
input hidden, or takes it as `--token`, and writes the file `0600`.

That file holds `url` and `token` as top-level strings and nothing else;
an unknown key is an error rather than a default silently taken, and
`XDG_CONFIG_HOME` moves the directory if it is set. The url and the token
are resolved independently and in that order — a `--url` on the command
line with a token from the file is the ordinary way to reach a second
server (D142).

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

`answer` resolves its one argument against the request's **mode**, which
is the only fact that is not a guess: a `form` request takes JSON and the
argument must parse as an object, an `options` request takes an option id,
and a `text` request takes the characters that were typed — so an answer
that happens to look like an object still reaches a text question as the
string it is (D145). `permit` and `deny` choose an option by kind
(`allow_once` before `allow_always`, `reject_once` before
`reject_always`), or send the option id they were given.

`--watch` and `-f` use the SSE feed with the same client wrapper the
tests use, keeping the last stored event id they saw so a stream that
drops resumes with `after=` instead of replaying from zero. Ctrl-C ends a
follow successfully; a server that cannot be reconnected to is exit 3.

## Exit codes

0 success, 1 API error (message from the `error` field), 2 usage, 3
server unreachable.

## Not in v1

Driving plugin actions, editing pools at runtime, an interactive shell.
