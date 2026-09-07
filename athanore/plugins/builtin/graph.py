"""The graph pane: this run's history projected onto its workflow's shape.

09 §Builtins are plugins: "run panel `custom` ``<ath-run-graph>`` (the
rail-list renderer, shipped in the SPA bundle, not as a plugin asset)".
10 §Graph pane fixes what it draws — one row per node, forward edges as
connectors, back edges as a right-hand rail, fan-out branches as indented
sub-lists, and a join drawn back at the parent indent.

One panel. The element reads ``GET /api/runs/{id}/graph`` (08 §Graph
semantics), which is where a node's ``state``, its ``live`` flag and a
join's ``arrivals`` are computed — server-side, once, so that the SPA and
a plugin asking the same question get the same answer. A ``source`` route
here would be a second computation of it.

This pane is also what makes the ``node`` slot of 09 usable: liveness
travels on that same graph response, so the SPA shows a workflow's
``node``-slot panes for exactly the nodes this run has live, and clicking
a node here opens the log pane filtered to it.
"""

from __future__ import annotations

from athanore.workflow import Workflow

__all__ = ["ELEMENT", "declare"]

#: The custom element the SPA renders for this pane.
ELEMENT = "ath-run-graph"


def declare(wf_host: Workflow) -> None:
    """Declare the graph pane on ``wf_host``."""

    wf_host.panel("graph", slot="run", kind="custom", element=ELEMENT)
