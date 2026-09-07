"""What the generated document says about itself (08 §OpenAPI).

Routes describe their own bodies; nothing describes the surface they sit
on. This module is that description, in one place rather than sprinkled
through the routers:

- **the eight tags** of 08 §OpenAPI, in the order that document lists
  them, each with the sentence a reader of ``/docs`` needs. All eight are
  declared even though ``plugins`` has no operations until T049a mounts
  them: the tag vocabulary is part of the contract, and a tag that only
  appears when a route happens to carry it is a vocabulary nobody can
  read off the document;
- **the two security schemes**, ``taskToken`` and ``operatorBearer``,
  and :func:`secure`, which writes the requirement onto every route of a
  router. This is what makes the two auth modes of 08 §Authentication
  visible to somebody reading the document rather than the code;
- **the error responses** those two schemes imply — 401 for an operator
  route without the token a network bind requires, 403 for an agent
  route whose task token is not live — both carrying the one error shape
  of 08 §Conventions;
- **the 422**, declared rather than inherited. FastAPI writes a 422 of
  its own for any operation with parameters or a body and hard-codes
  ``HTTPValidationError`` — ``{"detail": [...]}`` — as its schema, which
  is not the body this API sends: 08 §Conventions fixes ``{error, code,
  errors}`` and
  :func:`~athanore.api.errors.validation_error_handler` sends exactly
  that. Declaring the response on the routers suppresses FastAPI's,
  which matters for more than the wording — the definitions it injects
  are merged over the generated ones *by name*, and one of them is
  ``ValidationError``, which is also 18's ``loc``/``msg``/``type``
  triple. Left alone, FastAPI's version of that name silently replaces
  18's, and ``submission.rejected`` ends up documented with fields it
  never carries. :func:`install_openapi` then drops the declaration again
  from the operations that have nothing to validate, which is FastAPI's
  own rule applied honestly.

``operatorBearer`` is declared on the operator routes unconditionally,
while the server only enforces it on a network bind or under
``require_token`` (12). A security requirement in OpenAPI says what a
credential *is* and where it goes, not that every deployment demands one,
and a document that changed shape with the bind host would be a contract
that depended on how it was served.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from athanore.api.schemas.errors import ApiError

__all__ = [
    "AGENT_RESPONSES",
    "API_ERROR_REF",
    "OPERATOR_BEARER",
    "OPERATOR_RESPONSES",
    "OPERATOR_SCHEME",
    "SECURITY_SCHEMES",
    "TAGS",
    "TASK_TOKEN",
    "TASK_TOKEN_SCHEME",
    "TOKEN_HEADER",
    "VALIDATION_FAILED",
    "install_openapi",
    "secure",
]

#: The header a task token arrives in, and the only place it may (12
#: §Task tokens, finding S3). Spelled once here because three places
#: need it: the scheme below, the MCP path item, and the guard in front
#: of it.
TOKEN_HEADER: Final = "X-Athanore-Token"

#: The eight tags of 08 §OpenAPI, in that document's order.
TAGS: Final[list[dict[str, Any]]] = [
    {
        "name": "workflows",
        "description": "What this server can run, and how to start a run of it.",
    },
    {
        "name": "runs",
        "description": "A run's state, its history and the operator verbs "
        "that change it.",
    },
    {
        "name": "tasks",
        "description": "One attempt of one node: what it submitted, what it "
        "streamed, and the verbs that re-attempt it.",
    },
    {
        "name": "requests",
        "description": "The inbox: everything waiting on a person, and the answers.",
    },
    {
        "name": "agent",
        "description": "What an ACP agent may call, authenticated by the task "
        "token of the attempt it is running.",
    },
    {
        "name": "plugins",
        "description": "The manifest a workflow's declarations publish, and "
        "the routes and actions behind it.",
    },
    {
        "name": "events",
        "description": "The live feed: one server-sent event per event of the "
        "vocabulary.",
    },
    {
        "name": "system",
        "description": "Liveness and the caller's own standing. "
        "Unauthenticated, and carrying no ids.",
    },
]

#: The name of each scheme, as 08 §OpenAPI spells it.
TASK_TOKEN_SCHEME: Final = "taskToken"
OPERATOR_SCHEME: Final = "operatorBearer"

#: The two credentials this API knows (08 §Authentication).
SECURITY_SCHEMES: Final[dict[str, dict[str, Any]]] = {
    TASK_TOKEN_SCHEME: {
        "type": "apiKey",
        "in": "header",
        "name": TOKEN_HEADER,
        "description": (
            "The per-attempt task token. Minted at claim, valid only for "
            "the task it names and only while that attempt is in progress "
            "or waiting, and accepted in this header and nowhere else."
        ),
    },
    OPERATOR_SCHEME: {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "The operator token. Required on a non-loopback bind, or on a "
            "loopback bind with `require_token` set; on the default "
            "loopback bind these routes take no credential at all. "
            "`GET /api/events` additionally accepts it as `?access_token=`, "
            "because a browser's EventSource cannot set a header."
        ),
    },
}

#: The requirement a route declares, per scheme. A list of alternatives,
#: each a mapping of scheme name to scopes; neither scheme has scopes.
TASK_TOKEN: Final[list[dict[str, list[str]]]] = [{TASK_TOKEN_SCHEME: []}]
OPERATOR_BEARER: Final[list[dict[str, list[str]]]] = [{OPERATOR_SCHEME: []}]

#: The 422 of 08 §Conventions, in this API's own shape. Declared on
#: every router so that FastAPI never injects its own (see the module
#: docstring); :func:`install_openapi` removes it again wherever there is
#: nothing to validate.
VALIDATION_FAILED: Final[dict[int | str, dict[str, Any]]] = {
    422: {
        "model": ApiError,
        "description": "The request did not validate. `code` is "
        "`validation` and `errors` names each field that failed.",
    }
}

#: What an operator route answers when the bind requires a token and the
#: request carries none. Passed to ``include_router``, so it lands on
#: every route of the routers that depend on ``operator_auth``.
OPERATOR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    401: {
        "model": ApiError,
        "description": "No operator token, on a bind that requires one.",
    },
    **VALIDATION_FAILED,
}

#: What an agent route answers for a token that is not the live token of
#: the task in the path.
AGENT_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    403: {
        "model": ApiError,
        "description": "The task token is not valid for this task.",
    },
    **VALIDATION_FAILED,
}

#: Where the error shape lives in the document, for the one path item
#: that is written by hand rather than generated (the MCP endpoint).
API_ERROR_REF: Final = "#/components/schemas/ApiError"

#: The methods a path item may carry an operation under. Anything else in
#: one — ``parameters``, ``summary`` — is not an operation and is left
#: alone.
_METHODS: Final = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def secure(router: APIRouter, requirement: list[dict[str, list[str]]]) -> APIRouter:
    """Declare ``requirement`` as the security of every route on ``router``.

    Written onto each route's ``openapi_extra``, which FastAPI merges
    into the operation last of all, and which ``include_router`` carries
    across when the route is copied onto the application. Returns the
    router so a caller can wrap an ``include_router`` argument in it.

    Idempotent: ``create_app`` may be called any number of times in one
    process — the tests and the OpenAPI dump both do — and each call
    writes the same requirement onto the same module-level routers.
    """

    for route in router.routes:
        if isinstance(route, APIRoute):
            extra = route.openapi_extra or {}
            route.openapi_extra = {**extra, "security": requirement}
    return router


def _drop_impossible_validation_errors(document: dict[str, Any]) -> None:
    """Take the 422 back off the operations that cannot produce one.

    :data:`VALIDATION_FAILED` is declared on whole routers, so it lands on
    routes with nothing to validate too — ``GET /api/workflows`` takes no
    parameter and no body, and a documented refusal it can never answer
    is a contract nobody can rely on. The rule is FastAPI's own, read off
    the finished operation: a 422 is possible when there are parameters
    to parse or a body to bind, and not otherwise.
    """

    for item in document.get("paths", {}).values():
        for method, operation in item.items():
            if method not in _METHODS:
                continue
            responses = operation.get("responses", {})
            if "422" not in responses:
                continue
            if operation.get("parameters") or operation.get("requestBody"):
                continue
            del responses["422"]


def install_openapi(app: FastAPI) -> None:
    """Add this module's metadata to ``app``'s generated document.

    Wrapping ``app.openapi`` is FastAPI's own seam for a document it
    cannot generate on its own, and the same one
    :func:`athanore.api.mcp.mount` uses. The wrapper is installed last,
    so what it corrects includes the path item that one inserts, and the
    work is idempotent because the generator caches the document it
    returns.
    """

    generate = app.openapi

    def openapi() -> dict[str, Any]:
        document = generate()
        document.setdefault("components", {})["securitySchemes"] = SECURITY_SCHEMES
        _drop_impossible_validation_errors(document)
        return document

    app.openapi = openapi  # pyright: ignore[reportAttributeAccessIssue]
