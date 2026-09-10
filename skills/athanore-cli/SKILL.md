---
name: athanore-cli
description: Serve and steer Athanore from a terminal — `athanore serve` and its module:wf targets, the client verbs and how they find a server, --json output, pools and athanore.toml, and the exit codes. Load this before writing a command line, a script or a crontab entry against Athanore, or when a verb is refusing and you need to know what its exit status means.
---

# Using the Athanore CLI

Every path in this file is relative to the **checkout root**: the
directory two levels above this file in the checkout this skill was
installed from. Nothing here is normative — `docs/v1/11-cli.md` is the
specification and this only says which part of it to open.

## The surface

`athanore` is a small program with one server verb and a set of client
verbs. Three ideas are the whole of it:

1. **`athanore serve` is the composition root's command line.** It takes
   `module:wf` targets, builds the server, registers what it was given,
   and serves: `docs/v1/11-cli.md` §Server. It is the only verb that is
   not a client.
2. **Every other verb is a client of the HTTP API**, and they all find
   their server and their token the same way, through the same global
   flags: `docs/v1/11-cli.md` §Client connection.
3. **Output is a table on a TTY and JSON with `--json` everywhere**, so
   the CLI composes with `jq` rather than growing a query language of
   its own. That is the opening paragraph of `docs/v1/11-cli.md`; the
   verbs it applies to are `docs/v1/11-cli.md` §Verbs.

## Where to read

| If you are asking | Open |
|---|---|
| how do I serve one workflow, or several? | `docs/v1/11-cli.md` §Server |
| how does a verb decide which server to talk to? | `docs/v1/11-cli.md` §Client connection |
| which verbs are there, and which take `--json`? | `docs/v1/11-cli.md` §Verbs |
| where are the database and the config file looked for? | `docs/v1/02-architecture.md` §Configuration |
| what may the config file set, and what is refused in it? | `docs/v1/02-architecture.md` §`athanore.toml` layout |
| how do I declare a pool and put a workflow on it? | `docs/v1/04-engine.md` §Pools |
| how do I answer a question from a terminal? | `docs/v1/06-requests.md` §CLI (11) |
| what does the answer argument mean for this request's mode? | `docs/v1/06-requests.md` §The model |
| what does this exit status mean? | `docs/v1/11-cli.md` §Exit codes |
| do I need a token for this, and where does it live on disk? | `docs/v1/12-security.md` §Operator token (network binds only) |
| what must a script never print or log? | `docs/v1/12-security.md` §Hygiene |
| why is there no verb for the thing I want? | `docs/v1/11-cli.md` §Not in v1 |

An exit status is part of the contract, not a detail: a script that
branches on it is what the codes are for, and all four of them are
fixed in `docs/v1/11-cli.md` §Exit codes.

## What to copy

- `README.md` §The CLI. Serving and driving, in about a dozen lines.
- `workflows/__main__.py` — a real `serve` target: this repository's own
  workflows, registered on their own pools.
- `athanore/cli/` — the implementation, if a verb's behaviour is not
  written down anywhere else. `athanore/cli/client.py` is where the
  connection and the token are actually resolved.

The dev stack's wrappers around all of this — running the app, the gate
and an agent, on the host or in the container — are `AGENTS.md`
§Commands and the scripts under `scripts/`.

## Generated reference

The command tree, walked out of the code by `scripts/gen_skills.py`, so
it cannot drift from it:

- `skills/athanore-cli/reference/commands.md` — every command, its
  arguments and its options.

The endpoints these verbs call are
`skills/athanore-api/reference/routes.md`, and the error codes they
report are `skills/athanore-api/reference/error-codes.md`.
