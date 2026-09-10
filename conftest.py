"""What every suite in this repository is protected from: the shell.

The dev container carries `ATHANORE_HOST` and `ATHANORE_PORT`, because
`compose.yaml` passes both through so an operator can serve on an address
of their choosing. pydantic-settings reads `ATHANORE_*` above
`athanore.toml` and below constructor kwargs (02 §Configuration), so a
settings object a test does not pass `host` to binds whatever that shell
exported — and `create_app()` refuses a non-loopback bind with no
operator token (12 §Operator token). `ATHANORE_HOST=0.0.0.0` in the shell
that starts the gate therefore turns most of `tests/api` red without a
line of code having changed.

Three suites already scrubbed the environment for themselves
(`tests/cli`, `tests/smoke`, `tests/test_settings.py`) and two fixtures
claim in their docstrings that no `ATHANORE_*` variable can change what a
test asserts. This makes that claim true for every test, at the rootdir,
so `examples/tests` is covered by the same fixture (D205): every name
that can reach `AthanoreSettings` or the CLI's connection is dropped
before each test. Names that are not configuration survive —
`ATHANORE_IN_CONTAINER`, `ATHANORE_TEST_PG_URL`,
`ATHANORE_TEST_PG_REQUIRED`, `ATHANORE_SMOKE` — because the harness
itself is driven by them.

A test that wants one of these names sets it with `monkeypatch.setenv` in
its own body or in a fixture of its own suite, both of which run after
this one.
"""

from __future__ import annotations

import os

import pytest

from athanore.settings import _LEGACY_ENV, AthanoreSettings

#: Every environment name that can change a configured value: one
#: `ATHANORE_<FIELD>` per field of
#: :class:`~athanore.settings.AthanoreSettings`, the deprecated
#: `ARTIFICER_*` names it still reads as a fallback, and the two names
#: :func:`athanore.cli.client.resolve` takes a connection from. Derived
#: from the model rather than listed, so a field added later is covered
#: without an edit here, and a name that is not configuration cannot be
#: swept up by a prefix.
CONFIG_ENV = frozenset(
    {f"ATHANORE_{name.upper()}" for name in AthanoreSettings.model_fields}
    | set(_LEGACY_ENV)
    | {"ATHANORE_URL", "ATHANORE_TOKEN"}
)


@pytest.fixture(autouse=True)
def _clean_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every configuration variable the shell exported."""

    for name in CONFIG_ENV & set(os.environ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config_env() -> frozenset[str]:
    """:data:`CONFIG_ENV`, for the tests that assert what it covers.

    A fixture rather than an import: every `conftest.py` in this tree is
    imported under the module name `conftest`, so `from conftest import
    …` resolves to whichever one pytest loaded first.
    """

    return CONFIG_ENV
