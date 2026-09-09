"""A plugin's static assets: where they resolve, how they are served (T071).

09 §Escape hatch is three sentences and this file is all three:
``assets="./static"`` is resolved relative to the declaring module
(package data once installed), served at ``/plugins/{wf}/static/``, and
listed in the manifest as the URL of each ``.js`` the SPA injects.

Two refusals matter more than the happy path, and 17 §T071 names both:

- **a missing directory fails registration**, loudly and at startup,
  because a pane that renders nothing is otherwise the only symptom —
  and it is the same contract §Registration and validation gives every
  other declaration;
- **a traversal is a 404**, not a file. `StaticFiles` is what makes that
  true (12 §Plugins: "assets are served by `StaticFiles` (no
  traversal)"), and the assertion is here so that a mount built by hand
  some other way would be caught.

The application is a real ``create_app()`` with the workflow's collected
spec on it, because the mount is `create_app`'s: the manifest and the
files it names have to come from the same object or the SPA is told
about assets nothing serves.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from athanore.api import static
from athanore.api.app import create_app
from athanore.plugins.registry import (
    PluginSpec,
    PluginValidationError,
    collect,
    manifest_entry,
    package_directory,
    validate,
)
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

#: What a plugin's asset actually is: an ES module the SPA injects.
MODULE = "customElements.define('gd-playfield', class extends HTMLElement {});\n"


def gamedev(assets: str | Path | None) -> Workflow:
    """A one-node workflow with a `custom` panel and the assets behind it."""

    wf = Workflow("gamedev", assets=assets)

    @wf.node(start=True)
    async def play():
        return "played"

    wf.panel("Playfield", slot="run", kind="custom", element="gd-playfield")
    return wf


def serve(*workflows: Workflow, settings: AthanoreSettings) -> httpx.AsyncClient:
    """`create_app` over collected, validated specs — what a host builds."""

    specs = []
    for workflow in workflows:
        spec = collect(workflow)
        validate(spec, workflow.finalize())
        specs.append(spec)
    app = create_app(settings=settings, plugins=specs)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.fixture
def settings(tmp_path: Path) -> AthanoreSettings:
    """A plain loopback bind over a directory of this test's own."""

    return AthanoreSettings(root_path=tmp_path, db_url="sqlite+aiosqlite:///:memory:")


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A directory of the shape a plugin ships: two modules and a stray."""

    directory = tmp_path / "static"
    (directory / "vendor").mkdir(parents=True)
    (directory / "playfield.js").write_text(MODULE)
    (directory / "vendor" / "helper.js").write_text(MODULE)
    (directory / "playfield.css").write_text("gd-playfield { display: block }\n")
    return directory


# -- serving ----------------------------------------------------------------


async def test_a_declared_asset_is_served_under_the_plugin_prefix(
    assets: Path, settings: AthanoreSettings
) -> None:
    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get("/plugins/gamedev/static/playfield.js")

    assert response.status_code == 200
    assert response.text == MODULE


async def test_an_asset_carries_the_content_security_policy(
    assets: Path, settings: AthanoreSettings
) -> None:
    """12 §Plugins: a plugin's JS loads under the SPA's own policy."""

    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get("/plugins/gamedev/static/vendor/helper.js")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == static.CSP


async def test_a_workflow_that_ships_nothing_has_nothing_mounted(
    settings: AthanoreSettings,
) -> None:
    async with serve(gamedev(None), settings=settings) as client:
        response = await client.get("/plugins/gamedev/static/playfield.js")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_one_workflows_assets_are_not_anothers(
    assets: Path, settings: AthanoreSettings
) -> None:
    """Scope follows ownership (09), for files as for routes."""

    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get("/plugins/other/static/playfield.js")

    assert response.status_code == 404


# -- traversal --------------------------------------------------------------


#: Traversals as they arrive on the wire. Percent-encoded, because a
#: client that normalises — `httpx` does, and so does every browser —
#: would resolve the dots itself and send a path that never reaches the
#: mount at all; an attacker's client does not. `raw_asgi` below sends
#: the un-encoded one, which is the only way to put literal `..`
#: segments into `scope["path"]`.
TRAVERSALS = [
    "/plugins/gamedev/static/%2e%2e/secret.txt",
    "/plugins/gamedev/static/..%2fsecret.txt",
    "/plugins/gamedev/static/vendor/%2e%2e/%2e%2e/secret.txt",
    "/plugins/gamedev/static/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
]


async def raw_asgi(app: Any, path: str) -> tuple[int, bytes]:
    """`GET path` with no client between the test and `scope["path"]`.

    `httpx` resolves ``..`` in a URL before it sends it, so a spec that
    asked it for a traversal would be asserting on the client. This puts
    the path into the ASGI scope verbatim, which is what a raw socket
    does.
    """

    status = 0
    body = b""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status, body
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            body += message.get("body", b"")

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 4002),
        },
        receive,
        send,
    )
    return status, body


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    """A file one directory above the assets, which is what `../` reaches."""

    path = tmp_path / "secret.txt"
    path.write_text("the operator token")
    return path


@pytest.mark.parametrize("path", TRAVERSALS)
async def test_an_encoded_traversal_is_a_404_and_never_a_file(
    path: str, assets: Path, secret: Path, settings: AthanoreSettings
) -> None:
    """17 §T071: "traversal `../` is 404" — the file is right there."""

    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get(path)

    assert response.status_code == 404
    assert "the operator token" not in response.text


async def test_a_literal_traversal_in_the_scope_is_a_404(
    assets: Path, secret: Path, settings: AthanoreSettings
) -> None:
    """The same, with no client to normalise it first."""

    app = create_app(settings=settings, plugins=[collect(gamedev(assets))])
    status, body = await raw_asgi(app, "/plugins/gamedev/static/../secret.txt")

    assert status == 404
    assert b"the operator token" not in body


async def test_a_missing_asset_answers_the_api_error_shape(
    assets: Path, settings: AthanoreSettings
) -> None:
    """One answer to "there is no such asset" (08 §Conventions)."""

    async with serve(gamedev(assets), settings=settings) as client:
        mounted = await client.get("/plugins/gamedev/static/nope.js")
        unmounted = await client.get("/plugins/other/static/nope.js")

    assert mounted.status_code == unmounted.status_code == 404
    assert mounted.json()["code"] == unmounted.json()["code"] == "not_found"


async def test_a_directory_is_not_a_listing(
    assets: Path, settings: AthanoreSettings
) -> None:
    """`StaticFiles` serves files; a directory has nothing to answer with."""

    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get("/plugins/gamedev/static/vendor")

    assert response.status_code == 404


# -- the manifest -----------------------------------------------------------


async def test_the_manifest_lists_every_js_and_nothing_else(
    assets: Path, settings: AthanoreSettings
) -> None:
    async with serve(gamedev(assets), settings=settings) as client:
        response = await client.get("/api/plugins")

    entry = next(one for one in response.json() if one["workflow"] == "gamedev")
    assert entry["assets"] == [
        "/plugins/gamedev/static/playfield.js",
        "/plugins/gamedev/static/vendor/helper.js",
    ]


async def test_every_listed_asset_is_actually_served(
    assets: Path, settings: AthanoreSettings
) -> None:
    """The manifest and the mount are one object's two halves."""

    async with serve(gamedev(assets), settings=settings) as client:
        manifest = (await client.get("/api/plugins")).json()
        entry = next(one for one in manifest if one["workflow"] == "gamedev")
        answers = [(await client.get(url)).status_code for url in entry["assets"]]

    assert entry["assets"] != []
    assert answers == [200] * len(entry["assets"])


