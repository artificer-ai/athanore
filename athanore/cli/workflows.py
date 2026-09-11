"""``athanore workflows``: the table, and the three verbs that change it
(11 §Verbs, 22 §CLI).

The bare verb is what it always was — every registered workflow, its
graph and its pool. It is a group now, because the set of workflows a
server runs is no longer fixed at ``serve`` time (22): ``add`` registers
a target on the running server, ``reload`` loads a registered name
again from its file, and ``rm`` drops one. Each is a thin client of one
route — ``POST``, ``PUT`` and ``DELETE /api/workflows`` — and prints
what the server answered, the way every other verb does:

- ``add`` and ``reload`` print the workflow as the table prints one
  entry, with its ``target`` beside the pool; ``rm`` prints the task ids
  the removal interrupted, one per line, so the operator sees what
  stopped. ``--json`` is the API's own body, whole.
- ``--persist`` asks the server to write (or remove) the
  ``[workflows.<name>]`` row of its ``athanore.toml``, and the verb
  prints the path the server reports in ``X-Athanore-Persisted`` as its
  last line. Under ``--json`` that receipt goes to **stderr**, so stdout
  stays the API's JSON and ``| jq`` still parses (D252).
- A load that failed is priced as ``athanore serve`` prices a target it
  could not resolve — exit **2**, with the failure's ``stage`` and
  ``detail`` under the message — because it is the same mistake (11
  §Exit codes). A pool the server does not have is the same price,
  for the same reason ``athanore serve`` refuses a binding to one at 2
  (22 §Pools, D252). Every other refusal — a registered name, an
  unknown workflow, a pool move with attempts in flight, a row that
  could not be written — is the server's sentence and exit 1, through
  :func:`athanore.cli.output.dispatch` like any other verb.

Nothing here touches a file: the CLI never edits ``athanore.toml``
itself and never reads a workflow's source, because the server is the
one process that knows which file is its configuration (22
§Persistence).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Annotated, Any, Final

import typer
from rich.console import Console
from rich.markup import escape

from athanore.cli import Options, app
from athanore.cli.client import ApiClientError, Reply
from athanore.cli.inspect import console, join, line, mapping, mappings
from athanore.cli.output import EXIT_USAGE, Column, TableSpec, emit, fail

__all__ = [
    "NODES",
    "PERSISTED_HEADER",
    "add",
    "print_workflow",
    "reload",
    "rm",
    "workflows",
    "workflows_app",
]

#: The receipt header of 22 §Wire: the ``athanore.toml`` a row was
#: written to or removed from. Spelled here as the client reads it; the
#: server spells it in ``athanore.api.routers.workflows``.
PERSISTED_HEADER: Final = "X-Athanore-Persisted"

#: The two codes the verbs price at exit 2 rather than 1 (22 §CLI, §Pools).
_USAGE_CODES: Final = frozenset({"workflow_load_failed", "unknown_pool"})

#: One workflow's nodes, which is the graph 11 asks for.
NODES: Final[TableSpec] = (
    Column("NODE", "name"),
    Column("GEN", "generation"),
    Column("EDGES", "edges"),
    Column("PRIORITY", "priority"),
    Column("RETRIES", "retries"),
    Column("TIMEOUT", "timeout"),
)

workflows_app = typer.Typer(
    name="workflows",
    invoke_without_command=True,
    help="The workflows this server runs, and the verbs that change the set.",
)
app.add_typer(workflows_app, name="workflows")


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _node_row(name: str, node: Mapping[str, Any]) -> dict[str, Any]:
    """One node of a workflow's graph, projected onto :data:`NODES`."""

    return {
        "name": name,
        "generation": node.get("generation"),
        "edges": join(node.get("edges")) or "(terminal)",
        "priority": node.get("priority"),
        "retries": node.get("retries"),
        "timeout": node.get("timeout"),
    }


def print_workflow(workflow: Mapping[str, Any]) -> None:
    """One ``WorkflowOut`` as the table shows it: a header line, then the nodes.

    ``target`` joins the header only when the server reports one — a
    programmatic registration has none (22 §Terms), and its line reads
    as it always did.
    """

    head = (
        f"{workflow.get('name')}  start={workflow.get('start')}  "
        f"pool={workflow.get('pool')} "
        f"{workflow.get('in_flight')}/{workflow.get('capacity')}"
    )
    target = workflow.get("target")
    if target is not None:
        head += f"  target={target}"
    line(head)
    nodes = mapping(workflow.get("nodes"))
    emit([_node_row(name, mapping(node)) for name, node in nodes.items()], NODES)


def _receipt(options: Options, reply: Reply, did: str) -> None:
    """Print the path a persisting verb wrote or removed a row of, if any.

    On stdout in table mode, where it is the verb's last line; on stderr
    under ``--json``, where stdout is the API's JSON and nothing else
    (D252). Nothing at all when the response carries no receipt — the
    operator did not ask, or a ``rm --persist`` found no row to remove.
    """

    path = reply.headers.get(PERSISTED_HEADER)
    if path is None:
        return
    text = f"{did} {path}"
    if options.json:
        Console(stderr=True).print(escape(text), highlight=False)
        return
    line(text)


