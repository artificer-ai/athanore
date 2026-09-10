"""The graph pane: this run's history projected onto its workflow's shape.

09 §Builtins are plugins: "run panel `custom` ``<ath-run-graph>`` (the
React Flow canvas of 10 §Graph pane, shipped in the SPA bundle, not as a
plugin asset)". 10 §Graph pane fixes what it draws — one card per node
and never more than one, ranked by the response's own ``generation``,
forward and join edges running down the ranks, a back edge bowing out to
the right with a ``loop`` label, and a fan-out's branches as chips inside
the node it fanned (D206).

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
