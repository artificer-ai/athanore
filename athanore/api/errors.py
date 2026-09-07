"""The one error shape, and the exceptions that render as it (08 §Conventions).

Every failure the API reports is the same object on the wire::

    {"error": "<human message>", "code": "<stable snake_case>", ...extras}

:class:`ErrorCode` is the vocabulary of that ``code`` field — the whole
list of 08 §Conventions, one member per row — and it is a
:class:`~enum.StrEnum` for the same reason
:class:`~athanore.events.names.EventName` is: the code is spelled once,
referenced everywhere, and T048 publishes the enum in OpenAPI so the SPA
gets a TypeScript union rather than a bare ``string``.

:class:`ApiError` is what a router raises when it wants to say something
specific. Everything else that reaches a handler is a *domain* exception
— a refusal from :mod:`athanore.engine.errors` or
:mod:`athanore.requests.errors`, or a
:class:`~athanore.graph.GraphError` — and :data:`DOMAIN_ERRORS` is the
one table that maps those onto a status and a code. The layers below the
API therefore never import it and never learn what an HTTP status is:
they raise the exception that names what they refused, and this module
translates.

The translation is looked up along the raised exception's MRO, so a
subclass inherits its base's mapping unless it has a row of its own.
That is what lets :class:`~athanore.engine.errors.UnknownWorkflow` be a
:class:`~athanore.engine.errors.NotFound` — 404 either way — and still
answer with its own code.

:class:`~athanore.plugins.decl.PluginError` is the one row whose status
comes from the exception rather than from the table: a plugin handler
raises the status it means (09 §Wire contract), and the same refusal is
what a plugin context raises when a handler reaches for a service its
scope does not have.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from athanore.engine.errors import Conflict, NotFound, UnknownNode, UnknownWorkflow
from athanore.graph import GraphError
from athanore.plugins.decl import PluginError
from athanore.requests.errors import (
    AlreadyAnswered,
    InvalidAnswer,
    InvalidOption,
    RequestNotFound,
    StaleRequest,
)

__all__ = [
    "DOMAIN_ERRORS",
    "RESERVED",
    "ApiError",
    "ErrorCode",
    "ErrorResponse",
    "api_error_for",
    "install_error_handlers",
]


class ErrorCode(StrEnum):
    """The stable ``code`` of an error body — 08 §Conventions, in full.

    A code is a contract with the SPA and the CLI: it is what a client
    branches on, so it outlives any wording change to ``error``. Adding
    one is a change to 08 and to the TypeScript mirror, never to this
    module alone.
    """

    not_found = "not_found"
    conflict = "conflict"
    forbidden = "forbidden"
    unauthorized = "unauthorized"
    validation = "validation"
    invalid_option = "invalid_option"
    already_answered = "already_answered"
    stale_request = "stale_request"
    graph_error = "graph_error"
    unknown_workflow = "unknown_workflow"
    unknown_node = "unknown_node"
    payload_too_large = "payload_too_large"
    plugin_error = "plugin_error"


#: The two keys the error shape owns. An extra may not take one of them:
#: a caller that passed ``error=`` would silently replace the message,
#: and the body would still look well-formed to the client reading it.
RESERVED = frozenset({"error", "code"})


class ErrorResponse(JSONResponse):
    """A JSON response that serialises non-native values with ``str``.

    08 §Conventions fixes ``default=str`` for the API's JSON, and an
    error body is where it matters most: the extras of a 422 carry
    whatever a validator produced, and a handler that raised while
    rendering would turn a considered refusal into a bare 500.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")


class ApiError(Exception):
    """A refusal with an HTTP status, a code, a message, and extras.

    ``extras`` are the fields a particular refusal adds to the shape —
    ``errors`` on a validation failure, ``errors`` and ``schema`` on a
    rejected submission (08 §Agent-facing). They are merged into the
    body as they are given, which is why :data:`RESERVED` is refused:
    the two keys every client reads are not negotiable. The first three
    parameters are positional-only so that an extra may be *named*
    ``code`` or ``message`` and be refused, rather than collide with the
    signature and read as a caller's typo.
    """

    def __init__(
        self,
        status: int,
        code: ErrorCode | str,
        message: str,
        /,
        **extras: Any,
    ) -> None:
        super().__init__(message)
        clash = sorted(RESERVED & extras.keys())
        if clash:
            raise ValueError(
                f"extras may not shadow the error shape's own keys: {clash}"
            )
        self.status = status
        #: Coerced, so an unknown code is a failure here rather than a
        #: string the SPA has no branch for.
        self.code = ErrorCode(code)
        self.message = message
        self.extras: dict[str, Any] = dict(extras)

    @property
    def body(self) -> dict[str, Any]:
        """The wire body: ``{"error", "code", **extras}``."""

        return {"error": self.message, "code": self.code.value, **self.extras}

    def response(self) -> ErrorResponse:
        """The response an ASGI caller can send directly."""

        return ErrorResponse(status_code=self.status, content=self.body)


