# Install

Athanore needs Python 3.11 or newer and nothing else. There is no
service to stand up, no account to create, and no API key until a
workflow of yours dispatches an agent that wants one. Runs are kept in a
SQLite file in the directory you start the server in.

## With uv

```sh
uv add athanore                # into a project that defines workflows
uv tool install athanore       # or just the command line
uv add "athanore[postgres]"    # Postgres instead of the default SQLite
```

## With pip

```sh
pip install athanore
pip install "athanore[postgres]"
```

## From a checkout

Version 1 is tagged in its own repository and has not been uploaded
anywhere yet, so the commands above still fetch the last published
release. Until it is published, install from a clone:

```sh
git clone https://github.com/artificer-ai/athanore
cd athanore
uv sync --all-packages --all-groups --all-extras
uv run athanore --help
```

That gives you the command line, the server and the browser interface
from the working tree.

## The postgres extra

`postgres` swaps the default SQLite store for PostgreSQL over `asyncpg`.
Everything else, the engine, the agents, the API and the interface, is in
the base install. Nothing in the package depends on any particular agent
vendor or on Docker. Adapters for those are ordinary Python you write or
copy, in your own project.

Which database is used, and everything else that can be configured, is in
[Settings](reference/settings.md).

## Verify the install

```sh
athanore --help
athanore serve --help
```

`athanore serve` with nothing on its command line serves whatever
workflows are installed and advertised as entry points, which on a fresh
install is none. [Quickstart](quickstart.md) writes one.
