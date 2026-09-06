"""Failure classes, and what an operator operation refuses (04, D42).

Two unrelated families live here, and the difference between them is the
whole of why they can share a module. The first is rule 3 — "the
exception is the failure policy" — which decides what the engine does
with an attempt that raised. The second is the refusals of
``engine.ops`` (04 §Operator operations): a precondition that does not
hold is not a failure of a node body at all, it is an answer to an
operator, and T042 maps each of these onto its status code.

Rule 3 first. The exception *type* picks between the two policies the
engine has, and that is metadata on the existing rule rather than a
fourth one:

- ``GraphError`` — a routing defect. It reproduces on every attempt, so
  retrying it only burns inference. Dead-letter on attempt 1.
- ``NonRetryable`` — the body has decided a retry is pointless (a
  refused agent, a hard validation failure). Dead-letter on attempt 1.
- anything else, including ``asyncio.TimeoutError`` — retryable. A
  timeout may well not reproduce.

The predicate is all this module owns; the attempt loop that consults it
is the runner's (T024a).

The operator refusals are :class:`NotFound`, :class:`UnknownWorkflow`,
:class:`UnknownNode` and :class:`Conflict`. They never reach the retry
policy above — nothing raises them inside a node body — and none of them
is a subclass of :class:`NonRetryable`, so an op that refuses an
operator cannot be mistaken for an attempt that gave up.
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


# --------------------------------------------------------------------------
# What an operator operation refuses (04 §Operator operations)
# --------------------------------------------------------------------------


class EngineError(Exception):
    """Base of the refusals ``engine.ops`` raises.

    An operation states its preconditions by raising one of these, and
    T042 maps the four onto the codes of 08 §Conventions. Catching this
    class is how a caller says "the engine refused the operation" without
    enumerating the reasons.
    """


class NotFound(EngineError):
    """The run, task or request the operation named does not exist.

    404 ``not_found``. It is deliberately not an empty result: an
    operation is an instruction about a specific row, and an instruction
    about a row that is not there has no honest no-op.
    """


class UnknownWorkflow(NotFound):
    """No workflow of that name is registered on this server.

    404 ``unknown_workflow``. A :class:`NotFound` because that is what it
    is — the name resolves to nothing — with its own type so the API can
    say *which* name it could not resolve (T042).
    """


class UnknownNode(NotFound):
    """The workflow has no node of that name.

    404 ``unknown_node``. Raised by the operations that take a node
    — ``rerun`` and ``move`` — before anything is written.
    """


class Conflict(EngineError):
    """The operation is refused by the state the row is in.

    409 ``conflict``: pausing a completed run, resuming one that is not
    paused, retrying a task that is still going, moving one into a join
    node. The message names the state that refused, because "409" on its
    own tells an operator nothing about what to do next.
    """


__all__ = [
    "NON_RETRYABLE",
    "Conflict",
    "EngineError",
    "NonRetryable",
    "NotFound",
    "UnknownNode",
    "UnknownWorkflow",
    "is_retryable",
]
