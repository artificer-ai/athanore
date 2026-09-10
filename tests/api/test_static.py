"""The SPA at `/`, the policy it carries, and CORS (T047).

The MVP's `tests/test_web_serve.py` is the ancestor: there, "serve the
operator interface" meant supervising a `textual-serve` child process,
and its assertions were about that child's command line and its
lifetime. v1 has no child — the interface is a directory of files the
wheel ships (10 §Build) — so what is left to assert is what the server
says about it, and that is this file.

Nothing here needs a store or an engine: the routes under test are the
catch-all, the two open system routes and the middleware around them, so
the application is built the way the OpenAPI dump builds it. What each
test does need is a *particular* `dist`, present or absent, which is why
`athanore.api.static.DIST` is patched before `create_app` reads it
rather than after.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from athanore import web
from athanore.api import static
from athanore.api.app import create_app
from athanore.settings import AthanoreSettings

#: A stand-in for what Vite writes: one document, one hashed asset.
INDEX = """<!doctype html>
<html lang="en" class="dark">
  <head>
    <title>Athanore</title>
    <script type="module" crossorigin src="/assets/index-Test1234.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>
"""

ASSET = "export const built = true;\n"


def write_build(dist: Path) -> None:
    """Write a `dist` a build wrote. Blocking, so an async test threads it."""

    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "index-Test1234.js").write_text(ASSET)
    (dist / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')


#: The Vite dev server of 12 §Operator token — the one caller CORS exists
#: for.
DEV_SERVER = "http://127.0.0.1:5173"


# -- fixtures and helpers ---------------------------------------------------


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """A `dist` a build wrote: `index.html`, an asset, a favicon."""

    dist = tmp_path / "dist"
    write_build(dist)
    return dist


@pytest.fixture
def unbuilt(tmp_path: Path) -> Path:
    """The `dist` of a checkout that has never run a build: absent."""

    return tmp_path / "dist"


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Build an application whose SPA is ``directory``.

    `DIST` is patched rather than passed because `create_app` is what
    calls `mount_spa`, and the point of the test is the application every
    host builds — not one this file wired by hand.
    """

    def build(directory: Path, **overrides: Any) -> FastAPI:
        monkeypatch.setattr(static, "DIST", directory)
        settings = AthanoreSettings(
            root_path=tmp_path,
            db_url=f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
            **overrides,
        )
        return create_app(settings=settings)

    return build


