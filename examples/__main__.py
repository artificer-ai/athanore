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

The one thing it decides that a command line cannot is the pool. Every
seat of ``feature_build`` runs on one model (``feature_build.MODEL``), and
the LAN alternative to it answers a single request at a time, so the
workflow is registered on a capacity-1 pool: the model would serialize the
agents anyway, and a pool does the queueing in the scheduler instead of in
a socket timeout.

Everything else — the bind, the database, the public URL — comes from the
environment and ``athanore.toml`` (``ATHANORE_*``, 02 §Settings), because a
programmatic host that re-implemented settings parsing would be a second
place to configure a deployment.
"""

from __future__ import annotations

from athanore import Pool, Server
from feature_build import wf as feature_build


def build() -> Server:
    """The server this module serves: the registrations and nothing else.

    Separate from :func:`main` so that it can be built and inspected
    without binding a socket, which is what ``examples/tests`` does and
    what a host embedding these workflows would do.
    """

    server = Server()
    server.register(feature_build, Pool("local", capacity=1))
    return server


def main() -> None:
    """Build the server and serve until it is stopped."""

    build().serve()


if __name__ == "__main__":
    main()
