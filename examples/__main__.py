"""A host for the example adapters, so they can be run and looked at.

`examples/` is the vendor half of 02 §Small core: nothing in `athanore/`
may know about pi, Claude or Docker, so the adapters that do live here.
They are ACP agent classes rather than workflows with much shape — the
worked examples of `05 §User-land adapters`, and the integration test bed
`examples/tests` drives.

Run it from the checkout::

    uv run python -m examples

The pools are the point of the arrangement, and the reason this is a
programmatic host rather than `athanore serve` (04 §Programmatic host):

- ``docker_acp`` runs on ``local``, capacity 1. It spawns a sibling
  container per agent, and two of those competing for one machine's
  memory is a throughput choice that goes the wrong way.
- ``claude_acp`` runs on ``cloud``, capacity 8. Its work is a request to
  somebody else's machine, so the cap is about how many of those to have
  in flight, not about this one.
"""

from __future__ import annotations

from athanore import Pool, Server
from claude_acp import wf as claude_acp
from docker_acp import wf as docker_acp


def build() -> Server:
    """The server, with each adapter on the pool its work belongs to."""

    local = Pool("local", capacity=1)
    cloud = Pool("cloud", capacity=8)

    server = Server()
    server.register(docker_acp, local)
    server.register(claude_acp, cloud)
    return server


def main() -> None:
    """Build the server and serve until it is stopped."""

    build().serve()


if __name__ == "__main__":
    main()
