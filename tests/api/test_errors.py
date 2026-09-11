"""The error shape, the mappings onto it, and the body cap (08, T042).

Two surfaces are under test and they are deliberately exercised
differently. The mappings are asserted through a throwaway app whose
routes raise the domain exceptions, because the routers that will raise
them for real do not exist until T043 — what has to hold is that the
handlers `create_app` installs translate them. The body cap is asserted
through `create_app()` itself as well, because it is the one behaviour
that must work with no route at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

from athanore.api.app import create_app
from athanore.api.errors import (
    DOMAIN_ERRORS,
    ApiError,
    ErrorCode,
    api_error_for,
    install_error_handlers,
)
from athanore.api.middleware import BodyLimitMiddleware, BodyTooLarge
from athanore.engine.errors import (
    Conflict,
    EngineError,
    NotFound,
    UnknownNode,
    UnknownWorkflow,
)
from athanore.graph import GraphError
from athanore.requests.errors import (
    AlreadyAnswered,
    InvalidAnswer,
    InvalidOption,
    RequestNotFound,
    StaleRequest,
)
from athanore.settings import AthanoreSettings

LIMIT = 1_048_576
TWO_MIB = b"x" * (2 * 1024 * 1024)


class Body(BaseModel):
    name: str
    count: int


def raising_app(exc: BaseException) -> FastAPI:
    """An app whose one route raises `exc`, with the real handlers on it."""

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


async def get(app: FastAPI, path: str = "/boom") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.get(path)


# --------------------------------------------------------------------------
# The shape itself
# --------------------------------------------------------------------------


def test_the_body_is_error_code_and_extras() -> None:
    error = ApiError(409, ErrorCode.conflict, "run is not paused", run_id="01H")
    assert error.body == {
        "error": "run is not paused",
        "code": "conflict",
        "run_id": "01H",
    }
    assert error.status == 409


def test_an_unknown_code_is_refused_at_construction() -> None:
    """The vocabulary is closed: T048 publishes it as an OpenAPI enum."""
    with pytest.raises(ValueError):
        ApiError(400, "nearly_but_not_quite", "no")


@pytest.mark.parametrize("key", ["error", "code"])
def test_extras_may_not_shadow_the_shape(key: str) -> None:
    with pytest.raises(ValueError, match="shadow"):
        ApiError(400, ErrorCode.validation, "no", **{key: "hijacked"})


def test_the_codes_are_the_vocabulary_of_08() -> None:
    assert {code.value for code in ErrorCode} == {
        "not_found",
        "conflict",
        "forbidden",
        "unauthorized",
        "validation",
        "invalid_option",
        "already_answered",
        "stale_request",
        "graph_error",
        "unknown_workflow",
        "unknown_node",
        "payload_too_large",
        "plugin_error",
        # The four of a live registration (22 §Wire, T086).
        "workflow_load_failed",
        "unknown_pool",
        "registration_unavailable",
        "persist_failed",
    }


def test_a_non_native_extra_serialises_via_str() -> None:
    """08 §Conventions; an error body must never fail to render."""

    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    rendered = ApiError(400, ErrorCode.validation, "no", value=Opaque()).response().body
    assert b'"value":"opaque"' in rendered


async def test_an_api_error_raised_by_a_route_renders_itself() -> None:
    response = await get(raising_app(ApiError(403, ErrorCode.forbidden, "not yours")))
    assert response.status_code == 403
    assert response.json() == {"error": "not yours", "code": "forbidden"}


# --------------------------------------------------------------------------
# The domain mappings
# --------------------------------------------------------------------------

MAPPINGS: list[tuple[BaseException, int, str]] = [
    (NotFound("no such run"), 404, "not_found"),
    (UnknownWorkflow("no workflow 'nope'"), 404, "unknown_workflow"),
    (UnknownNode("no node 'nope'"), 404, "unknown_node"),
    (Conflict("run is completed"), 409, "conflict"),
    (GraphError("edge to an unknown node"), 409, "graph_error"),
    (RequestNotFound("no such request"), 404, "not_found"),
    (InvalidOption("no option 'maybe'"), 400, "invalid_option"),
    (InvalidAnswer("answer failed validation"), 422, "validation"),
    (AlreadyAnswered("answered already"), 409, "already_answered"),
    (StaleRequest("the task ended"), 409, "stale_request"),
]


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    MAPPINGS,
    ids=[type(exc).__name__ for exc, _, _ in MAPPINGS],
)
async def test_a_domain_exception_maps_to_its_status_and_code(
    exc: BaseException, status: int, code: str
) -> None:
    response = await get(raising_app(exc))
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["error"] == str(exc)


def test_a_subclass_row_wins_over_its_base() -> None:
    """`UnknownWorkflow` is a `NotFound`; the MRO decides which row."""
    mapped = api_error_for(UnknownWorkflow("nope"))
    assert mapped is not None
    assert mapped.code is ErrorCode.unknown_workflow


def test_an_exception_with_no_message_gets_the_row_default() -> None:
    mapped = api_error_for(NotFound())
    assert mapped is not None
    assert mapped.message == "not found"


def test_an_unmapped_exception_is_not_claimed() -> None:
    """The base refusals are abstract; a 500 is the honest answer."""
    assert api_error_for(EngineError("nothing raises this")) is None
    assert api_error_for(RuntimeError("a defect")) is None


async def test_an_invalid_answer_carries_its_per_field_errors() -> None:
    exc = InvalidAnswer("does not fit", [{"loc": ["age"], "msg": "nope", "type": "x"}])
    response = await get(raising_app(exc))
    assert response.status_code == 422
    assert response.json() == {
        "error": "does not fit",
        "code": "validation",
        "errors": [{"loc": ["age"], "msg": "nope", "type": "x"}],
    }


def test_every_mapped_class_has_a_handler_registered() -> None:
    app = FastAPI()
    install_error_handlers(app)
    for cls in DOMAIN_ERRORS:
        assert cls in app.exception_handlers


# --------------------------------------------------------------------------
# The 422 shape
# --------------------------------------------------------------------------


@pytest.fixture
async def validating_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    @app.post("/echo")
    async def echo(body: Body) -> Body:
        return body

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


async def test_a_validation_failure_is_the_one_422_shape(
    validating_client: httpx.AsyncClient,
) -> None:
    response = await validating_client.post("/echo", json={"name": "a"})
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation failed",
        "code": "validation",
        "errors": [
            {"loc": ["body", "count"], "msg": "Field required", "type": "missing"}
        ],
    }


async def test_the_422_never_leaks_fastapi_s_own_body(
    validating_client: httpx.AsyncClient,
) -> None:
    """`detail`, `input` and `url` are FastAPI's shape, not the contract."""
    response = await validating_client.post("/echo", json={"name": "a", "count": "x"})
    body = response.json()
    assert "detail" not in body
    assert set(body) == {"error", "code", "errors"}
    assert set(body["errors"][0]) == {"loc", "msg", "type"}


