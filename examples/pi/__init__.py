"""The pi adapter: everything about pi that the package must not know.

``athanore`` ships no vendor knowledge (02 §Small core, D14). What pi is,
what it is spawned as, where it writes its sessions and how it is handed
tools all live here, in an example package outside the distribution's
import graph.

- :mod:`pi.stats` reads a pi session file as a
  :class:`~athanore.agents.stats.SessionStatsProvider`, which is where a
  run's cost and its truncation come from (D27).
"""

from __future__ import annotations

from pi.stats import PiSessionStats

__all__ = ["PiSessionStats"]
