# The command line

`athanore` is a small program: one server verb, and a set of client verbs
that are thin wrappers over the HTTP API. It is deliberately not the full
operator surface — the browser interface is — but it is enough to start a
server, submit work, look at a run and answer a question from a shell or
a script.

Every command, its arguments and its options are in
[Command line](../reference/cli.md), generated from the command tree
itself.

## Serving

```sh
athanore serve                                   # whatever is installed
athanore serve hello.py:wf                       # a file, and the object in it
athanore serve myproject.flows:build --workers 4
athanore serve --host 0.0.0.0 --port 8080        # needs an operator token
athanore serve --open                            # ...and open a browser at it
```

What gets served, in order: the targets you named, then any installed
workflows advertised as entry points unless you pass `--no-discover`,
then the pool bindings from `athanore.toml`. A named target wins over a
discovered workflow of the same name, so you can serve a working copy of
an installed workflow without uninstalling it.

`serve` also runs any outstanding migrations before it serves, and prints
the URL it bound — which on `--port 0` is knowable only once the socket
exists.

## Finding a server

Client verbs default to `http://127.0.0.1:4002`, and a loopback server
needs no credential at all. For a server on a network:

```sh
athanore --url https://athanore.example.com --token "$TOKEN" ls
ATHANORE_TOKEN="$TOKEN" athanore --url https://athanore.example.com ls
athanore login https://athanore.example.com     # prompts, then remembers
```

`login` writes the URL and the token to your user configuration
directory with restrictive permissions. The URL and the token are
resolved independently, so a `--url` on the command line with a token
from the file is the ordinary way to reach a second server.

Three verbs talk to no server at all: `athanore db` acts on the database
directly, and `athanore token` and `athanore login` read and write files.

## The verbs

```sh
athanore submit <workflow> "<title>" ["<description>"]
athanore ls [--status s] [--workflow w] [--watch]
athanore show <run>
athanore logs <run> [-f]
athanore stream <task> [-f]
athanore workflows
```

```sh
athanore requests [run]
athanore answer <req> <option | text | json>
athanore permit <req> [option]
athanore deny <req>
```

```sh
athanore pause <run> | resume <run> | cancel <run> | rm <run>
athanore rerun <run> <node> | retry <task> | move <task> <node>
athanore set-status <task> <status>
athanore edit <run> [--title] [--description]
athanore position <run> up|down|<index>
athanore open [run]
```

```sh
athanore db upgrade | current | backup <path> | import-v0 <file>
athanore token show | rotate
```

The bare form `athanore <workflow> "title"` is an alias for `submit`,
which is why a workflow may not be named after a verb — that is refused
when it is registered rather than resolved by precedence later.

## JSON out

Every read verb takes `--json`, so the command line composes with `jq`
rather than growing a query language:

```sh
athanore ls --json | jq -r '.[] | select(.status == "failed") | .id'
athanore show "$RUN" --json | jq '.tasks[] | {node, status, attempt}'
athanore requests --json | jq 'length'
```

On a terminal the same verbs print a table.

## Following

`--watch` on `ls` and `-f` on `logs` and `stream` follow the server-sent
event stream, remembering the last event they saw so a dropped connection
resumes instead of replaying from the beginning. Ctrl-C ends a follow
successfully.

## Exit codes

A script can branch on the status:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | the API refused, and the message is what it said |
| 2 | usage: a bad flag, an unresolvable target, a pool binding naming a pool nothing declares |
| 3 | the server could not be reached |

## Next

- [Deployment](deployment.md) — `athanore.toml`, tokens, migrations and
  backups.
- [Command line](../reference/cli.md) — every command, generated.
