"""The requests panes: the human-in-the-loop history, and the inbox.

09 §Builtins are plugins: "run pane `custom` ``<ath-requests>`` (the
mock's messages pane), plus a global pane when no run is selected". Two
panels, one element.

The run pane is the mock's `messages` pane re-purposed (D33): Athanore
has no node-to-node messages, because the work log is the inter-node
channel, so what that pane shows is every question this run has asked a
person and every answer it got — permissions, elicitations and the
``human_input`` of 06.

The **global** pane is the same element with no run in scope: the inbox,
shown when nothing is selected, so an operator who opens the app to a
list of runs can still see what is waiting on them. It is the one builtin
that is not about the selected run, and it is why 09's
``services.run.list()`` works in a ``global`` scope at all.

Both are ``custom``, and neither declares a ``source``: requests are
already on the wire (``GET /api/runs/{id}/requests`` and the request
endpoints of 08 §Requests), and the element answers them through
``window.athanore``. Two panels rather than one because a panel is
declared with one slot, and a pane shown beside a run and a pane shown
instead of one are two placements of the same renderer.
"""

from __future__ import annotations

from athanore.workflow import Workflow

__all__ = ["ELEMENT", "declare"]

#: The custom element both panes render.
ELEMENT = "ath-requests"


def declare(wf_host: Workflow) -> None:
    """Declare the run pane and the global inbox on ``wf_host``."""

    wf_host.panel("requests", slot="run", kind="custom", element=ELEMENT)
    wf_host.panel("inbox", slot="global", kind="custom", element=ELEMENT)
