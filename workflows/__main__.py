"""The host for the workflows that maintain this checkout.

A programmatic host rather than `athanore serve` (04 §Programmatic host),
for the one reason a command line cannot cover: the pool. Both seats
mutate the working tree — `feature` branches, merges and runs the gate;
`planner` branches, writes documents and merges — so two runs at the same
time in the same checkout would be two agents editing one tree. Capacity
1 is not a throughput choice here, it is the correctness of the thing,
and it is **one** pool for both because there is one working tree.

`planner` also queues `feature` runs, over the API this host serves, so
the two are on the same server for a second reason: a plan's tasks are
submitted to the thing that will build them.

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
from workflows.planner import wf as planner


def build() -> Server:
    """The server, with both seats on one capacity-1 pool."""

    checkout = Pool("checkout", capacity=1)
    server = Server()
    server.register(planner, checkout)
    server.register(feature, checkout)
    return server


def main() -> None:
    """Build the server and serve until it is stopped."""

    build().serve()


if __name__ == "__main__":
    main()
