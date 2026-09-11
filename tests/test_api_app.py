"""The application factory and the one route it exposes today."""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import version

import httpx
import pytest
from fastapi import FastAPI

from athanore.api.app import VERSION, create_app
from athanore.plugins.decl import Route
from athanore.plugins.mount import MountedPlugins
from athanore.plugins.registry import PluginSpec


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


def test_create_app_takes_the_published_signature() -> None:
    """The collaborators are the shape T042 onward fills in (02)."""
    app = create_app(settings=None, engine=None, store=None, plugins=None)
    assert isinstance(app, FastAPI)


def test_create_app_holds_its_plugins_in_a_live_collection() -> None:
    """`app.state.plugins` is the `MountedPlugins` of 22 §Live mounting.

    Empty for a bare `create_app()`, and with no dispatcher: no engine
    means no bus and nothing to deliver. A sequence handed in — list or
    tuple — is what the collection starts with.
    """

    bare = create_app()
    assert isinstance(bare.state.plugins, MountedPlugins)
    assert bare.state.plugins.specs == ()
    assert bare.state.plugins.dispatch is None

    async def words() -> dict[str, str]:
        return {"word": "athanor"}

    spec = PluginSpec(workflow="gamedev", routes=(Route("/words", ("GET",), words),))
    for plugins in ([spec], (spec,)):
        app = create_app(plugins=plugins)
        assert app.state.plugins.get("gamedev") is spec
        assert app.state.plugins.specs == (spec,)


def test_the_version_is_the_installed_distribution() -> None:
    """The API is versioned by the package version (08 §Versioning)."""
    assert VERSION == version("athanore")
    assert create_app().openapi()["info"]["version"] == VERSION


async def test_health_reports_ok_and_the_version(client: httpx.AsyncClient) -> None:
    """The counts an app with no engine and no store cannot measure are
    omitted rather than zero-filled (02 §Real data only); T043's
    `tests/api/test_auth.py` asserts them where there is something to
    count."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": VERSION}
