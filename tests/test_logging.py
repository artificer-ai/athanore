"""`configure_logging` puts one shape on stderr, whatever emits the record.

The three properties worth pinning are the ones that were wrong once: a
foreign traceback must survive, both chains must produce the same keys,
and uvicorn's loggers must not keep their own handlers.
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from athanore.logging import bind_attempt, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]


def test_stdlib_and_structlog_records_share_a_shape(capsys):
    configure_logging("json")
    logging.getLogger("alembic.runtime.migration").warning("foreign")
    get_logger("athanore.test").warning("native")

    foreign, native = _lines(capsys)
    assert foreign["event"] == "foreign"
    assert native["event"] == "native"
    # `logger` comes from add_logger_name, which has to be in both chains.
    assert set(foreign) == set(native)
    assert foreign["logger"] == "alembic.runtime.migration"


def test_foreign_traceback_is_rendered_not_dropped(capsys):
    configure_logging("json")
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("sqlalchemy.engine").exception("failed")

    (record,) = _lines(capsys)
    # format_exc_info must turn exc_info into a string; without it the raw
    # tuple is str()-ed and the traceback is lost.
    assert isinstance(record["exception"], str)
    assert "ValueError: boom" in record["exception"]


def test_uvicorn_loggers_propagate_to_the_shared_handler(capsys):
    configure_logging("json")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.handlers == []
        assert logger.propagate is True

    logging.getLogger("uvicorn.error").warning("from uvicorn")
    (record,) = _lines(capsys)
    assert record["event"] == "from uvicorn"


def test_bind_attempt_puts_the_attempt_identity_on_every_record(capsys):
    configure_logging("json")
    with bind_attempt("run1", "42", "implement", "v1_feature", 2):
        get_logger("athanore.test").info("inside")
        logging.getLogger("uvicorn.error").info("foreign inside")

    inside, foreign = _lines(capsys)
    for record in (inside, foreign):
        assert record["run_id"] == "run1"
        assert record["node"] == "implement"
        assert record["attempt"] == 2
