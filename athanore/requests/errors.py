"""What the request channel refuses (06 §Service, 08 §Conventions).

Five refusals, one per way an answer can fail to land. They are
exceptions rather than return values because every one of them is an
answer to whoever sent the answer — an operator at a form, an agent
mid-turn, a node body replaying after a crash — and none of them is a
state the caller can usefully continue from.

They are also the far end of the wire contract: T042 maps each onto the
code of 08 §Conventions, and nothing else in the API produces the
request-channel codes.

- :class:`InvalidOption` — 400 ``invalid_option``
- :class:`InvalidAnswer` — 422 ``validation``
- :class:`AlreadyAnswered` — 409 ``already_answered``
- :class:`StaleRequest` — 409 ``stale_request``
- :class:`RequestNotFound` — 404 ``not_found``

None of them is a subclass of :class:`~athanore.engine.errors.NonRetryable`
(nor could be — ``requests`` is a sibling of ``engine``, not a layer
below it): a refused answer reaching a node body is an ordinary
exception, and rule 3 decides what the engine does with it.
"""

from __future__ import annotations

from typing import Any


class RequestError(Exception):
    """Base of the five refusals of the request channel.

    Catching this is how a caller says "the request channel refused"
    without enumerating the reasons — the v0 role of ``AnswerError``,
    renamed because :class:`RequestNotFound` is not about an answer.
    """


class RequestNotFound(RequestError):
    """No request with that id exists.

    404 ``not_found``. Answering, waiting on, or reading a request that
    is not there has no honest no-op: the id came from somewhere, and
    telling the caller it resolves to nothing is the only useful reply.
    """


class InvalidOption(RequestError):
    """The ``option_id`` is not one the request offered.

    400 ``invalid_option``, not 422: an ``options`` request carries its
    own list of acceptable answers, so a miss is a malformed request
    against a known vocabulary rather than a value that failed
    validation. Options are chosen by id, never by index (D10).
    """


class InvalidAnswer(RequestError):
    """The answer does not fit the request's mode or schema.

    422 ``validation``. ``errors`` is the machine-readable list the SPA
    renders next to the offending fields — ``[{loc, msg, type}]`` in
    pydantic's shape, whichever validator produced it (see
    :mod:`athanore.requests.validators`) — and is always a list, empty
    when the failure has no per-field detail (a ``text`` answer that is
    not a non-empty string, say).
    """

    def __init__(
        self,
        message: str = "answer failed validation",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors: list[dict[str, Any]] = list(errors or [])


class AlreadyAnswered(RequestError):
    """An answer already exists for that request.

    409 ``already_answered``. One answer per request, claimed exactly
    once by the waiter that opened it (06 §The model), so a second
    answer is refused whether or not the first has been consumed —
    overwriting it would change an answer a body may already have acted
    on.
    """


class StaleRequest(RequestError):
    """The request's task is no longer running, so nobody will read it.

    409 ``stale_request``. A request goes stale when its task ends: the
    row survives in the run's history, but it leaves the operator's
    inbox and stops accepting answers, because the waiter that would
    have consumed one is gone (06 §Restart durability).
    """


__all__ = [
    "AlreadyAnswered",
    "InvalidAnswer",
    "InvalidOption",
    "RequestError",
    "RequestNotFound",
    "StaleRequest",
]
