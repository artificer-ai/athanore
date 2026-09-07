"""The agent pane: the transcript of the focused attempt.

09 §Builtins are plugins: "run pane `custom` ``<ath-agent-stream>``
reading ``/api/tasks/{id}/stream`` for the focused task, with the docked
request panel". 10 §Panes fixes what it draws — one block per chunk kind,
a blinking caret while the attempt is live, and the request panel docked
underneath when the focused task has questions open.

One panel and nothing else. A ``custom`` panel is a tag and a scope: the
element is handed ``run-id``, ``task-id`` and ``node``, and it fetches
and subscribes for itself through ``window.athanore`` (09 §Escape
hatch). There is no ``source`` route here because there is nothing for
one to add — the transcript is already an endpoint of the wire contract
(``GET /api/tasks/{id}/stream``, 08 §Tasks), and a plugin route that
forwarded it would be a second way to read the same rows.

``refresh_on`` is empty for the same reason: a panel's ``refresh_on``
tells the SPA when to refetch a ``source``, and an element that
subscribes to the feed itself knows sooner than a refetch would. The
transcript is the one thing on the feed that arrives two to three times a
second (``task.stream``), and appending from ``after=seq`` is what 10
§Realtime does with it instead of refetching.

The renderer ships in the SPA's own bundle rather than as a plugin asset
— but its *placement* comes through the manifest like any other panel's,
which is the whole point of declaring it here.
"""

from __future__ import annotations

from athanore.workflow import Workflow

__all__ = ["ELEMENT", "declare"]

#: The custom element the SPA renders for this pane.
ELEMENT = "ath-agent-stream"


def declare(wf_host: Workflow) -> None:
    """Declare the agent pane on ``wf_host``."""

    wf_host.panel("agent", slot="run", kind="custom", element=ELEMENT)
