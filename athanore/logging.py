"""Structured logging via structlog (02 §Library choices, §Observability).

One process, one log format: pretty on a TTY, JSON everywhere else. Stdlib
``logging`` — uvicorn, alembic, sqlalchemy — is routed through the same
structlog pipeline, so a single run has a single shape on stderr.

Nothing here is called until T011 (CLI) and T031 (server); this module
only defines the configuration and the per-attempt binding seam. The
server must construct uvicorn with ``log_config=None`` (02
§Observability): uvicorn's own dictConfig would otherwise re-capture its
loggers after ``configure_logging`` has run.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
import structlog.typing

__all__ = ["configure_logging", "bind_attempt", "get_logger"]


def _renderer(fmt: str | None) -> structlog.typing.Processor:
    """Pick the renderer for the configured format.

    ``fmt`` is ``AthanoreSettings.log_format``: ``"pretty"`` and ``"json"``
    force a renderer, ``None`` falls back to pretty on a TTY and JSON when
    stderr is redirected (02 §Configuration).
    """
    pretty = fmt == "pretty" or (fmt is None and sys.stderr.isatty())
    if pretty:
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


def configure_logging(fmt: str | None = None) -> None:
    """Configure structlog and route stdlib ``logging`` through it.

    Safe to call more than once: the root handler is replaced rather than
    appended, so reconfiguration does not stack duplicate handlers.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    renderer = _renderer(fmt)

    # stdlib logging (uvicorn, alembic, sqlalchemy) lands here, rendered by
    # the same renderer as structlog's own output.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.contextvars.merge_contextvars,
            structlog.processors.format_exc_info,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)

    # uvicorn installs its own handlers and sets `propagate = False` on
    # these three loggers, so their records would bypass the pipeline
    # above and stderr would carry two shapes at once. It does this from
    # `uvicorn.Config.__init__`, not only from `uvicorn.run()`, so a
    # programmatic server (T051) triggers it too: the server passes
    # `log_config=None` so uvicorn never reinstalls them, and this loop
    # undoes any configuration that already happened.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        foreign = logging.getLogger(name)
        foreign.handlers.clear()
        foreign.propagate = True

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@contextmanager
def bind_attempt(
    run_id: str,
    task_id: str,
    node: str,
    workflow: str,
    attempt: int,
) -> Iterator[None]:
    """Bind the attempt identity into structlog context for the block.

    Every log line emitted inside the block — including agent subprocess
    stderr pumped through structlog — carries these keys (02 §Observability).
    """
    with structlog.contextvars.bound_contextvars(
        run_id=run_id,
        task_id=task_id,
        node=node,
        workflow=workflow,
        attempt=attempt,
    ):
        yield


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger named ``name``."""
    return structlog.get_logger(name)
