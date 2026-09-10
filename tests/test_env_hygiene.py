"""The rootdir fixture that keeps the shell out of a test (D205).

`conftest.py` at the rootdir drops every configuration variable before
each test, so that a developer — or the dev container, which exports
`ATHANORE_HOST` and `ATHANORE_PORT` — cannot change what a suite asserts
by exporting a name. These are the assertions that say so: the hazard is
covered, nothing configured survives into a test, and the names the
harness itself is driven by are not configuration and are left alone.
"""

from __future__ import annotations

import os
from pathlib import Path

from athanore.settings import AthanoreSettings

#: Names that are not settings: the harness reads them, so the fixture
#: must not take them. `ATHANORE_IN_CONTAINER` is how `scripts/*.sh`
#: knows which side of the boundary it is on, and the other three select
#: suites (`-m postgres`, the live smoke).
HARNESS_ENV = frozenset(
    {
        "ATHANORE_IN_CONTAINER",
        "ATHANORE_TEST_PG_URL",
        "ATHANORE_TEST_PG_REQUIRED",
        "ATHANORE_SMOKE",
        "ATHANORE_SMOKE_TIMEOUT",
    }
)


def test_the_two_names_the_dev_container_exports_are_configuration(
    config_env: frozenset[str],
) -> None:
    assert {"ATHANORE_HOST", "ATHANORE_PORT"} <= config_env


def test_no_configuration_name_survives_into_a_test(
    config_env: frozenset[str],
) -> None:
    assert not config_env & set(os.environ)


def test_settings_built_without_a_host_bind_loopback(tmp_path: Path) -> None:
    """The property every API and engine fixture leans on."""

    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.host == "127.0.0.1"
    assert settings.is_loopback


def test_the_harness_names_are_left_in_the_environment(
    config_env: frozenset[str],
) -> None:
    assert not config_env & HARNESS_ENV
