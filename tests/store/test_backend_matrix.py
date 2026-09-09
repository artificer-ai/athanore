"""What the store suite's backend matrix does when there is no Postgres.

`tests/store/conftest.py` parametrises every database test over SQLite
and PostgreSQL, and the second parameter has to survive two very
different callers:

- a dev machine that has not run `docker compose --profile pg up -d
  postgres`, where the right answer is a skip that names what it skipped
  and why;
- the nightly workflow, which provisions a database *for* the run, where
  a skip would be a green build that tested nothing (T079).

`ATHANORE_TEST_PG_REQUIRED` is what tells the two apart, and this is the
suite for it. It exercises the policy functions directly rather than
through a parametrised test, because the thing under test is precisely
what happens when the fixtures decline to run a test.
"""

from __future__ import annotations

import pytest

from tests.store.conftest import (
    PG_REQUIRED_ENV,
    _no_postgres,
    _postgres_is_required,
)


def test_unset_means_a_missing_database_is_only_a_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PG_REQUIRED_ENV, raising=False)
    assert _postgres_is_required() is False
    with pytest.raises(pytest.skip.Exception) as skipped:
        _no_postgres("nothing is listening")
    assert "nothing is listening" in str(skipped.value)


@pytest.mark.parametrize("value", ["1", "true", "yes", " 1 ", "on"])
def test_set_means_a_missing_database_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The nightly job's posture: no database is a red build, not a green one."""

    monkeypatch.setenv(PG_REQUIRED_ENV, value)
    assert _postgres_is_required() is True
    with pytest.raises(pytest.fail.Exception) as failed:
        _no_postgres("nothing is listening")
    message = str(failed.value)
    assert PG_REQUIRED_ENV in message
    assert "nothing is listening" in message


@pytest.mark.parametrize("value", ["", "0", "false", "no", "NO", " False "])
def test_the_negatives_are_the_only_things_that_disarm_it(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A value nobody meant as a negative must not turn the check off.

    The variable is set by a workflow file, so the failure mode to guard
    against is a typo that reads as "off" — which is why the accepted
    negatives are an explicit set and everything else is "on".
    """

    monkeypatch.setenv(PG_REQUIRED_ENV, value)
    assert _postgres_is_required() is False
