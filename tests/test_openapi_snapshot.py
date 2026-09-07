"""The committed OpenAPI snapshot is the app's own document.

One wire contract (02): OpenAPI is generated from the code, the SPA's
TypeScript client is generated from OpenAPI, and both are committed. The
check has two halves and this is the first — the snapshot matches the
app. CI's `contract` job is the second: it regenerates the client too
and fails on a tree either generator left dirty.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from athanore.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "snapshots" / "openapi.json"

STALE = (
    "tests/snapshots/openapi.json is stale. Regenerate the snapshot and "
    "the TypeScript client together:\n"
    "    uv run scripts/dump_openapi.py && pnpm -C web gen"
)


@pytest.fixture(scope="module")
def dumper() -> ModuleType:
    """`scripts/dump_openapi.py`, loaded by path.

    `scripts/` is dev machinery rather than a package, so there is no
    import to do. Loading the real file is the point: the renderer under
    test is the one CI runs, not a copy of it.
    """
    path = ROOT / "scripts" / "dump_openapi.py"
    spec = importlib.util.spec_from_file_location("dump_openapi", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_matches_the_app(snapshot: dict[str, Any]) -> None:
    assert create_app().openapi() == snapshot, STALE


def test_snapshot_is_byte_for_byte_what_the_script_writes(
    dumper: ModuleType,
) -> None:
    """The freshness check CI runs is `git diff`, so formatting counts."""
    assert dumper.render() == SNAPSHOT.read_text(encoding="utf-8"), STALE


def test_the_rendering_is_deterministic(dumper: ModuleType) -> None:
    """Sorted keys, so a dict ordering cannot make the check flap."""
    assert dumper.render() == dumper.render()
    document = json.loads(dumper.render())
    assert list(document) == sorted(document)


def test_the_document_describes_the_health_endpoint(
    snapshot: dict[str, Any],
) -> None:
    """08 §System's first route, with its response schema."""
    assert snapshot["info"]["title"] == "Athanore"
    operation = snapshot["paths"]["/api/health"]["get"]
    assert operation["tags"] == ["system"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/Health"
    health = snapshot["components"]["schemas"]["Health"]
    # Only the two an application without collaborators can answer are
    # required; the counts are omitted rather than zero-filled (T043).
    assert sorted(health["required"]) == ["ok", "version"]
    assert set(health["properties"]) == {
        "ok",
        "version",
        "runs_running",
        "tasks_in_progress",
        "pools",
    }


def test_the_document_describes_the_me_endpoint(snapshot: dict[str, Any]) -> None:
    """08 §System's second route: what the SPA reads before anything else."""
    operation = snapshot["paths"]["/api/me"]["get"]
    assert operation["tags"] == ["system"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/Me"
    me = snapshot["components"]["schemas"]["Me"]
    assert sorted(me["required"]) == [
        "auth",
        "authenticated",
        "features",
        "started_at",
        "version",
    ]
    # `auth` is an enum on both sides, so the generated client gives the
    # SPA a union rather than a bare string (03 §Conventions).
    assert me["properties"]["auth"]["enum"] == ["off", "token"]
