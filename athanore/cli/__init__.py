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

The other thing this module holds is the **bare-workflow alias** (11
§Verbs): ``athanore feature_build "title"`` is ``athanore submit
feature_build "title"``. It is a property of the application rather than
of any verb — it decides *which* verb runs — so it lives in the group
class typer builds the application from, and
:meth:`WorkflowAliasGroup.resolve_command` is the whole of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import typer
from typer._click import Context as ClickContext
from typer.core import TyperGroup

from athanore.cli.client import DEFAULT_URL, Client, is_http_url
from athanore.cli.output import EXIT_USAGE, fail, main
from athanore.cli.verbs import RESERVED

__all__ = ["Options", "WorkflowAliasGroup", "app", "main"]


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

    @classmethod
    def of(cls, ctx: typer.Context) -> Options:
        """The options the application's callback set on ``ctx``.

        A verb takes its connection with this rather than re-declaring
        ``--url`` and ``--token``, and a context that carries something
        else — a verb invoked from a test with no callback in front of it
        — gets the defaults rather than an ``AttributeError``.
        """

        options = ctx.obj
        return options if isinstance(options, Options) else cls()

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


class WorkflowAliasGroup(TyperGroup):
    """The application's group, with the MVP's bare-workflow shorthand.

    ``athanore feature_build "Build X"`` submits a run of
    ``feature_build`` (11 §Verbs). The alias is resolved here, in click's
    own "which command did they mean" step, rather than by rewriting the
    argument list somewhere earlier: ``resolve_command`` already receives
    what is left after the group's own options were parsed, and returning
    the ``submit`` command *with the workflow name still in ``args``*
    makes that name ``submit``'s first argument. Nothing else in the CLI
    has to know the alias exists.

    Two things must both be true, and 17 §T054 names both:

    - the word is **not a verb** — not in
      :data:`athanore.cli.verbs.RESERVED`, and not a command registered
      on this group. :meth:`athanore.server.Server.register` refuses a
      workflow named after a verb precisely so that these two questions
      cannot disagree, and asking both is what keeps the alias correct if
      one of them ever drifts from the other;
    - the word **is a workflow this server runs** — it is in
      ``GET /api/workflows``. Without that half, a mistyped workflow name
      would become a ``POST`` the operator did not know was being made,
      answered by a 404 about a workflow they never asked to submit.

    A word that is neither is a usage error naming both facts, because
    the operator meant one of the two and "no such command" does not say
    which of them they got wrong.
    """

    def resolve_command(
        self, ctx: ClickContext, args: list[str]
    ) -> tuple[str | None, Any, list[str]]:
        name = args[0] if args else ""
        submit = self.get_command(ctx, "submit")
        if (
            not name
            or name.startswith("-")
            or name in RESERVED
            or submit is None
            or self.get_command(ctx, name) is not None
        ):
            return super().resolve_command(ctx, args)
        with self._client(ctx) as client:
            if name in _workflow_names(client, name):
                # `args` whole rather than `args[1:]`: the workflow name
                # is `submit`'s first argument, and click passes the rest
                # of the line on to it unchanged.
                return "submit", submit, args
            ctx.fail(
                f"{name!r} is not an athanore verb, and {client.url} runs no "
                f"workflow of that name; `athanore workflows` lists the ones "
                f"it does."
            )

    @staticmethod
    def _client(ctx: ClickContext) -> Client:
        """A client from the flags the group has already parsed.

        ``ctx.params`` and not ``ctx.obj``: click resolves the subcommand
        *before* it invokes the group callback, so the :class:`Options`
        that callback sets does not exist yet — but the two values it
        will be built from have been parsed and are here.
        """

        return Client(ctx.params.get("url"), ctx.params.get("token"))


def _workflow_names(client: Client, name: str) -> frozenset[str]:
    """The names ``GET /api/workflows`` reports, for the alias check.

    A server that cannot be reached cannot answer the question, and the
    CLI does not guess at it: the message names both of the things the
    operator might have meant, because with no answer neither has been
    ruled out. It is still 11 §Exit codes' **2** rather than its 3 — a
    first word the application could not resolve to a verb is a mistake
    in what was typed, and 3 is what a verb that *did* resolve returns
    when it cannot reach the server.
    """

    try:
        listed = client.get("/api/workflows")
    except httpx.TransportError as exc:
        fail(
            f"{name!r} is not an athanore verb, and {client.url} could not be "
            f"asked whether it is a workflow: {exc}"
        )
        raise typer.Exit(EXIT_USAGE) from exc
    if not isinstance(listed, list):  # pragma: no cover - the API returns a list
        return frozenset()
    return frozenset(
        str(entry["name"])
        for entry in listed
        if isinstance(entry, dict) and "name" in entry
    )


app = typer.Typer(
    name="athanore",
    cls=WorkflowAliasGroup,
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


# The verb modules, imported last and for their effect: each hangs its
# commands on `app` above with typer's decorators, so `athanore serve`
# exists without this module having to know what `serve` takes. Last
# because the application has to exist before a module can decorate it,
# which is also why they may import `app` and `Options` back from here —
# both are bound by the time these lines run (E402 is that ordering, not
# an accident).
from athanore.cli import db as _db  # noqa: E402, F401
from athanore.cli import inspect as _inspect  # noqa: E402, F401
from athanore.cli import serve as _serve  # noqa: E402, F401
from athanore.cli import steer as _steer  # noqa: E402, F401
from athanore.cli import token as _token  # noqa: E402, F401
