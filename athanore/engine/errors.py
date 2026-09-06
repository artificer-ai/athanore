"""Failure classes: rule 3, refined (04 §Failure classes, D42).

Rule 3 is "the exception is the failure policy". The exception *type*
picks between the two policies the engine has, and that is metadata on
the existing rule rather than a fourth one:

- ``GraphError`` — a routing defect. It reproduces on every attempt, so
  retrying it only burns inference. Dead-letter on attempt 1.
- ``NonRetryable`` — the body has decided a retry is pointless (a
  refused agent, a hard validation failure). Dead-letter on attempt 1.
- anything else, including ``asyncio.TimeoutError`` — retryable. A
  timeout may well not reproduce.

The predicate is all this module owns; the attempt loop that consults it
is the runner's (T024a).
"""

from __future__ import annotations

from athanore.graph import GraphError


class NonRetryable(Exception):
    """Raised by a node body that knows a retry cannot help.

    The engine dead-letters the task on the attempt this is raised on,
    rather than spending the node's remaining ``retries`` on a failure
    the body has already called final. Subclass it freely: the policy
    follows the subclass.
    """


#: The exception types that dead-letter on their first attempt — the two
#: rows of 04's table. Subclasses of either inherit the policy, which is
#: how user-land narrows it (`class Refused(NonRetryable)`).
NON_RETRYABLE: tuple[type[BaseException], ...] = (GraphError, NonRetryable)


def is_retryable(exc: BaseException) -> bool:
    """Whether the engine should retry the attempt ``exc`` failed.

    ``False`` for :class:`~athanore.graph.GraphError`, for
    :class:`NonRetryable`, and for any subclass of either. ``True`` for
    everything else, ``asyncio.TimeoutError`` (which is ``TimeoutError``
    on 3.11+) included: the clock running out is exactly the failure a
    second attempt can survive.
    """
    return not isinstance(exc, NON_RETRYABLE)
