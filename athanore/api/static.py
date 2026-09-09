"""The built SPA, the plugin assets, and CORS (08 §Static, 12 §Plugins).

Three things hang off `/` rather than off `/api/`, and all three are this
module's.

**The SPA.** `pnpm -C web build` writes `athanore/web/dist`, which the
wheel ships as package data (10 §Build), and :func:`mount_spa` serves it
at `/`: a file when the path names one, and `index.html` when it does
not, because a path the server has no route for is the client router's
to interpret.

It is the router's **fallback**, not a catch-all route. A `Mount` at `/`
matches every path, so it would answer before any route registered after
it — a plugin's routes (T070), an asset mount (T071), a route a test
hangs off a real application — and turn each of them into the SPA's
document with no error anywhere. Starlette consults `router.default`
only once nothing has matched at all, which is exactly when a request is
the SPA's, and leaves the routing that comes first untouched: a method
an API route does not have is still its 405, and a trailing slash is
still its redirect.

Two things the fallback still decides for itself.

- **`/api/…` and `/plugins/…` never become the document.** A typo'd
  endpoint that answered `200 text/html` would be a client bug that
  looks like a parsing bug, and a missing asset that arrived at a
  `<script type="module">` as HTML would be worse; both answer with the
  404 of 08 §Conventions instead — JSON, with a `code` a client can
  branch on.
- **Only `GET` and `HEAD` reach the SPA.** A `POST` to a path with no
  route is a 404 in the same shape, not a document.

**The policy.** Every response this module serves — the SPA's HTML, its
assets, a plugin's assets — carries the content-security policy of 12
§Plugins verbatim. It is what makes "a plugin's JS runs in the
operator's browser" a bounded statement rather than an open one: no
third-party origin, no inline script, and `style-src`'s one relaxation
because React and the panel splitter set inline `style` attributes.

**CORS.** Off unless `cors_origins` names an origin (12 §Operator token).
The SPA is same-origin in production and no cookies are used, so the one
caller that needs it is the Vite dev server on another port — and a
wildcard default would undo the loopback-first posture for everyone else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from athanore import web
from athanore.api.errors import ApiError, ErrorCode
from athanore.settings import AthanoreSettings

__all__ = [
    "CSP",
    "DIST",
    "RESERVED_PREFIXES",
    "SPA",
    "PolicyFiles",
    "install_cors",
    "mount_plugin_assets",
    "mount_spa",
]

#: The content-security policy of 12 §Plugins, verbatim. Two relaxations
#: and no more, each forced by something the SPA is built out of:
#:
#: - ``style-src 'unsafe-inline'``: React and the panel splitter set
#:   inline ``style`` attributes.
#: - ``script-src 'unsafe-eval'``: RJSF validates with ajv8 (02 §Library
#:   choices), and ajv compiles every schema — the operator's form and
#:   the JSON Schema meta-schema it is checked against — into a
#:   ``new Function``. Without it, ajv throws where it compiles, RJSF
#:   reports "Form validation failed", and **no form in the app can be
#:   submitted at all**: not a plugin action, not a `form` request, not
#:   an elicitation (D182).
#:
#: Fonts are bundled (10), so nothing loads from a third party, and
#: ``'self'`` is the whole allowance for every origin directive.
CSP: Final[str] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)

#: Where `pnpm -C web build` writes and what the wheel ships as package
#: data (10 §Build). Read at mount time rather than closed over at import
#: time, so a test can point one application at a directory of its own.
DIST: Final[Path] = Path(web.__file__).resolve().parent / "dist"

#: Path prefixes the SPA does not own. A request under one of these that
#: no route claimed is a 404 in the API's error shape, never `index.html`.
RESERVED_PREFIXES: Final[tuple[str, ...]] = ("/api", "/plugins")

#: What `/` says when `dist/index.html` is not there. A fresh checkout
#: that has not run a build is the ordinary case, not a failure, so the
#: page names the two commands rather than reporting a missing file. No
#: inline script: the policy above holds here too.
UNBUILT_PAGE: Final[str] = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Athanore — the interface is not built</title>
    <style>
      body { font-family: ui-monospace, monospace; line-height: 1.6;
             margin: 4rem auto; max-width: 44rem; padding: 0 1.5rem;
             background: #0b0d10; color: #d6dbe1; }
      h1 { font-size: 1.25rem; font-weight: 600; }
      pre { background: #14181d; border: 1px solid #232a32; border-radius: 6px;
            padding: 1rem; overflow-x: auto; }
      a { color: #8fb8ff; }
    </style>
  </head>
  <body>
    <h1>The interface is not built</h1>
    <p>
      The server is running, but <code>athanore/web/dist</code> holds no
      <code>index.html</code>. Build the SPA:
    </p>
<pre>pnpm -C web install
pnpm -C web build</pre>
    <p>
      The API is up either way: <a href="/api/health">/api/health</a>,
      <a href="/docs">/docs</a>.
    </p>
  </body>
</html>
"""


