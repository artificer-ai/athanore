"""What the CLI prints, and what it exits with (11 §Exit codes).

Two decisions live here, and they are the two that every verb would
otherwise make for itself.

**How a result is rendered.** :func:`emit` takes the value a verb got
from the API and a description of the columns worth showing, and either
prints a rich table or the JSON the API sent. ``--json`` is not a second
rendering of the same thing through another code path: it is the *whole*
value, unprojected, so ``athanore ls --json | jq`` sees fields the table
had no room for and a script never has to parse a table.

**What a failure costs.** :func:`dispatch` is the one wrapper around the
typer application, and 11 §Exit codes is its whole body: 0 success, 1 an
error the server reported, 2 a usage mistake, 3 no server there. It runs
the application with click's ``standalone_mode`` off so that those
exceptions reach it rather than being turned into a status by the
library: the mapping is Athanore's contract with whatever is reading
``$?``, not click's default.

The three exceptions the mapping names are the three a verb can
legitimately produce. Anything else — a bug in a verb, a broken
response, an ``AttributeError`` — is left to propagate, because a
traceback is the honest report of a defect and an exit status of 1 would
file it under "the server said no".
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from athanore.cli.client import ApiClientError

__all__ = [
    "EXIT_API_ERROR",
    "EXIT_OK",
    "EXIT_UNREACHABLE",
    "EXIT_USAGE",
    "Column",
    "TableSpec",
    "dispatch",
    "emit",
    "fail",
    "main",
    "warn",
]

#: 11 §Exit codes, one constant each.
EXIT_OK: Final = 0
EXIT_API_ERROR: Final = 1
EXIT_USAGE: Final = 2
EXIT_UNREACHABLE: Final = 3


@dataclass(frozen=True, slots=True)
class Column:
    """One column of a table: its heading and where its value comes from.

    ``key`` is a dotted path into the row, so a nested field
    (``pool.name``) is a column without the verb having to flatten the
    response first. A path that is not there renders as an empty cell —
    "unknown is omitted" (02 §Real data only), never a zero or a dash
    that would read as a value the server sent.
    """

    header: str
    key: str
    style: str | None = None


#: The columns of a table, in the order they are printed.
TableSpec = Sequence[Column]


def emit(
    data: Any,
    table_spec: TableSpec | None = None,
    json_flag: bool = False,
    *,
    console: Console | None = None,
) -> None:
    """Print ``data`` as JSON, as a table, or as text.

    ``json_flag`` wins over everything: the value goes out exactly as the
    API sent it, so what a script reads is the wire contract rather than
    this module's opinion of it.

    Without it, ``table_spec`` and the shape of ``data`` decide. A list
    of objects with columns is a table — including an empty list, which
    prints its headings and no rows, because a verb that found nothing
    and a verb that printed nothing look the same otherwise. Anything
    else is text: an object becomes ``key: value`` lines, a list becomes
    one line per item, a scalar becomes itself.
    """

    if json_flag:
        # Deliberately not rich's `print_json`: this is machine-readable
        # output, and a console would reflow and colour it.
        print(json.dumps(data, indent=2, default=str))
        return
    out = console if console is not None else Console()
    if (
        table_spec is not None
        and isinstance(data, Sequence)
        and not isinstance(data, (str, bytes))
    ):
        out.print(_table(data, table_spec))
        return
    _text(data, out)


def _table(rows: Sequence[Any], spec: TableSpec) -> Table:
    """``rows`` as a rich table with the columns of ``spec``."""

    table = Table(box=None, pad_edge=False, header_style="bold")
    for column in spec:
        table.add_column(column.header, style=column.style, overflow="fold")
    for row in rows:
        table.add_row(*(_cell(_lookup(row, column.key)) for column in spec))
    return table


def _lookup(row: Any, key: str) -> Any:
    """The value at the dotted ``key`` of ``row``, or ``None`` if absent."""

    value = row
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _cell(value: Any) -> str:
    """One value as a table cell.

    ``None`` is an empty cell rather than the string ``"None"``: the
    field was not reported, and the table says so by saying nothing.
    Structured values are compact JSON, which is at least readable and
    exact where a repr would be neither.
    """

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)


def _text(data: Any, out: Console) -> None:
    """The no-table rendering: lines a human reads, values unmangled."""

    if data is None:
        return
    if isinstance(data, Mapping):
        for key, value in data.items():
            out.print(f"{key}: {_cell(value)}", highlight=False)
        return
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        for item in data:
            out.print(_cell(item), highlight=False)
        return
    out.print(_cell(data), highlight=False)


def fail(message: str, details: Sequence[str] = ()) -> None:
    r"""Report a failure on stderr, so stdout stays the verb's output.

    Public because the server-side verbs (11 §Server) report failures
    that never went near the API — a port already in use, a database that
    is not SQLite — and a second way of printing "Error:" would drift
    from this one.

    The message is escaped, never interpreted: it carries a path, a
    server's sentence or a TOML key, and ``[workflows.demo]`` is a table
    name rather than a style tag. Only the label around it is markup.
    """

    console = Console(stderr=True)
    console.print(f"[bold red]Error:[/] {escape(message)}", highlight=False)
    for detail in details:
        console.print(f"  {escape(detail)}", highlight=False)


def warn(message: str) -> None:
    """Report something worth saying that is not a failure.

    On stderr with the failures, because it is not the verb's output
    either, and worded as the warning it is: a verb that printed
    "Error:" and then carried on would be telling the operator two
    different things at once.
    """

    Console(stderr=True).print(
        f"[bold yellow]Warning:[/] {escape(message)}", highlight=False
    )


def dispatch(app: typer.Typer, argv: Sequence[str] | None = None) -> int:
    """Run ``app`` and return the exit status of 11 §Exit codes.

    ``argv`` of ``None`` means ``sys.argv[1:]``, which is what the
    console entry point wants; a list is what a test passes.

    ``standalone_mode=False`` is what puts this function in charge:
    click would otherwise catch its own exceptions, print them and call
    :func:`sys.exit` itself, and the status codes below would be click's
    defaults rather than the CLI's contract. The cost is that this
    wrapper renders those failures, which is the two ``show`` calls
    below.
    """

    try:
        result = app(args=None if argv is None else list(argv), standalone_mode=False)
    except typer.BadParameter as exc:
        # The usage failure 11 names: a value the operator typed that a
        # parameter would not take.
        _show(exc)
        return EXIT_USAGE
    except typer.TyperException as exc:
        # Every other refusal from the parser — an unknown verb, a
        # missing argument, a bare `athanore`. Their own `exit_code` is
        # click's, and click's is 11's: 2 for a usage error.
        _show(exc)
        return int(getattr(exc, "exit_code", EXIT_USAGE))
    except typer.Abort:
        # Ctrl-C, or a confirmation answered "no". Nothing to report
        # beyond the fact, and it is not the server's fault.
        fail("aborted")
        return EXIT_API_ERROR
    except ApiClientError as exc:
        fail(exc.message, exc.details)
        return EXIT_API_ERROR
    except httpx.TransportError as exc:
        # No answer at all: nothing listening, a connection that died, a
        # request that timed out. `httpx.ConnectError` is the case 11
        # names and the common one; the rest of the family says the same
        # thing to the operator, and a traceback would say it worse.
        fail(f"{exc} ({type(exc).__name__})")
        return EXIT_UNREACHABLE
    # `typer.Exit(code)` surfaces as the return value rather than as an
    # exception when standalone mode is off, and `--help` returns 0 the
    # same way; anything else a command returned is not a status.
    return result if isinstance(result, int) else EXIT_OK


def _show(exc: Exception) -> None:
    """Print a parser refusal the way click would have."""

    show = getattr(exc, "show", None)
    if callable(show):
        show()
        return
    fail(str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI: :func:`dispatch` over the application of :mod:`athanore.cli`.

    The import is deferred because it points back at the package this
    module is part of: `athanore.cli` builds its typer application out of
    this module's `main`, and asking for the application at call time is
    what lets both live where 17 §T052 puts them.
    """

    from athanore.cli import app

    return dispatch(app, argv)
