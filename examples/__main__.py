"""Serve the example workflows: ``python -m examples``, from the checkout.

This is the **programmatic form** of 11 §Server: a :class:`athanore.Server`
built in Python, handed the workflows and the pools they run on, and told
to serve. It replaces the MVP's ``python -m workflow``.

``athanore serve`` is the other way to run exactly these workflows, and it
needs no arguments — ``athanore-examples`` advertises them in the
``athanore.workflows`` entry-point group, so discovery finds them and
``athanore.toml``'s ``[pools]`` / ``[workflows]`` tables place them (09
§Discovery). What this file is for is the case that has no command line:
a host that builds a server out of its own configuration, in its own
process, beside its own code.

The one thing it decides that a command line cannot is the pool, and the
registrations below are 04 §Programmatic host's own four lines:

- ``feature_build`` and ``gamedev`` share the capacity-1 ``local`` pool.
  Every seat of both runs on one model (``MODEL`` in each package), and
  the LAN alternative to it answers a single request at a time: the model
  would serialize the agents anyway, and a pool does that queueing in the
  scheduler instead of in a socket timeout. Sharing the pool is what makes
  it one queue rather than two that each think they are alone.
- ``projects`` runs on ``cloud``, capacity 8. Its seats are Claude Code
  over ACP — a hosted service that answers several requests at once — and
  its product stage fans out one branch per deliverable, so the branches
  are the thing worth running in parallel. Eight is the capacity 02
  §Settings gives that pool in its worked ``athanore.toml``.
- ``msgtest`` is registered on no pool at all, which puts it on the
  default one. It runs no agents; what it waits for is a person, and a
  ``human_input`` gives its worker slot back for the duration of the wait
  (04 §Waiting) — so it needs no capacity of its own and cannot starve
  anything of theirs.

Everything else — the bind, the database, the public URL — comes from the
environment and ``athanore.toml`` (``ATHANORE_*``, 02 §Settings), because a
programmatic host that re-implemented settings parsing would be a second
place to configure a deployment.
"""

from __future__ import annotations

from athanore import Pool, Server
from feature_build import wf as feature_build
from gamedev import wf as gamedev
from msgtest import wf as msgtest
from projects import wf as projects


def build() -> Server:
    """The server this module serves: the registrations and nothing else.

    Separate from :func:`main` so that it can be built and inspected
    without binding a socket, which is what ``examples/tests`` does and
    what a host embedding these workflows would do.
    """

    local = Pool("local", capacity=1)
    server = Server()
    server.register(feature_build, local)
    server.register(gamedev, local)
    server.register(projects, Pool("cloud", capacity=8))
    server.register(msgtest)
    return server


def main() -> None:
    """Build the server and serve until it is stopped."""

    build().serve()


if __name__ == "__main__":
    main()