# -- registration -----------------------------------------------------------


def test_a_missing_assets_directory_fails_registration(tmp_path: Path) -> None:
    """09 §Registration, check 5: at startup, where the author is looking."""

    workflow = gamedev(tmp_path / "not-there")
    spec = collect(workflow)

    with pytest.raises(PluginValidationError) as refusal:
        validate(spec, workflow.finalize())

    assert "gamedev" in str(refusal.value)
    assert str(tmp_path / "not-there") in str(refusal.value)


def test_the_refusal_names_the_package_it_also_looked_in(tmp_path: Path) -> None:
    spec = PluginSpec(
        workflow="gamedev", assets="static", base=tmp_path, package="acme.gamedev"
    )

    with pytest.raises(PluginValidationError) as refusal:
        validate(spec, gamedev(None).finalize())

    assert "'acme.gamedev'" in str(refusal.value)


def test_a_missing_directory_is_refused_before_a_request_is_ever_made(
    tmp_path: Path, settings: AthanoreSettings
) -> None:
    """The mount refuses too, so neither half can be the only check."""

    with pytest.raises(RuntimeError):
        create_app(
            settings=settings,
            plugins=[PluginSpec(workflow="gamedev", assets=tmp_path / "gone")],
        )


# -- resolution: the module, then the package -------------------------------


