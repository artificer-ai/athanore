"""The request-body cap (08 §Sizes).

``body_limit`` (1 MiB by default, 02 §Configuration) bounds every request
body. Neither Starlette nor FastAPI ships the check, so this is it: a
pure ASGI middleware, which is what lets it run *before* anything reads
the body and lets it answer without a route.

Two cases, and only the second is interesting.

- A declared ``Content-Length`` past the limit is refused immediately,
  before a single byte of the body is read.
- A body sent without one — ``Transfer-Encoding: chunked``, which any
  streaming client produces — is counted as it arrives, and the request
  is refused the moment the running total passes the limit. A check that
  only read the header would be decorative: it is exactly the client
  that declines to declare a size that is worth bounding.

The refusal is ``413`` with the shape of 08 §Conventions and the code
:attr:`~athanore.api.errors.ErrorCode.payload_too_large`.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from athanore.api.errors import ApiError, ErrorCode

__all__ = ["BodyLimitMiddleware", "BodyTooLarge"]


class BodyTooLarge(BaseException):
    """Raised out of the wrapped ``receive`` when the body passes the cap.

    A :class:`BaseException` rather than an :class:`Exception`, and that
    is the whole point of the class. This is raised *inside* the app's
    own body-reading code, and every layer between there and here
    catches ``Exception`` on purpose: FastAPI turns anything the body
    parser raises into a 400 "There was an error parsing the body",
    Starlette's exception middleware would look for a handler, and the
    server error middleware would report a 500. All three of them are
    right to do that for a body that failed to parse, and all three
    would be wrong here — the request was refused before it was read,
    and the middleware that refused it is the one that answers.

    Deriving from :class:`BaseException` walks the exception past those
    ``except Exception`` clauses untouched, up to
    :class:`BodyLimitMiddleware`, which catches it and nothing else does.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(_message(limit))
        self.limit = limit


def _message(limit: int) -> str:
    return f"request body exceeds the {limit} byte limit"


def _declared_length(scope: Scope) -> int | None:
    """The request's ``Content-Length``, or ``None`` if it has no usable one.

    A header that is absent and one that is unparseable are the same
    answer: nothing is known about the size yet. The counting wrapper is
    the real guard in both cases, so a malformed value is not refused
    here — the body it precedes is bounded all the same.
    """

    raw = Headers(scope=scope).get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class BodyLimitMiddleware:
    """Refuse a request body larger than ``limit`` bytes with a 413."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.limit:
            await self._refuse(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise BodyTooLarge(self.limit)
            return message

        async def watched_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, watched_send)
        except BodyTooLarge:
            if started:
                # The app has already committed to a status line, so
                # there is no 413 to send. Let it out: the server ends
                # the response, which is the only honest thing left.
                raise
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        error = ApiError(413, ErrorCode.payload_too_large, _message(self.limit))
        await error.response()(scope, receive, send)
