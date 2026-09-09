"""The host for the workflows that maintain this checkout.

A programmatic host rather than `athanore serve` (04 §Programmatic host),
for the one reason a command line cannot cover: the pool. `feature`
mutates the working tree — it branches, it merges, it runs the gate — so
two runs of it in the same checkout at the same time would be two agents
editing one branch. Capacity 1 is not a throughput choice here, it is the
correctness of the thing.

Everything else — the bind, the database, the public URL — comes from the
environment and `athanore.toml` (`ATHANORE_*`, 02 §Settings).

Run it from the checkout, in this repository's own environment::

    uv run python -m workflows

There is no container around this: athanore v1 maintaining athanore v1 is
one distribution, so there is no second environment to keep it out of
(D67 was about v0). The agents it dispatches *are* containerised, through
`scripts/agent.sh` — see :mod:`workflows.feature.agents`.
"""

from __future__ import annotations

from athanore import Pool, Server
from workflows.feature import wf as feature


def build() -> Server:
    """The server, with `feature` on a capacity-1 pool."""

    server = Server()
    server.register(feature, Pool("checkout", capacity=1))
    return server


def main() -> None:
    """Build the server and serve until it is stopped."""

    build().serve()


if __name__ == "__main__":
    main()
