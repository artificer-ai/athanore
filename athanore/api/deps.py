"""Who may call what: the two auth dependencies (12 §Auth, 08 §Authentication).

Athanore is a local tool, so there are only two principals the API has
to tell apart and one of them usually needs no credential at all.

**The operator.** On the default loopback bind there is no operator
authentication: the SPA and the CLI call the API plainly and nobody sees
a login. Auth turns on for exactly two reasons — the bind is not
loopback, or ``require_token`` says a reverse proxy is in front of a
loopback bind (D47) — and :func:`auth_mode` is that sentence in code.
When it is on, the credential is ``Authorization: Bearer <operator
token>``, compared with :func:`hmac.compare_digest` rather than ``==``
(finding S4 of 12 §Review of the MVP), and the one exception is ``GET
/api/events``: an ``EventSource`` cannot set a header, so that route —
and no other — also accepts ``?access_token=``. The query string it
arrives in is never logged (:class:`athanore.logging.RedactingFilter`).

**An agent.** A task token is minted per attempt at claim (04 §Dispatch)
and stored as a SHA-256; :func:`task_auth` hashes what was presented,
looks the attempt up, and grants nothing unless the token belongs to
*this* task and that attempt is still ``in_progress`` or ``waiting``.
Anything else is 403, including a token from an attempt that has since
finished: a recovered or retried task gets a new token, so a captured one
dies with the attempt it was minted for. It is read from the
``X-Athanore-Token`` header and from nowhere else — never a query
parameter, never a body field (finding S3) — and no operator response
ever contains one.

Two smaller decisions are stated here rather than rediscovered:

- **A server whose auth can never succeed refuses to start.**
  :func:`check_operator_token` raises when :func:`auth_mode` says
  ``"token"`` and there is no token to compare against, so ``--host
  0.0.0.0`` without ``athanore token rotate`` is a startup failure rather
  than an API that answers 401 forever (12 §Operator token, S1).
  :func:`athanore.api.app.create_app` calls it, which is what makes the
  refusal a property of the application rather than of one host.
- **The operator token is read per request.** ``effective_operator_token``
  re-reads ``.athanore/token`` each time, so ``athanore token rotate``
  takes effect on the next request instead of at the next restart. Auth
  is only on for a network bind, and a local file read is cheaper than a
  stale credential.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import Header, Path, Request

from athanore.api.errors import ApiError, ErrorCode
from athanore.settings import AthanoreSettings
from athanore.store.repos.tasks import token_hash
from athanore.store.rows import TaskRow, TaskStatus

__all__ = [
    "EVENTS_PATH",
    "LIVE_STATUSES",
    "AuthMode",
    "MissingOperatorToken",
    "auth_mode",
    "authenticated",
    "check_operator_token",
    "operator_auth",
    "task_auth",
]

#: Whether operator endpoints need a credential. ``/api/me`` reports it so
#: the SPA knows whether to offer a token screen (08 §System).
AuthMode = Literal["off", "token"]

#: The one route that also accepts the operator token as a query
#: parameter, because a browser's ``EventSource`` cannot set a header
#: (08 §Authentication). Matched against the request path exactly: the
#: exception is for this route, not for a prefix of it.
EVENTS_PATH = "/api/events"

#: The attempt statuses a task token is live for (12 §Task tokens).
LIVE_STATUSES = frozenset({TaskStatus.in_progress, TaskStatus.waiting})

#: What every operator 401 says. One wording for a missing header, a
#: malformed one and a wrong token alike: which of the three it was is
#: not information the door should hand out.
_UNAUTHORIZED = "operator token required"

#: What every task-token 403 says, for the same reason — an agent
#: learning *why* it was refused learns whether a task id exists.
_FORBIDDEN = "task token is not valid for this task"


class MissingOperatorToken(RuntimeError):
    """Auth is required and no operator token is configured.

    Raised by :func:`check_operator_token` at construction time, so the
    process fails where the operator can read it (``athanore serve
    --host 0.0.0.0`` without a token) rather than serving an API that
    can only ever answer 401.
    """


def auth_mode(settings: AthanoreSettings) -> AuthMode:
    """Whether operator endpoints require a token, for ``settings``.

    ``"token"`` when the bind is not loopback, or when ``require_token``
    forces it on a loopback bind for the reverse-proxy case (D47).
    "Loopback" is decided by the *configured* host and never by a
    request's peer address (08 §Authentication): a proxy makes every
    caller look local, which is exactly the case ``require_token``
    exists for.
    """

    return "token" if not settings.is_loopback or settings.require_token else "off"


def check_operator_token(settings: AthanoreSettings) -> None:
    """Refuse a configuration whose operator auth could never succeed.

    A no-op when :func:`auth_mode` is ``"off"``, and a
    :class:`MissingOperatorToken` when it is ``"token"`` with no token
    configured (12 §Operator token).
    """

    if auth_mode(settings) == "off":
        return
    if settings.effective_operator_token is not None:
        return
    why = (
        f"the bind host {settings.host!r} is not loopback"
        if not settings.is_loopback
        else "`require_token` is set"
    )
    raise MissingOperatorToken(
        f"operator authentication is required ({why}) but no operator token "
        f"is configured: run `athanore token rotate` to write "
        f"{settings.token_file}, or set ATHANORE_OPERATOR_TOKEN."
    )


def _bearer(request: Request) -> str | None:
    """The token of an ``Authorization: Bearer`` header, or ``None``.

    A header with another scheme, or with an empty credential, is not a
    bearer token and reads as absent; the caller answers 401 either way.
    """

    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return credential.strip() or None


def _presented(request: Request) -> str | None:
    """The operator token ``request`` carries, from wherever it may carry it.

    The header first, always. The ``access_token`` query parameter is
    consulted only for ``GET /api/events`` and only when the header did
    not supply one, so no other route can be reached with a credential in
    a URL.
    """

    token = _bearer(request)
    if token is not None:
        return token
    if request.method == "GET" and request.url.path == EVENTS_PATH:
        return request.query_params.get("access_token") or None
    return None


def authenticated(request: Request) -> bool:
    """Whether ``request`` carries operator rights.

    ``True`` for every request when auth is off — there is nothing to
    prove and the caller has full control (12 §Posture). ``/api/me``
    reports this without requiring it, which is how the SPA decides
    whether to show its token screen.

    The comparison is over UTF-8 bytes so that a non-ASCII credential is
    a mismatch rather than the :class:`TypeError` that
    :func:`hmac.compare_digest` raises for a non-ASCII :class:`str`.
    """

    settings: AthanoreSettings = request.app.state.settings
    if auth_mode(settings) == "off":
        return True
    expected = settings.effective_operator_token
    if expected is None:
        return False
    presented = _presented(request)
    if presented is None:
        return False
    return hmac.compare_digest(
        presented.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    )


async def operator_auth(request: Request) -> None:
    """Require operator rights, or 401 ``unauthorized``.

    The dependency every operator route, plugin route and the SSE stream
    depends on (08 §Authentication). It returns nothing: v1 has one
    operator and no principal object to hand back. Multi-user auth is the
    seam that replaces this function, and nothing else (12 §Operator
    token).
    """

    if not authenticated(request):
        raise ApiError(401, ErrorCode.unauthorized, _UNAUTHORIZED)


async def task_auth(
    request: Request,
    task_id: Annotated[int, Path(description="The task the token was minted for.")],
    x_athanore_token: Annotated[
        str, Header(description="The task token, from the claimed attempt.")
    ],
) -> TaskRow:
    """The attempt ``x_athanore_token`` is the live token of, or 403.

    Three conditions, and all three are the same refusal: the hash is
    known, the attempt it names is *this* ``task_id``, and that attempt
    is still ``in_progress`` or ``waiting`` (12 §Task tokens). A token
    from a finished, failed, recovered or cancelled attempt is dead, so
    an agent that keeps working after its task ended can no longer write
    to it.

    The header is required, so a request without one is FastAPI's 422
    with the shape of 08 §Conventions rather than a 403: nothing was
    presented to refuse, and the body names the header that is missing.
    """

    store = request.app.state.store
    if store is None:
        # No store, no attempts, no valid token — the honest answer is
        # the same refusal rather than a 500 about the server's wiring.
        raise ApiError(403, ErrorCode.forbidden, _FORBIDDEN)
    async with store.reader() as reader:
        row = await reader.tasks.by_token_hash(token_hash(x_athanore_token))
    if row is None or row.id != task_id or row.status not in LIVE_STATUSES:
        raise ApiError(403, ErrorCode.forbidden, _FORBIDDEN)
    return row
