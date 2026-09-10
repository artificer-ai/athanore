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
from workflows.feature.cron import start_ticker
from workflows.rps import wf as rps


def build() -> Server:
    """The server: `feature` on the checkout, `rps` well away from it.

    Two pools because they cap two different things. `checkout` is the
    working tree — one of it, so one run at a time. `play` is nothing at
    all: `rps` touches no file and spends most of its life parked on a
    person, and a game waiting for a throw has no business holding the
    slot the build needs.
    """

    server = Server()
    server.register(feature, Pool("checkout", capacity=1))
    server.register(rps, Pool("play", capacity=4))
    return server


def _start_scheduler(server: Server) -> None:
    """Start the crontab's minute loop, and drop the handle.

    Nothing cancels it: the task lives as long as the loop does, and the
    loop ends when the process does. Holding the handle would only be
    worth it if something here could stop the scheduler without stopping
    the server, and nothing can.
    """

    start_ticker(server)


def main() -> None:
    """Build the server, start the scheduler, and serve until stopped.

    ``on_start`` is where the crontab's minute loop begins. It has to be
    here rather than in the plugin, because 09's four declarations are a
    route, an action, a panel and an event handler — none of them a
    clock, and an ``on`` handler on a quiet server never fires at all.
    The callback runs on the server's own loop once the socket is bound,
    and starts a task rather than waiting on one.
    """

    build().serve(on_start=_start_scheduler)


if __name__ == "__main__":
    main()
