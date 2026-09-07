"""The pi adapter: everything about pi that the package must not know.

``athanore`` ships no vendor knowledge (02 §Small core, D14). What pi is,
what it is spawned as, where it writes its sessions and how it is handed
tools all live here, in an example package outside the distribution's
import graph.

- :mod:`pi.agent` is the seat a workflow subclasses: the pinned ACP
  adapter, ``tooling="native"`` and the stats provider below.
- :mod:`pi.stats` reads a pi session file as a
  :class:`~athanore.agents.stats.SessionStatsProvider`, which is where a
  run's cost and its truncation come from (D27).
- ``extensions/athanore.ts`` is the pi extension that makes the
  ``native`` tier real: the four capabilities of 05 as pi tools, calling
  the agent HTTP API with the token out of the environment (D63).
"""

from __future__ import annotations

from pi.agent import ATHANORE_EXTENSION, PI_ACP_VERSION, PiAgent
from pi.stats import PiSessionStats

__all__ = ["ATHANORE_EXTENSION", "PI_ACP_VERSION", "PiAgent", "PiSessionStats"]