async def call(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    """One request against ``app`` over ASGI."""

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        return await http.request(method, path, **kwargs)


# -- the SPA ----------------------------------------------------------------


async def test_the_root_is_the_document_with_the_policy(serve, built: Path) -> None:
    response = await call(serve(built), "GET", "/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text
    assert response.headers["content-security-policy"] == static.CSP


async def test_plugin_cdns_widen_only_where_code_is_fetched_from(
    serve, built: Path
) -> None:
    """D211: the three fetch directives, and `connect-src` left alone.

    That last part is the containment. A CDN script runs with
    `window.athanore` in reach — the operator's credential and `ops` —
    so if it could also reach a third-party origin, a bad script could
    post what it found there. With `connect-src` closed the worst it can
    do is fail to render.
    """

    response = await call(
        serve(built, plugin_cdns=["https://cdn.jsdelivr.net"]), "GET", "/"
    )

    assert response.headers["content-security-policy"] == (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; connect-src 'self'"
    )


async def test_no_plugin_cdns_is_the_policy_every_install_had(
    serve, built: Path
) -> None:
    """Empty is not "a policy with an empty allowlist" — it is the old one."""

    response = await call(serve(built, plugin_cdns=[]), "GET", "/")

    assert response.headers["content-security-policy"] == static.CSP


@pytest.mark.parametrize(
    "entry",
    [
        "cdn.jsdelivr.net",
        "https://cdn.jsdelivr.net/npm/thing",
        "https://x.net; script-src *",
        "https://x.net 'unsafe-inline'",
        "https://x.net?a=1",
    ],
)
def test_a_plugin_cdn_that_is_not_a_bare_origin_is_refused(entry: str) -> None:
    """A CSP is built by joining strings, so an entry is checked as a host.

    `urlparse` alone is not enough: it takes everything up to the first
    `/` as the netloc, so `https://x.net; script-src *` parses with the
    injection sitting inside the host.
    """

    with pytest.raises(ValidationError):
        AthanoreSettings(plugin_cdns=[entry])


async def test_the_policy_is_the_one_12_states(serve, built: Path) -> None:
    """12 §Plugins, verbatim: two relaxations, and each of them forced."""

    response = await call(serve(built), "GET", "/")

    assert response.headers["content-security-policy"] == (
        "default-src 'self'; script-src 'self' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'"
    )


async def test_the_policy_lets_the_form_validator_compile(serve, built: Path) -> None:
    """`script-src` carries `'unsafe-eval'`, and the SPA cannot do without it.

    RJSF validates with ajv8 (02 §Library choices) and ajv compiles every
    schema — the operator's form, and the JSON Schema meta-schema it is
    checked against — into a `new Function`. Under a bare `script-src
    'self'` that call is refused, ajv throws where it compiles, and RJSF
    reports "Form validation failed" and submits nothing: no plugin
    action, no `form` request and no elicitation can be answered from the
    browser (D182). It is asserted on its own because the string above
    would happily be corrected back the other way by somebody reading 12
    and not this (the browser found it; jsdom evaluates under no policy
    at all).
    """

    response = await call(serve(built), "GET", "/")
    directives = dict(
        (part.split(" ", 1) + [""])[:2]
        for part in (
            piece.strip()
            for piece in response.headers["content-security-policy"].split(";")
        )
        if part
    )

    assert "'unsafe-eval'" in directives["script-src"]
    # And nowhere else: `'unsafe-inline'` for scripts is the relaxation
    # that would let an injected `<script>` run, and it is not here.
    assert "'unsafe-inline'" not in directives["script-src"]


async def test_an_asset_is_served_under_the_same_policy(serve, built: Path) -> None:
    response = await call(serve(built), "GET", "/assets/index-Test1234.js")

    assert response.status_code == 200
    assert response.text == ASSET
    assert "javascript" in response.headers["content-type"]
    assert response.headers["content-security-policy"] == static.CSP


async def test_a_client_route_falls_back_to_the_document(serve, built: Path) -> None:
    """A path only the client router knows is answered with the document."""

    response = await call(serve(built), "GET", "/runs/01JBQ4TR9YV3W0K7X6C2F8M5AZ")

    assert response.status_code == 200
    assert '<div id="root">' in response.text


async def test_head_of_the_root_is_the_same_answer(serve, built: Path) -> None:
    response = await call(serve(built), "HEAD", "/")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == static.CSP


def test_the_packaged_default_is_the_wheels_dist() -> None:
    """The default directory is the package data of 10 §Build."""

    assert static.DIST == Path(web.__file__).resolve().parent / "dist"


# -- what the SPA does not swallow ------------------------------------------


async def test_an_unknown_api_path_is_json_not_the_document(serve, built: Path) -> None:
    """The bug the catch-all exists to not have: a typo answering 200 HTML."""

    response = await call(serve(built), "GET", "/api/nothing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "not_found"
    assert "/api/nothing" in response.json()["error"]


async def test_a_missing_plugin_asset_is_json_too(serve, built: Path) -> None:
    """An asset that arrived as HTML would break the tag that asked for it."""

    response = await call(serve(built), "GET", "/plugins/gamedev/static/panel.js")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_path_that_merely_starts_with_api_is_the_spas(
    serve, built: Path
) -> None:
    response = await call(serve(built), "GET", "/apiary")

    assert response.status_code == 200
    assert '<div id="root">' in response.text


async def test_a_method_an_api_route_lacks_is_still_405(serve, built: Path) -> None:
    """The fallback runs after routing, so it never turns a 405 into a 404."""

    response = await call(serve(built), "POST", "/api/health")

    assert response.status_code == 405


async def test_a_trailing_slash_still_redirects(serve, built: Path) -> None:
    """Starlette's slash redirect also runs before the fallback."""

    response = await call(serve(built), "GET", "/api/health/")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/api/health")


async def test_a_post_to_an_unrouted_path_is_not_the_document(
    serve, built: Path
) -> None:
    response = await call(serve(built), "POST", "/runs")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_route_added_after_the_app_was_built_still_answers(
    serve, built: Path
) -> None:
    """The trap a catch-all would set: T070 mounts plugin routes here."""

    app = serve(built)

    @app.get("/api/plugins/gamedev/late")
    async def late() -> dict[str, bool]:
        return {"ok": True}

    response = await call(app, "GET", "/api/plugins/gamedev/late")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_the_api_still_answers(serve, built: Path) -> None:
    response = await call(serve(built), "GET", "/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "content-security-policy" not in response.headers


# -- a checkout that has not run a build ------------------------------------


async def test_without_a_build_the_root_says_how_to_build(serve, unbuilt: Path) -> None:
    response = await call(serve(unbuilt), "GET", "/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "pnpm -C web build" in response.text
    assert response.headers["content-security-policy"] == static.CSP


async def test_without_a_build_the_api_is_untouched(serve, unbuilt: Path) -> None:
    app = serve(unbuilt)

    assert (await call(app, "GET", "/api/health")).status_code == 200
    assert (await call(app, "GET", "/api/nothing")).status_code == 404


async def test_a_build_that_lands_later_needs_no_restart(serve, unbuilt: Path) -> None:
    """The directory is read per request, so `pnpm build` is enough."""

    app = serve(unbuilt)
    assert "pnpm -C web build" in (await call(app, "GET", "/")).text

    await asyncio.to_thread(write_build, unbuilt)

    assert '<div id="root">' in (await call(app, "GET", "/")).text


# -- CORS -------------------------------------------------------------------


async def test_cors_is_off_by_default(serve, built: Path) -> None:
    response = await call(
        serve(built), "GET", "/api/health", headers={"origin": DEV_SERVER}
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_a_preflight_is_not_answered_by_default(serve, built: Path) -> None:
    response = await call(
        serve(built),
        "OPTIONS",
        "/api/health",
        headers={
            "origin": DEV_SERVER,
            "access-control-request-method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


async def test_a_configured_origin_is_allowed(serve, built: Path) -> None:
    app = serve(built, cors_origins=[DEV_SERVER])

    response = await call(app, "GET", "/api/health", headers={"origin": DEV_SERVER})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEV_SERVER
    assert "access-control-allow-credentials" not in response.headers


async def test_a_configured_origin_gets_its_preflight(serve, built: Path) -> None:
    app = serve(built, cors_origins=[DEV_SERVER])

    response = await call(
        app,
        "OPTIONS",
        "/api/runs",
        headers={
            "origin": DEV_SERVER,
            "access-control-request-method": "POST",
            "access-control-request-headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEV_SERVER
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


async def test_another_origin_is_not_allowed(serve, built: Path) -> None:
    app = serve(built, cors_origins=[DEV_SERVER])

    response = await call(
        app, "GET", "/api/health", headers={"origin": "http://evil.example"}
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# -- the plugin asset seam (09 §Escape hatch; filled by T071) ---------------


async def test_plugin_assets_are_served_from_their_directory(
    serve, built: Path, tmp_path: Path
) -> None:
    assets = tmp_path / "gamedev-static"
    assets.mkdir()
    (assets / "panel.js").write_text(ASSET)
    app = serve(built)

    static.mount_plugin_assets(app, "gamedev", assets)
    response = await call(app, "GET", "/plugins/gamedev/static/panel.js")

    assert response.status_code == 200
    assert response.text == ASSET
    assert response.headers["content-security-policy"] == static.CSP


async def test_a_missing_assets_directory_is_refused_at_registration(
    serve, built: Path, tmp_path: Path
) -> None:
    """09 §Registration: a plugin's mistakes are startup errors."""

    with pytest.raises(RuntimeError):
        static.mount_plugin_assets(serve(built), "gamedev", tmp_path / "nope")


# -- the shipped build under the policy -------------------------------------

#: The real `athanore/web/dist`, read from the package rather than from
#: `static.DIST`, which the `serve` fixture patches per test.
WHEEL_ASSETS: Final[Path] = Path(web.__file__).resolve().parent / "dist" / "assets"

#: One `@font-face` block of a built stylesheet.
FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}")


def build_output(pattern: str) -> list[Path]:
    """Files the real `pnpm -C web build` wrote, or nothing if it has not run."""

    if not WHEEL_ASSETS.is_dir():
        return []
    return sorted(WHEEL_ASSETS.glob(pattern))


async def test_no_bundled_font_is_inlined_as_a_data_url() -> None:
    """The build obeys the policy the server sends with it.

    `font-src 'self'` does not permit `data:`, so a font the bundler
    inlined into the CSS is blocked in every browser: the policy holds
    and the glyphs do not. 12 §Plugins says fonts are bundled and 10
    §Design system says `font-src 'self'` holds, which is only true of
    a build that emits every font as a file — `assetsInlineLimit: 0`.
    """

    sheets = build_output("*.css")
    if not sheets:
        pytest.skip("no build to read: run `pnpm -C web build`")

    for sheet in sheets:
        css = await asyncio.to_thread(sheet.read_text)
        for face in FONT_FACE.findall(css):
            assert "url(data:" not in face, f"{sheet.name} inlines a font"


async def test_every_bundled_font_is_a_file_the_server_serves(serve) -> None:
    """And each of those files is `'self'`: an asset the SPA's own server sends."""

    fonts = build_output("*.woff2")
    if not fonts:
        pytest.skip("no build to read: run `pnpm -C web build`")
    app = serve(WHEEL_ASSETS.parent)

    for font in fonts:
        response = await call(app, "GET", f"/assets/{font.name}")

        assert response.status_code == 200, font.name
        assert response.headers["content-security-policy"] == static.CSP