#: How a domain exception is reported: exception class → (status, code,
#: the message used when the exception carries none). The order is
#: documentation only — the lookup walks the raised exception's MRO, so
#: a subclass row wins over its base's wherever both are present.
DOMAIN_ERRORS: dict[type[Exception], tuple[int, ErrorCode, str]] = {
    UnknownWorkflow: (404, ErrorCode.unknown_workflow, "unknown workflow"),
    UnknownNode: (404, ErrorCode.unknown_node, "unknown node"),
    NotFound: (404, ErrorCode.not_found, "not found"),
    Conflict: (409, ErrorCode.conflict, "conflict"),
    GraphError: (409, ErrorCode.graph_error, "invalid graph"),
    RequestNotFound: (404, ErrorCode.not_found, "not found"),
    InvalidOption: (400, ErrorCode.invalid_option, "not one of the options offered"),
    InvalidAnswer: (422, ErrorCode.validation, "answer failed validation"),
    AlreadyAnswered: (409, ErrorCode.already_answered, "already answered"),
    StaleRequest: (409, ErrorCode.stale_request, "request is no longer live"),
    # The one row whose status is not the row's: a plugin handler names
    # its own (09 §Wire contract), and 400 is what it gets when it did
    # not — the context's own refusals, which are all client errors.
    PluginError: (400, ErrorCode.plugin_error, "the plugin refused"),
}


def api_error_for(exc: Exception) -> ApiError | None:
    """The :class:`ApiError` ``exc`` reports as, or ``None`` if unmapped.

    ``None`` means the exception is not one this module claims to
    translate — the caller re-raises it and the server reports a 500,
    which is the honest answer for a defect the API has no vocabulary
    for.
    """

    for cls in type(exc).__mro__:
        row = DOMAIN_ERRORS.get(cls)
        if row is None:
            continue
        status, code, default = row
        extras: dict[str, Any] = {}
        if isinstance(exc, PluginError):
            # A plugin says what status it means. Everything else in the
            # table is refused by a layer that does not know what an HTTP
            # status is, which is why this is the one exception to the
            # rule that the row decides.
            status = exc.status
        if isinstance(exc, InvalidAnswer):
            # The per-field detail the SPA renders next to the offending
            # inputs (06 §Service); always a list, empty when the
            # failure has none.
            extras["errors"] = exc.errors
        return ApiError(status, code, str(exc) or default, **extras)
    return None


async def api_error_handler(request: Request, exc: Exception) -> Response:
    """Render an :class:`ApiError` as itself."""

    if not isinstance(exc, ApiError):
        raise exc
    return exc.response()


async def domain_error_handler(request: Request, exc: Exception) -> Response:
    """Render a mapped engine/requests/graph exception (:data:`DOMAIN_ERRORS`)."""

    mapped = api_error_for(exc)
    if mapped is None:
        raise exc
    return mapped.response()


async def validation_error_handler(request: Request, exc: Exception) -> Response:
    """The one 422 shape (08 §Conventions).

    FastAPI's own body is ``{"detail": [...]}`` with pydantic's full
    error dicts, including ``input`` and ``url``. The contract here is
    narrower and stable: the three fields the SPA renders, and the
    ``code`` every other error carries.
    """

    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return ApiError(
        422, ErrorCode.validation, "validation failed", errors=errors
    ).response()


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler this module owns on ``app``.

    Called by :func:`athanore.api.app.create_app`; the domain classes are
    registered one by one rather than through a common base so that
    Starlette's MRO lookup lands on the most specific row.
    """

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    for cls in DOMAIN_ERRORS:
        app.add_exception_handler(cls, domain_error_handler)