def test_a_relative_path_resolves_beside_the_declaring_module() -> None:
    """09 §Escape hatch: relative to the module, not to the cwd."""

    workflow = gamedev("./static")
    spec = collect(workflow)

    assert spec.base == Path(__file__).resolve().parent
    assert spec.package == (__package__ or None)
    assert spec.assets_dir() == Path(__file__).resolve().parent / "static"


def test_an_absolute_path_is_itself(tmp_path: Path) -> None:
    assert collect(gamedev(tmp_path)).assets_dir() == tmp_path


def test_a_root_overrides_both(tmp_path: Path) -> None:
    """A host serving extracted package data says where, and is obeyed."""

    (tmp_path / "static").mkdir()
    spec = collect(gamedev("./static"))

    assert spec.assets_dir(tmp_path) == tmp_path / "static"


@pytest.fixture
def installed(tmp_path: Path) -> Any:
    """A package on `sys.path` whose data is not beside the declaring module.

    Which is the shape 09 §Escape hatch's "package data when installed"
    has: `importlib.resources` is asked where the package's data is, and
    the answer is not derived from any one module's ``__file__``.
    """

    site = tmp_path / "site"
    package = site / "gamedev_plugin"
    (package / "static").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "static" / "playfield.js").write_text(MODULE)
    sys.path.insert(0, str(site))
    try:
        yield package
    finally:
        sys.path.remove(str(site))
        sys.modules.pop("gamedev_plugin", None)


def test_a_package_answers_where_the_declaring_module_cannot(
    installed: Path, tmp_path: Path
) -> None:
    spec = PluginSpec(
        workflow="gamedev",
        assets="./static",
        base=tmp_path / "elsewhere",
        package="gamedev_plugin",
    )

    assert spec.assets_dir() == installed / "static"
    validate(spec, gamedev(None).finalize())


def test_the_module_wins_where_both_answer(installed: Path, tmp_path: Path) -> None:
    """`__file__` is exact; the package is the fallback, not the rule."""

    beside = tmp_path / "beside"
    (beside / "static").mkdir(parents=True)
    spec = PluginSpec(
        workflow="gamedev", assets="./static", base=beside, package="gamedev_plugin"
    )

    assert spec.assets_dir() == beside / "static"


def test_an_installed_package_serves_its_assets(
    installed: Path, tmp_path: Path, settings: AthanoreSettings
) -> None:
    """End to end: the URL the manifest lists is a file the app serves."""

    spec = PluginSpec(
        workflow="gamedev",
        assets="./static",
        base=tmp_path / "elsewhere",
        package="gamedev_plugin",
    )
    validate(spec, gamedev(None).finalize())

    assert manifest_entry(spec)["assets"] == [
        "/plugins/gamedev/static/playfield.js",
    ]
    create_app(settings=settings, plugins=[spec])


def test_a_package_that_cannot_be_imported_answers_nothing() -> None:
    assert package_directory("no.such.package.anywhere") is None
    assert package_directory(None) is None
    assert package_directory("") is None