@contextmanager
def _priced() -> Iterator[None]:
    """Exit 2 for the two refusals that are the operator's to fix (22 §CLI).

    A ``workflow_load_failed`` prints its ``stage`` and ``detail`` under
    the message, because the fix is in the file the target names and
    the stage says where; an ``unknown_pool`` prints the server's
    sentence, which names the pools that exist. Anything else is left
    for :func:`athanore.cli.output.dispatch`: the server's message and
    exit 1.
    """

    try:
        yield
    except ApiClientError as exc:
        if exc.code not in _USAGE_CODES:
            raise
        body = mapping(exc.body)
        details: list[str] = []
        if exc.code == "workflow_load_failed":
            details.append(f"{body.get('stage')}: {body.get('detail')}")
        fail(exc.message, details)
        raise typer.Exit(EXIT_USAGE) from exc


def _body(target: str | None, pool: str | None, persist: bool) -> dict[str, Any]:
    """The request body, with the keys the operator did not give left out.

    ``target`` omitted from a ``PUT`` is what tells the server to
    re-resolve the recorded one, so it must be absent rather than
    ``null``; ``pool`` omitted keeps the binding on ``PUT`` and takes
    the default on ``POST``.
    """

    body: dict[str, Any] = {"persist": persist}
    if target is not None:
        body["target"] = target
    if pool is not None:
        body["pool"] = pool
    return body


# --------------------------------------------------------------------------
# The verbs
# --------------------------------------------------------------------------


@workflows_app.callback(invoke_without_command=True)
def workflows(ctx: typer.Context) -> None:
    """The workflows this server runs: their graphs and their pools."""

    if ctx.invoked_subcommand is not None:
        return
    options = Options.of(ctx)
    with options.client() as client:
        listed = client.get("/api/workflows")
    if options.json:
        emit(listed, json_flag=True)
        return
    out = console()
    for index, workflow in enumerate(mappings(listed)):
        if index:
            out.print()
        print_workflow(workflow)


@workflows_app.command()
def add(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Argument(
            help="The workflow to register: `module:attr` or `path/to/file.py:attr`."
        ),
    ],
    pool: Annotated[
        str | None,
        typer.Option(
            "--pool", help="Bind it to this pool; the default pool otherwise."
        ),
    ] = None,
    persist: Annotated[
        bool,
        typer.Option(
            "--persist",
            help="Write the registration to the server's athanore.toml too.",
        ),
    ] = False,
) -> None:
    """Register a workflow on the running server, from a target.

    The name it registers under is the loaded workflow's own. A target
    that does not load is exit 2, with where the load stopped; a name
    that is already registered is the server's refusal and exit 1.
    """

    options = Options.of(ctx)
    with options.client() as client, _priced():
        reply = client.exchange(
            "POST", "/api/workflows", body=_body(target, pool, persist)
        )
    if options.json:
        emit(reply.body, json_flag=True)
    else:
        print_workflow(mapping(reply.body))
    _receipt(options, reply, "persisted to")


@workflows_app.command()
def reload(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The registered workflow to reload.")],
    target: Annotated[
        str | None,
        typer.Argument(
            help="The target to load it from; what the server loaded it from "
            "when omitted."
        ),
    ] = None,
    pool: Annotated[
        str | None,
        typer.Option("--pool", help="Move it to this pool; keep its pool otherwise."),
    ] = None,
    persist: Annotated[
        bool,
        typer.Option(
            "--persist",
            help="Rewrite the registration in the server's athanore.toml too.",
        ),
    ] = False,
) -> None:
    """Load a registered workflow again, so the next task runs the new code.

    An attempt already running finishes on the body it started with. A
    target that now defines a differently named workflow is refused: that
    is a new workflow, and `add` is how it arrives.
    """

    options = Options.of(ctx)
    with options.client() as client, _priced():
        reply = client.exchange(
            "PUT", f"/api/workflows/{name}", body=_body(target, pool, persist)
        )
    if options.json:
        emit(reply.body, json_flag=True)
    else:
        print_workflow(mapping(reply.body))
    _receipt(options, reply, "persisted to")


@workflows_app.command()
def rm(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The registered workflow to remove.")],
    persist: Annotated[
        bool,
        typer.Option(
            "--persist",
            help="Remove its registration from the server's athanore.toml too.",
        ),
    ] = False,
) -> None:
    """Unregister a workflow, interrupting whatever it was running.

    Prints the task ids that were interrupted, one per line. Nothing is
    deleted: the workflow's runs stay listed, flagged unregistered, and
    resume when it is added back.
    """

    options = Options.of(ctx)
    with options.client() as client, _priced():
        reply = client.exchange(
            "DELETE", f"/api/workflows/{name}", params={"persist": persist}
        )
    if options.json:
        emit(reply.body, json_flag=True)
    else:
        for task_id in mapping(reply.body).get("task_ids") or ():
            line(str(task_id))
    _receipt(options, reply, "removed from")
