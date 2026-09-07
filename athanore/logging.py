"""Structured logging via structlog (02 §Library choices, §Observability).

One process, one log format: pretty on a TTY, JSON everywhere else. Stdlib
``logging`` — uvicorn, alembic, sqlalchemy — is routed through the same
structlog pipeline, so a single run has a single shape on stderr.

That one pipeline is also where credentials are taken back out.
:class:`RedactingFilter` sits on the shared handler and rewrites records
*before* they are formatted, which is what lets it reach both shapes at
once: a foreign record's ``msg`` and ``args`` (uvicorn's access line is
``'%s - "%s %s HTTP/%s" %d'`` with the full query string in an argument,
so ``GET /api/events?access_token=…`` would otherwise be written to the
log verbatim) and a structlog record's event dict, whose values are still
Python objects at that point rather than rendered JSON. 12 §Hygiene:
never log tokens, ``Authorization`` headers, or the SSE query string.

The server must construct uvicorn with ``log_config=None`` (02
§Observability): uvicorn's own dictConfig would otherwise re-capture its
loggers after ``configure_logging`` has run — and, since the filter lives
on the handler this module installs, would take the redaction off with
them.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import structlog
import structlog.typing

__all__ = [
    "REDACTED",
    "RedactingFilter",
    "bind_attempt",
    "configure_logging",
    "get_logger",
    "redact",
]

#: What a credential is replaced with. A fixed marker rather than a
#: deletion: a log line that shows a token *was* presented and did not
#: say what it was is more useful than one that shows nothing at all.
REDACTED = "[redacted]"

#: Keys whose value is a credential wherever one turns up — a structlog
#: keyword, a header dict, a parsed query. Compared case-insensitively
#: with ``-`` normalised to ``_``, so ``X-Athanore-Token`` and
#: ``x_athanore_token`` are the same key.
_CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "operator_token",
        "task_token",
        "token",
        "x_athanore_token",
    }
)

#: ``Authorization: Bearer abc`` / ``X-Athanore-Token=abc`` inside an
#: already-formatted string. The separator is captured so the line keeps
#: its shape, and an optional ``Bearer`` is swallowed with the value
#: rather than left behind as the only half worth hiding.
_HEADER = re.compile(
    r"\b(authorization|x-athanore-token|x_athanore_token)(\s*[:=]\s*)"
    r"(?:bearer\s+)?[^\s,;\"']+",
    re.IGNORECASE,
)

#: ``?access_token=abc`` in a URL or an access-log line. The value ends
#: at the next query separator, whitespace or quote.
_QUERY = re.compile(r"\b(access_token)(=)[^\s&\"']+", re.IGNORECASE)

#: How deep :func:`redact` walks a nested structure. Log payloads are
#: shallow; the cap is there so a self-referential value cannot turn a
#: log call into a recursion error.
_MAX_DEPTH = 6


def _is_credential(key: object) -> bool:
    """Whether ``key`` names a credential (:data:`_CREDENTIAL_KEYS`)."""

    return isinstance(key, str) and key.strip().lower().replace("-", "_") in (
        _CREDENTIAL_KEYS
    )


def redact(value: Any, depth: int = 0) -> Any:
    """``value`` with every credential in it replaced by :data:`REDACTED`.

    Two rules, applied wherever they fit. A string has its
    ``Authorization`` headers and ``access_token`` query parameters
    rewritten in place; a mapping additionally loses the whole value of
    any key that *names* a credential, because a structlog keyword or a
    header dict carries the token bare, with nothing around it to match.

    Anything that is not a string, mapping, list or tuple is returned as
    it is: this is a log filter, not a serialiser, and a value it does
    not understand is one it must not damage.
    """

    if isinstance(value, str):
        return _QUERY.sub(rf"\1\2{REDACTED}", _HEADER.sub(rf"\1\2{REDACTED}", value))
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_credential(key) else redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        items = [redact(item, depth + 1) for item in value]
        return tuple(items) if isinstance(value, tuple) else items
    return value


class RedactingFilter(logging.Filter):
    """Take credentials out of a record before anything formats it.

    Installed on the one handler :func:`configure_logging` builds, so it
    sees every record in the process — uvicorn's access line, structlog's
    event dict, an agent's pumped stderr — and it sees them while
    ``msg`` and ``args`` are still the objects the caller passed. A
    processor at the end of the chain would only ever get the rendered
    string, by which point a token inside a nested value has already been
    written into it.

    Never drops a record: redaction is not a reason to lose a log line.

    A record with ``args`` is redacted through its *formatted* message
    and not through the format string, because the two cannot be
    separated safely: ``log.warning("Authorization: Bearer %s", token)``
    hides its credential in the argument, while rewriting the format
    string on its own would delete the ``%s`` the argument was going to
    fill and turn the record into a ``TypeError``. So the message is
    rendered, redacted, and — only when that changed something — kept as
    a message with no arguments left to substitute. When it changed
    nothing the arguments are still scrubbed in place, element for
    element, for the credential a mapping's *key* names and a flattened
    string cannot express.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.args:
            record.msg = redact(record.msg)
            return True
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
            return True
        record.args = (
            redact(record.args)
            if isinstance(record.args, Mapping)
            else tuple(redact(arg) for arg in record.args)
        )
        return True


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
    # Before the formatter, and on the handler rather than on a logger:
    # a filter on a logger is skipped for records that propagate up from
    # a child, which is every uvicorn and sqlalchemy record here.
    handler.addFilter(RedactingFilter())

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