async def test_malformed_json_is_the_same_422_shape(
    validating_client: httpx.AsyncClient,
) -> None:
    response = await validating_client.post(
        "/echo", content=b"{nope", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation"


# --------------------------------------------------------------------------
# The body cap
# --------------------------------------------------------------------------


def limited_app(limit: int = LIMIT) -> FastAPI:
    """An endpoint that reads its whole body, behind the cap."""

    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, limit=limit)
    install_error_handlers(app)

    @app.post("/sink")
    async def sink(request: Request) -> PlainTextResponse:
        body = await request.body()
        return PlainTextResponse(str(len(body)))

    return app


async def chunks(payload: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    """`payload` as a stream, which is a request with no `Content-Length`."""

    for start in range(0, len(payload), size):
        yield payload[start : start + size]


async def post(
    app: FastAPI,
    path: str = "/sink",
    *,
    content: bytes | AsyncIterator[bytes] | None = None,
    json: object = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.post(path, content=content, json=json)


async def test_a_declared_content_length_past_the_limit_is_refused() -> None:
    response = await post(limited_app(), content=TWO_MIB)
    assert "content-length" in {k.lower() for k in response.request.headers}
    assert response.status_code == 413
    assert response.json() == {
        "error": f"request body exceeds the {LIMIT} byte limit",
        "code": "payload_too_large",
    }


async def test_a_chunked_body_past_the_limit_is_refused_as_it_arrives() -> None:
    """No `Content-Length` at all: the counting wrapper is the guard."""
    response = await post(limited_app(), content=chunks(TWO_MIB))
    assert "content-length" not in {k.lower() for k in response.request.headers}
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_a_body_at_the_limit_is_read_whole() -> None:
    payload = b"y" * LIMIT
    response = await post(limited_app(), content=chunks(payload))
    assert response.status_code == 200
    assert response.text == str(LIMIT)


async def test_a_body_one_byte_past_the_limit_is_refused() -> None:
    response = await post(limited_app(8), content=chunks(b"123456789"))
    assert response.status_code == 413


async def test_the_cap_runs_before_routing() -> None:
    """A declared oversize body never reaches a route, existing or not."""
    response = await post(limited_app(), path="/nothing-here", content=TWO_MIB)
    assert response.status_code == 413


async def test_a_get_with_no_body_is_untouched() -> None:
    response = await get(limited_app(), "/openapi.json")
    assert response.status_code == 200


async def test_the_real_app_caps_bodies_at_the_configured_limit() -> None:
    app = create_app(AthanoreSettings(body_limit=1024))
    response = await post(app, path="/api/health", content=b"z" * 2048)
    assert response.status_code == 413
    assert response.json() == {
        "error": "request body exceeds the 1024 byte limit",
        "code": "payload_too_large",
    }


async def test_the_real_app_uses_the_settings_default() -> None:
    """The default is 1 MiB (02 §Configuration), counted as it arrives."""
    app = create_app()
    assert app.state.settings.body_limit == LIMIT

    @app.post("/sink")
    async def sink(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    response = await post(app, content=chunks(TWO_MIB))
    assert response.status_code == 413


async def test_an_undeclared_body_nobody_reads_is_not_counted() -> None:
    """The counter is on `receive`, so an unread body is never seen.

    A route that does not read its body — and a request that reaches no
    route at all — answers as it would have. Nothing was buffered, which
    is what the cap exists to prevent; declaring a size past the limit
    is still refused before routing (above).
    """
    response = await post(limited_app(), path="/nothing-here", content=chunks(TWO_MIB))
    assert response.status_code == 404


async def _receive() -> Message:
    return {"type": "http.disconnect"}


async def _send(message: Message) -> None:
    return None


async def test_a_lifespan_scope_passes_straight_through() -> None:
    """The cap is an HTTP concern; every other scope is not its business."""
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    await BodyLimitMiddleware(app, limit=8)({"type": "lifespan"}, _receive, _send)
    assert seen == ["lifespan"]


async def test_an_oversize_body_read_after_the_headers_went_out_is_raised() -> None:
    """There is no 413 left to send, so the failure reaches the server.

    An app that streams — headers first, body read afterwards — is the
    one case the middleware cannot answer. Swallowing it would leave a
    truncated 200 looking like a complete one.
    """

    async def streaming(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            await receive()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * 16, "more_body": True}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    with pytest.raises(BodyTooLarge):
        await BodyLimitMiddleware(streaming, limit=8)(
            {"type": "http", "headers": []}, receive, send
        )
    assert [message["type"] for message in sent] == ["http.response.start"]
