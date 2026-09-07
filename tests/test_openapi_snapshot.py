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
from athanore.api.errors import ErrorCode
from athanore.api.openapi import OPERATOR_SCHEME, TAGS, TASK_TOKEN_SCHEME, TOKEN_HEADER
from athanore.events.names import EventName
from athanore.events.payloads import ENVELOPES

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


def test_the_document_declares_the_eight_tags(snapshot: dict[str, Any]) -> None:
    """08 §OpenAPI's vocabulary, in that document's order.

    `plugins` is declared without operations until T049a mounts them:
    the tag list is the contract, not a summary of what happens to be
    registered.
    """
    assert [tag["name"] for tag in snapshot["tags"]] == [
        "workflows",
        "runs",
        "tasks",
        "requests",
        "agent",
        "plugins",
        "events",
        "system",
    ]
    assert all(tag["description"] for tag in snapshot["tags"])
    assert snapshot["tags"] == TAGS
    # Every tag an operation carries is one of the eight.
    used = {
        tag
        for item in snapshot["paths"].values()
        for operation in item.values()
        for tag in operation.get("tags", ())
    }
    assert used <= {tag["name"] for tag in TAGS}


def test_the_two_security_schemes_are_declared(snapshot: dict[str, Any]) -> None:
    """08 §OpenAPI: `taskToken` in a header, `operatorBearer` as a bearer."""
    schemes = snapshot["components"]["securitySchemes"]
    assert set(schemes) == {TASK_TOKEN_SCHEME, OPERATOR_SCHEME}
    assert schemes[TASK_TOKEN_SCHEME]["type"] == "apiKey"
    assert schemes[TASK_TOKEN_SCHEME]["in"] == "header"
    assert schemes[TASK_TOKEN_SCHEME]["name"] == TOKEN_HEADER
    assert schemes[OPERATOR_SCHEME]["type"] == "http"
    assert schemes[OPERATOR_SCHEME]["scheme"] == "bearer"


def test_every_operation_declares_the_credential_it_wants(
    snapshot: dict[str, Any],
) -> None:
    """The two auth modes of 08 §Authentication, readable off the document.

    The agent surface — the five REST routes and the MCP endpoint — takes
    the task token; every operator router takes the operator bearer; the
    system router takes neither, because `/api/health` and `/api/me` are
    unauthenticated on any bind.
    """
    security: dict[str, Any] = {}
    for path, item in snapshot["paths"].items():
        for method, operation in item.items():
            security[f"{method.upper()} {path}"] = (
                operation.get("security"),
                operation["tags"],
            )
    for name, (declared, tags) in security.items():
        if tags == ["system"]:
            assert declared is None, name
        elif tags == ["agent"]:
            assert declared == [{TASK_TOKEN_SCHEME: []}], name
        else:
            assert declared == [{OPERATOR_SCHEME: []}], name
    assert security["POST /mcp/agent"][0] == [{TASK_TOKEN_SCHEME: []}]


def test_every_event_name_is_in_the_schema_enum(snapshot: dict[str, Any]) -> None:
    """The contract test of 13: the vocabulary, mirrored into TypeScript.

    `EventName` reaches the document through `PluginEvent.name` — the one
    envelope whose name the enum does not spell — and the SPA's union is
    generated from it. A name added to 03 and to the enum but not to this
    list would mean the mirror had stopped being generated from the
    source.
    """
    assert snapshot["components"]["schemas"]["EventName"]["enum"] == [
        member.value for member in EventName
    ]
    envelope = snapshot["components"]["schemas"]["PluginEvent"]["properties"]["name"]
    assert {"$ref": "#/components/schemas/EventName"} in envelope["anyOf"]


def test_each_event_envelope_pins_its_own_name(snapshot: dict[str, Any]) -> None:
    """18 §Typing: a `oneOf` per event, each tagged by a constant name.

    The union is only a discriminated union in TypeScript if the variants
    are described at all — a serialiser's return type once made every one
    of them an opaque object (T048) — and it is only *tagged* if the tag is
    always there. 18 §Envelope names `id`, `run_id` and `task_id` as the
    only fields that may be absent, so every other one is required, `name`
    included.
    """
    schemas = snapshot["components"]["schemas"]
    absent = {"id", "run_id", "task_id"}
    for name, envelope in ENVELOPES.items():
        variant = schemas[envelope.__name__]
        assert variant["properties"]["name"]["const"] == name.value
        assert "$ref" in variant["properties"]["data"]
        assert "name" in variant["required"], "the union's tag is never absent"
        assert set(variant["required"]) == set(variant["properties"]) - absent
    plugin = schemas["PluginEvent"]
    assert set(plugin["required"]) == set(plugin["properties"]) - absent
    page = snapshot["paths"]["/api/runs/{run_id}/events"]["get"]
    schema = page["responses"]["200"]["content"]["application/json"]["schema"]
    refs = {one["$ref"] for one in schema["items"]["oneOf"]}
    assert len(refs) == len(EventName) + 1  # ...and `PluginEvent`


def test_the_error_shape_is_the_one_of_08(snapshot: dict[str, Any]) -> None:
    """One `ApiError`, with `code` referencing the whole `ErrorCode` enum."""
    schemas = snapshot["components"]["schemas"]
    error = schemas["ApiError"]
    assert sorted(error["required"]) == ["code", "error"]
    assert error["properties"]["code"]["$ref"] == "#/components/schemas/ErrorCode"
    assert error["additionalProperties"] is True, "08's `...extras` are open"
    assert schemas["ErrorCode"]["enum"] == [member.value for member in ErrorCode]


def test_every_declared_refusal_carries_that_shape(snapshot: dict[str, Any]) -> None:
    """No route answers a 4xx in a shape of FastAPI's invention.

    `HTTPValidationError` is what FastAPI writes when an operation has
    nothing else declared for 422, and its body is not this API's. Its
    absence is also what keeps 18's `ValidationError` — the same
    component name — from being replaced by FastAPI's version of it.
    """
    schemas = snapshot["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert schemas["ValidationError"]["additionalProperties"] is False
    reference = {"$ref": "#/components/schemas/ApiError"}
    for path, item in snapshot["paths"].items():
        for method, operation in item.items():
            for status, response in operation["responses"].items():
                if not status.startswith("4"):
                    continue
                content = response["content"]["application/json"]["schema"]
                assert content == reference, f"{method.upper()} {path} {status}"


def test_a_route_with_nothing_to_validate_declares_no_422(
    snapshot: dict[str, Any],
) -> None:
    """The 422 is declared per router, and taken back off where it cannot
    happen: `GET /api/workflows` takes no parameter and no body."""
    listing = snapshot["paths"]["/api/workflows"]["get"]
    assert sorted(listing["responses"]) == ["200", "401"]
    filtered = snapshot["paths"]["/api/runs"]["get"]
    assert sorted(filtered["responses"]) == ["200", "401", "422"]
