"""``/api/requests``: the inbox, one request, and the answer (08 §Requests).

The attention surface. A request is the one object in Athanore that
blocks on a person (06), and this router is where a person unblocks it:
the inbox lists what is still waiting, and ``/answer`` records the one
answer a request may have.

The two reads come from the store and the write goes through the request
service, and that is not an inconsistency. Reading a request is a join —
the row, its answer, and the status of the task that asked — which
:meth:`~athanore.store.repos.requests.RequestRepo.list_views` already
does in SQL, and ``GET /api/runs/{id}/requests`` reads it the same way.
Answering one is a decision: the mode's validation, the validator a
waiter registered, the ``request.answered`` event that wakes it, and the
transaction all belong to
:class:`~athanore.requests.service.RequestService` (06 §Service). The
router asks it and never re-implements a word of it.

The refusals are 06 §Errors, in the service's own order, and every one of
them is already in :data:`athanore.api.errors.DOMAIN_ERRORS`:

- an id that names no request → 404 ``not_found``;
- a second answer → 409 ``already_answered``;
- a request whose task has ended → 409 ``stale_request``;
- an ``option_id`` the request did not offer → 400 ``invalid_option``;
- a ``text`` answer that is not a non-empty string, or a ``form`` answer
  that is not an object or that the registered validator refused → 422
  ``validation``, with the per-field ``errors`` beside it.

``?pending`` defaults to **true**, because this route is the inbox: 08
names it one, both of its consumers — the SPA's global requests pane and
``athanore requests`` — want exactly the requests a person can still act
on, and a run's whole history already has a route of its own
(``GET /api/runs/{id}/requests``). ``?pending=false`` widens it to every
request, answered and stale included, and ``?run=`` scopes either to one
run.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as PathParam

from athanore.api.deps import operator_auth
from athanore.api.schemas import Answer, RequestView
from athanore.engine import Engine
from athanore.engine.services import RequestBackend
from athanore.requests.errors import RequestNotFound
from athanore.store import rows
from athanore.store.uow import Store

__all__ = ["router"]

router = APIRouter(
    prefix="/api/requests",
    tags=["requests"],
    dependencies=[Depends(operator_auth)],
)

#: The path parameter the two single-request routes take.
RequestId = Annotated[int, PathParam(description="The request id, unique across runs.")]


# --------------------------------------------------------------------------
# The collaborators, and what their absence means
# --------------------------------------------------------------------------


def _store(request: Request) -> Store | None:
    """The store this application reads requests from, if it has one."""

    store: Store | None = request.app.state.store
    return store


def _service(request: Request, request_id: int) -> RequestBackend:
    """The request service, or the 404 a request has without one.

    A server composed without one has a request port whose every method
    raises (04 §TaskContext), so no attempt on it ever opened a request
    and there is nothing here to answer. Saying "no such request" is the
    same answer the store would have given, rather than a 500 about the
    server's own wiring.
    """

    engine: Engine | None = request.app.state.engine
    service = engine.requests if engine is not None else None
    if service is None:
        raise RequestNotFound(
            f"no request {request_id}: this server has no request service"
        )
    return service


async def _view(request: Request, request_id: int) -> rows.RequestView:
    """The joined request, or 404 ``not_found``."""

    store = _store(request)
    view = None
    if store is not None:
        async with store.reader() as reader:
            view = await reader.requests.view(request_id)
    if view is None:
        raise RequestNotFound(f"no request {request_id}")
    return view


# --------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------


@router.get("", summary="The inbox: every request still waiting on a person")
async def list_requests(
    request: Request,
    pending: Annotated[
        bool,
        Query(
            description="Only requests a person can still act on: unanswered, "
            "with the attempt that asked still running."
        ),
    ] = True,
    run: Annotated[str | None, Query(description="Only requests of this run.")] = None,
) -> list[RequestView]:
    """The requests of every run, or of one, oldest first.

    "Pending" is narrower than "unanswered": a request whose task has
    ended is **stale** and leaves the inbox, because an answer to it
    would reach nobody (06 §Restart durability). It stays in the run's
    own history, and ``pending=false`` here shows it too, with
    ``stale: true`` on it.

    An application with no store holds no requests and answers with an
    empty list; a ``run`` that names no run is a filter that matches
    nothing rather than a 404.
    """

    store = _store(request)
    if store is None:
        return []
    async with store.reader() as reader:
        views = await reader.requests.list_views(run, pending_only=pending)
    return [RequestView.of(view) for view in views]


@router.get("/{request_id}", summary="One request and its answer")
async def get_request(request: Request, request_id: RequestId) -> RequestView:
    """One request, answered or not, with the node that asked."""

    return RequestView.of(await _view(request, request_id))


@router.post("/{request_id}/answer", summary="Answer a request")
async def answer_request(
    request: Request, request_id: RequestId, body: Answer
) -> RequestView:
    """Record the one answer this request may have, and return it.

    ``option_id`` for an ``options`` request and ``value`` for a ``text``
    or ``form`` one; the request's own ``mode`` decides which of the two
    is read, so a ``value`` sent to an ``options`` request is not an
    answer that request could have (06 §Service).

    The response is the **updated** view rather than the answer row (08
    §Requests): the SPA re-renders the card it just answered, and
    ``pending``, ``answer`` and ``answered_by`` are all part of what
    changed. The author is ``user`` — this route is the operator's, and
    the other author, ``engine``, belongs to the headless fallbacks that
    record an answer without a person (06 §Timeouts).
    """

    service = _service(request, request_id)
    await service.answer(request_id, option_id=body.option_id, value=body.value)
    return RequestView.of(await _view(request, request_id))