class PolicyFiles(StaticFiles):
    """`StaticFiles` that puts :data:`CSP` on everything it serves.

    The header goes on here rather than in a middleware because it
    belongs to *these* responses: the API's JSON is not a document a
    policy means anything for, and a policy on every response would be a
    claim about routes this module does not own.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["content-security-policy"] = CSP
        return response


def _unbuilt() -> HTMLResponse:
    """The build-the-SPA page, under the same policy as the SPA itself."""

    return HTMLResponse(
        UNBUILT_PAGE,
        headers={"content-security-policy": CSP, "cache-control": "no-store"},
    )


def _is_reserved(path: str) -> bool:
    """Is ``path`` under a prefix the server owns rather than the SPA?"""

    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in RESERVED_PREFIXES
    )


async def _static_or_none(
    files: StaticFiles, path: str, scope: Scope
) -> Response | None:
    """``files``' answer for ``path``, or ``None`` when there is no such file.

    Only a 404 becomes ``None``. A 401 from an unreadable file and a 405
    from a method `StaticFiles` will not serve are answers in their own
    right, and swallowing them would report "no such file" for a file
    that is right there.
    """

    try:
        return await files.get_response(path, scope)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None


class SPA:
    """The built SPA, as the ASGI app the router falls back to.

    Holds the directory rather than the files: it is read once per
    request, so a `pnpm -C web build` under a running server takes
    effect without a restart, and a checkout that has never run one is
    an ordinary state rather than a startup failure.
    """

    def __init__(self, directory: Path, unmatched: ASGIApp) -> None:
        #: What the router did before — a 404 for HTTP, a close for a
        #: websocket. Anything this app does not answer goes back to it.
        self.unmatched = unmatched
        self.files = PolicyFiles(directory=directory, check_dir=False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.unmatched(scope, receive, send)
            return
        response = await self.response(Request(scope, receive))
        await response(scope, receive, send)

    async def response(self, request: Request) -> Response:
        """The file, the document, or the 404 that is neither."""

        path = request.url.path
        if request.method not in ("GET", "HEAD") or _is_reserved(path):
            return ApiError(
                404, ErrorCode.not_found, f"no such endpoint: {path}"
            ).response()
        # `get_path` normalises away `.` and `..`, and `StaticFiles`
        # refuses anything that still resolves outside the directory.
        asset = await _static_or_none(
            self.files, self.files.get_path(request.scope), request.scope
        )
        if asset is not None:
            return asset
        index = await _static_or_none(self.files, "index.html", request.scope)
        return index if index is not None else _unbuilt()


def mount_spa(app: FastAPI, directory: Path | None = None) -> SPA:
    """Serve the built SPA from ``directory`` (default :data:`DIST`) at ``/``.

    Installed as `app.router.default`, so every route — including the
    ones a plugin registers long after this call — is matched first, and
    the SPA answers only for a path nothing else claimed.
    """

    spa = SPA(DIST if directory is None else directory, app.router.default)
    app.router.default = spa
    return spa


def mount_plugin_assets(app: FastAPI, workflow: str, directory: Path) -> Mount:
    """Serve one workflow's asset directory at ``/plugins/{workflow}/static``.

    The seam 09 §Escape hatch describes and T071 fills: a workflow that
    declares ``assets=`` gets its directory mounted here at registration,
    served by `StaticFiles` (so no path escapes it) under the same CSP as
    the SPA.

    ``check_dir`` is left on, so a declared directory that does not exist
    raises here — at registration, which is where 09 §Registration and
    validation says a plugin's mistakes are reported.
    """

    mount = Mount(
        f"/plugins/{workflow}/static",
        app=PolicyFiles(directory=directory),
        name=f"plugin-assets:{workflow}",
    )
    app.router.routes.append(mount)
    return mount


def install_cors(app: FastAPI, settings: AthanoreSettings) -> None:
    """Add `CORSMiddleware` when — and only when — ``cors_origins`` is set.

    The origins are the ones configured, never ``*``: 12 §Operator token
    has CORS off by default because the SPA is same-origin in production,
    and the one caller that needs it is a Vite dev server on another
    port. Credentials stay off with it — no cookie is used, so the token
    travels in a header the browser will not send unasked, and there is
    no CSRF surface to open.
    """

    if not settings.cors_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
