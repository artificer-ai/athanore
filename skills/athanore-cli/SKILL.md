---
name: athanore-cli
description: Serve and steer Athanore from a terminal — `athanore serve` and its module:wf targets, the client verbs and how they find a server, `--json` output, `athanore.toml` and pools, deployment, and the exit codes. Load this before writing a command line, a shell script or a crontab entry against Athanore.
---

# Using the Athanore command line

The command line is a small program: one server verb, and a set of
client verbs that are thin wrappers over the HTTP API. It is not the full
operator surface — the browser interface is — but it is enough to start
a server, submit work, look at a run and answer a question from a shell
or a script. This directory is self-contained: every file it names is
under its own `reference/`.

## A complete session

Serve one workflow, or several, or whatever is installed:

<!-- from: docs/site/src/guide/cli.md -->
```sh
athanore serve                                   # whatever is installed
athanore serve hello.py:wf                       # a file, and the object in it
athanore serve myproject.flows:build --workers 4
athanore serve --host 0.0.0.0 --port 8080        # needs an operator token
athanore serve --open                            # ...and open a browser at it
```

Then, from a second shell, submit a run, watch it stop on a question,
answer it and read the output:

<!-- from: docs/site/src/quickstart.md -->
```sh
athanore submit hello "first run"   # prints a run id
athanore ls                         # every run, and the node each is on
athanore requests                   # what is waiting for you
athanore answer 1 world             # the request id, then what you are answering
athanore show <run>                 # output: {'greeting': 'HELLO WORLD'}
```

`--json` is a global flag — it goes before the verb, like `--url` and
`--token` — and every read verb honours it, so this composes with `jq`:

<!-- from: docs/site/src/guide/cli.md -->
```sh
athanore --json ls | jq -r '.[] | select(.status == "failed") | .id'
athanore --json show "$RUN" | jq '.tasks[] | {node, status, attempt}'
athanore --json requests | jq 'length'
```

## The rules an agent gets wrong first

- **A serve target is `module:wf` or `file.py:wf`**, naming the module
  or file and the `Workflow` object in it. What is served, in order: the
  targets named, then installed workflows advertised as entry points
  unless `--no-discover`, then the pool bindings from `athanore.toml`. A
  named target wins over a discovered workflow of the same name.
- **Client verbs default to `http://127.0.0.1:4002`, and a loopback
  server needs no credential.** For anything else, `--url` and
  `--token` before the verb, `ATHANORE_TOKEN` in the environment, or
  `athanore login <url>` once, which remembers both.
- **`athanore db`, `athanore token` and `athanore login` talk to no
  server.** `db` acts on the database directly; the other two read and
  write files on disk.
- **`athanore <workflow> "title"` is `athanore submit`**, which is why a
  workflow may not be named after a verb — that is refused at
  registration.
- **`answer` reads its argument against the request's mode**: a form
  request takes JSON that parses as an object, an options request takes
  an option, a text request takes the characters typed. `permit` and
  `deny` answer a permission request. Request ids are unique across
  runs, so no run id is needed.
- **`--watch` on `ls` and `-f` on `logs` and `stream` follow the event
  stream** and resume after a dropped connection; Ctrl-C ends a follow
  successfully.
- **Binding anywhere but loopback needs an operator token**, and the
  server refuses to start without one: `athanore token rotate` writes
  it, owner-only. Behind a reverse proxy, keep the bind on loopback and
  set `require_token`.
- **`serve` runs outstanding migrations before it serves.** Set
  `run_migrations` to false to do it yourself, with `athanore db upgrade`.
  `athanore db backup <path>` is consistent while the server runs.
- **Exit codes**: 0 success; 1 the API refused, and the message is what
  it said; 2 usage — a bad flag, an unresolvable target, a pool binding
  naming a pool nothing declares; 3 the server could not be reached.

## Where to read next

Every file below is in this skill's `reference/`. The two guides are
narrative; the two after them are generated from the command tree and
the settings model, so a flag or a default there is the one that runs.

- Serving, finding a server, every verb by group, JSON out, following,
  the exit codes: `reference/guide-cli.md`.
- `athanore.toml` and precedence, binding to a network, a reverse
  proxy, Postgres, migrations, backups, retention, agents in containers,
  hygiene: `reference/guide-deployment.md`.
- Every command, its arguments and its options: `reference/cli.md`.
- Every setting, its environment variable, its `athanore.toml` key and
  its default, and the `[pools]` and `[workflows]` tables:
  `reference/settings.md`.

The workflow being served is the `athanore-workflows` skill; the API
these verbs call is the `athanore-api` skill.
