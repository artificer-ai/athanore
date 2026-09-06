"""Shared pytest configuration.

The one thing here is the exit code of a marker-selected run that
matches nothing. `pytest -m postgres` selects the Postgres variants of
the store suite, which arrive in T014; until then it deselects every
test and pytest reports `NO_TESTS_COLLECTED` (exit 5). A nightly
workflow reads that as a failure, so an explicit marker selection that
comes up empty is reported as a pass instead (D76).

The narrowing to `-m` is deliberate: a run with no marker expression
that collects nothing is a broken invocation — a mistyped `-k`, a
`testpaths` that no longer resolves — and must keep failing.
"""

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if (
        exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED
        and session.config.option.markexpr
    ):
        session.exitstatus = pytest.ExitCode.OK
