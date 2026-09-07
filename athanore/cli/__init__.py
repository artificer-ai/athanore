"""The typer application, and the options every verb shares (11).

`athanore` is a thin client over the HTTP API plus one server verb (11).
This module is the application itself: the connection flags of 11
§Client connection, which are global because they belong to *reaching*
the server rather than to any one thing you might ask it, and the
:class:`Options` a verb reads them back out of.

The flags are read here and resolved in :func:`athanore.cli.client.resolve`,
never both. Typer can read an environment variable into an option by
itself, and doing that would put half of 11's precedence in the parser
and the other half in the client, with the config file — which typer
knows nothing about — landing in whichever of them noticed it last. So
the options default to ``None``, meaning "the operator did not say", and
the client is the one place that knows what silence resolves to.

``--url`` is validated as it is parsed, which is why it is a parameter
callback rather than a check inside a verb: a URL the CLI could not
reach a server at is a mistake in what was typed, and 11 §Exit codes
prices that at 2, not at 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer

from athanore.cli.client import DEFAULT_URL, Client, is_http_url
from athanore.cli.output import main

__all__ = ["Options", "app", "main"]


@dataclass(frozen=True, slots=True)
class Options:
    """What the operator said about the connection and the output.

    Set on the click context by :func:`athanore`, so a verb takes it with
    ``ctx.obj`` and never re-declares the flags. ``None`` means the
    operator did not say — :func:`athanore.cli.client.resolve` decides
    what that means.
    """

    url: str | None = None
    token: str | None = None
    json: bool = False

    def client(self) -> Client:
        """The API client these options describe."""

        return Client(self.url, self.token)


def _check_url(value: str | None) -> str | None:
    """Refuse a ``--url`` that is not one (11 §Exit codes: usage is 2)."""

    if value is not None and not is_http_url(value):
        raise typer.BadParameter(
            f"{value!r} is not an http(s) URL; the server is named as "
            f"e.g. {DEFAULT_URL}."
        )
    return value


app = typer.Typer(
    name="athanore",
    help="Code-defined AI agent workflows over the Agent Client Protocol.",
    no_args_is_help=True,
)


@app.callback()
def athanore(
    ctx: typer.Context,
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            callback=_check_url,
            help=f"The server to talk to. Defaults to {DEFAULT_URL}.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help=(
                "The operator token. Not needed against a loopback server; "
                "ATHANORE_TOKEN and `athanore login` are the other two ways "
                "to give it."
            ),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the API's JSON instead of a table."),
    ] = False,
) -> None:
    """Athanore: an orchestrator for code-defined AI agent workflows."""

    ctx.obj = Options(url=url, token=token, json=json_output)
