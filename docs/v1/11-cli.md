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

What is served, in order (09 §Discovery has the same rules from the
plugin side; 22 §Persistence gives the precedence its reason):

1. **The targets given**, in the order they were given. A target is
   `module:attr` or `path/to/file.py:attr`, resolved by
   `athanore.plugins.discovery.load_target` — the loader lives beside
   the entry-point loader so the API can reach it without importing the
   CLI (22 §Reloading a module) — and the attribute may be the
   `Workflow` or a callable returning one, as an entry point's may.
   Every failure to resolve one — no such module, no such file, no such
   attribute, an attribute that is not a `Workflow` — costs 2. The name
   registered is the workflow's own, not the target's.
2. **Then the rows of `athanore.toml`** that carry a `target`
   (`[workflows.<name>] = { target = "…", pool? }`), in the file's
   order, through the same loader and at the same price: a failure to
   load costs 2 and names the row, the target and the cause, and so
   does a row whose key is not the loaded workflow's name — the row is
   a registration, and one under the wrong name is a typo. A row whose
   name a target already registered is skipped with a warning naming
   both targets: the positional is the working copy and wins.
3. **Then the entry points**, unless `--no-discover`. A discovered
   workflow whose *workflow name* a target or a row already registered
   is dropped: an explicit target wins, so a working copy can be served
   without uninstalling the package that ships it. An entry point that
   cannot be loaded is not skipped — it names itself, its distribution
   and its cause, and exits 1.
4. **Then the pools.** `[workflows.<name>].pool` binds a workflow, by
   workflow name, to the capacity `[pools]` declares for that name; a
   workflow nothing binds runs on the default pool, sized by `--workers`.
   A binding naming a pool `[pools]` does not declare costs 2 and names
   the pool — it is a typo, and a typo that fell back to the default
   would put the work on the wrong capacity for as long as nobody looked.
   A binding for a workflow this server does not run is a warning, said
   once: an `athanore.toml` describes a project's workflows, and serving
   one of them on purpose is ordinary.

`serve` records the target of every workflow it loads — each positional
as it was given, each row's `target`, each discovered entry point as its
`module:attr` value — on the server (`Server.targets`, 04 §Programmatic
host), so that a later reload of the name can re-resolve what `serve`
loaded (22 §Terms).

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
athanore workflows add <target> [--pool NAME] [--persist]             → POST   /api/workflows
athanore workflows reload <name> [<target>] [--pool NAME] [--persist] → PUT    /api/workflows/{name}
athanore workflows rm <name> [--persist]                              → DELETE /api/workflows/{name}
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

`athanore workflows` stays the table it is, and is a group: its three
subcommands are thin clients of the three live-registration routes (22
§CLI). `add` and `reload` print the workflow as the table prints one
entry, with `target=` beside the pool when the server reports one;
`rm` prints the interrupted task ids, one per line, so the operator
sees what stopped. `--persist` is the body's `persist` (`?persist=` on
`rm`), and a verb whose response carries `X-Athanore-Persisted` prints
`persisted to <path>` / `removed from <path>` as its last line — on
stderr under `--json`, so stdout stays the API's JSON (D252). A
`workflow_load_failed` prints `stage` and `detail` under the message
and exits 2 — the same price §Exit codes puts on a target `serve` could
not resolve, because it is the same mistake — and an `unknown_pool`
exits 2 for the reason §Server refuses a binding to one (D252). Every
other refusal is the server's sentence and exit 1.

## Exit codes

0 success, 1 API error (message from the `error` field), 2 usage, 3
server unreachable.

## Not in v1

Driving plugin actions, editing pools at runtime, an interactive shell.
