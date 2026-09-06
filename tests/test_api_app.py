"""The application factory and the one route it exposes today."""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import version

import httpx
import pytest
from fastapi import FastAPI

from athanore.api.app import VERSION, create_app


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


def test_the_version_is_the_installed_distribution() -> None:
    """The API is versioned by the package version (08 §Versioning)."""
    assert VERSION == version("athanore")
    assert create_app().openapi()["info"]["version"] == VERSION


async def test_health_reports_ok_and_the_version(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": VERSION}
