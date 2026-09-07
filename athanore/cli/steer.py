"""The verbs that change something (11 §Verbs).

The write half of the CLI. Every one of them is a single call to an
endpoint the SPA calls too — there is no verb here that needs an
endpoint of its own, and none that keeps state between calls. That is
deliberate and it is what keeps the CLI honest: a precondition lives in
:class:`athanore.engine.ops.Ops`, surfaces as a 409, and reaches the
operator as the sentence the server wrote (11 §Exit codes' 1). The CLI
never decides that a run cannot be paused, and never phrases a refusal it
did not receive.

Two verbs need a read before their write, and only two:

- **``answer``** is the one verb with real argument ambiguity, because
  ``allow_once``, ``looks fine to me`` and ``{"ship": true}`` are the
  same shape on a command line and three different bodies on the wire.
  The request's own ``mode`` is what tells them apart, and it is a fact
  the server states rather than one the CLI can infer, so ``answer``
  reads the request first (06 §The model).
- **``permit`` / ``deny``** with no option id pick one *by kind* —
  ``allow_once`` before ``allow_always``, ``reject_once`` before
  ``reject_always`` — which needs the options the agent offered. Given an
  option id explicitly they are one call, and the server is what refuses
  an id the request does not offer.

``rm`` asks before it deletes, because a deleted run takes its tasks, its
events, its work log and its transcripts with it (07). ``--yes`` is the
answer for a script.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, Final

import typer

from athanore.cli import Options, app
from athanore.cli.client import Client
from athanore.cli.output import EXIT_API_ERROR, emit, fail

__all__ = [
    "REQUEST",
    "SettableStatus",
    "answer",
    "cancel",
    "deny",
    "edit",
    "move",
    "pause",
    "permit",
    "position",
    "rerun",
    "resume",
    "retry",
    "rm",
    "set_status",
]


class SettableStatus(StrEnum):
    """The three statuses an operator may write on a task (08 §Tasks).

    The wire's own vocabulary, restated here for the same reason the
    generated TypeScript restates it: the parser has to know the choices
    to refuse a fourth one as the usage error it is (11 §Exit codes' 2)
    rather than sending it and reading a 422 back. The other four
    statuses are the engine's record of what happened and are not an
    operator's to declare, which is why they are not here.
    """

    ready = "ready"
    cancelled = "cancelled"
    dead_letter = "dead_letter"


#: What ``position`` sends for each of its two words: ``-1`` is the
#: neighbour above, ``1`` the one below (D57).
_DIRECTIONS: Final[Mapping[str, int]] = {"up": -1, "down": 1}

#: The fields of a `RequestView` worth printing when the operator is not
#: asking for JSON. The whole view carries the prompt, the schema and the
#: tool call, which are what they were *asked*; this is the answer.
REQUEST: Final[tuple[str, ...]] = (
    "id",
    "run_id",
    "node",
    "mode",
    "pending",
    "answer",
    "answered_by",
)

#: The fields of a `RunDetail` an edit is about. `edit --json` still
#: prints the whole detail the API returned.
_RUN: Final[tuple[str, ...]] = ("id", "workflow", "status", "title", "description")


def _emit(options: Options, data: Any, keys: Sequence[str] | None = None) -> None:
    """Print the API's answer: whole for ``--json``, ``keys`` otherwise.

    A ``RequestView`` and a ``RunDetail`` are large and most of what they
    carry did not change; a person wants the part that did. ``--json``
    still gets the response exactly as it arrived, because that is the
    wire contract and a script reads it (11).
    """

    if options.json:
        emit(data, json_flag=True)
        return
    if not isinstance(data, Mapping):
        emit(data)
        return
    wanted = data.keys() if keys is None else keys
    # A field the server sent as null is omitted rather than printed as a
    # blank: `note` on an `Ok` and `answer` on an unanswered request are
    # both "there is nothing to say", and 01 §Real data only says nothing
    # rather than something empty.
    emit({key: data[key] for key in wanted if data.get(key) is not None})


def _mapping(value: Any) -> Mapping[str, Any]:
    """``value`` as the object the API documents it to be."""

    return value if isinstance(value, Mapping) else {}


# --------------------------------------------------------------------------
# Answering a request
# --------------------------------------------------------------------------


def _json_object(text: str) -> dict[str, Any] | None:
    """``text`` as a JSON object, or ``None`` if it is not one.

    An *object*, not any JSON value: ``42`` and ``true`` are perfectly
    good answers to a text question and would be silently retyped by a
    parser that accepted whatever parsed.
    """

    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _answer_body(mode: str, text: str) -> dict[str, Any]:
    """The body 08 §Requests wants for one answer, by the request's mode.

    The resolution order of 17 §T054a, with the mode deciding which rule
    can apply at all — which is what stops an operator answering
    ``{"ok": true}`` to a *text* question from sending a dict, and is the
    only reading under which a text answer that happens to look like JSON
    still reaches the node as the string that was typed:

    - ``form`` — the argument is JSON, and must parse as an object. One
      that does not is sent as it stands, so the refusal the operator
      reads is the server's ("its answer must be an object") rather than
      a second opinion from here;
    - ``options`` — the argument is an option id, and the server refuses
      one the request does not offer;
    - ``text`` — the argument, verbatim.
    """

    if mode == "form":
        parsed = _json_object(text)
        if parsed is not None:
            return {"value": parsed}
    if mode == "options":
        return {"option_id": text}
    return {"value": text}


def _request(client: Client, request_id: int) -> Mapping[str, Any]:
    """The request being answered, read before anything is sent."""

    return _mapping(client.get(f"/api/requests/{request_id}"))


@app.command()
def answer(
    ctx: typer.Context,
    request_id: Annotated[int, typer.Argument(metavar="REQ", help="The request id.")],
    words: Annotated[
        list[str],
        typer.Argument(
            metavar="ANSWER",
            help="An option id, the text, or the JSON object for a form.",
        ),
    ],
) -> None:
    """Answer a request: an option id, some text, or a JSON object.

    The words are joined with single spaces, so a sentence needs no
    quoting; quote it anyway if the spacing matters.
    """

    options = Options.of(ctx)
    text = " ".join(words)
    with options.client() as client:
        view = _request(client, request_id)
        body = _answer_body(str(view.get("mode", "")), text)
        answered = client.post(f"/api/requests/{request_id}/answer", body)
    _emit(options, answered, REQUEST)


def _pick(client: Client, request_id: int, kinds: Sequence[str], verb: str) -> str:
    """The option id ``verb`` means for this request, chosen by kind.

    ``kinds`` is a preference and not a filter: the search is over the
    wanted kinds and then over the options, so the agent's list order
    cannot turn a ``permit`` into a denial (20 §Finding 1). A request
    that is not an ``options`` request, or that offers nothing of a
    wanted kind, is the one refusal in this module the server has no
    equivalent of, so it is worded here.
    """

    view = _request(client, request_id)
    mode = view.get("mode")
    if mode != "options":
        fail(
            f"request {request_id} is a `{mode}` request, so there is nothing "
            f"to {verb}; `athanore answer {request_id} <answer>` answers it."
        )
        raise typer.Exit(EXIT_API_ERROR)
    offered = [
        option for option in view.get("options") or [] if isinstance(option, dict)
    ]
    for kind in kinds:
        for option in offered:
            if option.get("kind") == kind:
                return str(option["option_id"])
    ids = ", ".join(str(option.get("option_id")) for option in offered)
    fail(
        f"request {request_id} offers no option of kind {' or '.join(kinds)}, "
        f"so `{verb}` cannot pick one; it offers {ids or '(none)'} — "
        f"`athanore answer {request_id} <option-id>` picks one by hand."
    )
    raise typer.Exit(EXIT_API_ERROR)


def _decide(
    ctx: typer.Context,
    request_id: int,
    option: str | None,
    kinds: Sequence[str],
    verb: str,
) -> None:
    """``permit`` and ``deny``: the same call under two preference orders."""

    options = Options.of(ctx)
    with options.client() as client:
        # An explicit id is sent as it stands: the server owns the list
        # of what this request offers and refuses an id that is not on
        # it, with the message that names the ones that are.
        chosen = (
            option if option is not None else _pick(client, request_id, kinds, verb)
        )
        answered = client.post(
            f"/api/requests/{request_id}/answer", {"option_id": chosen}
        )
    _emit(options, answered, REQUEST)


@app.command()
def permit(
    ctx: typer.Context,
    request_id: Annotated[int, typer.Argument(metavar="REQ", help="The request id.")],
    option: Annotated[
        str | None,
        typer.Argument(
            help="The option id to answer with; picked by kind without one."
        ),
    ] = None,
) -> None:
    """Allow what a permission request is asking to do."""

    from athanore.agents.policies import ALLOW_KINDS

    _decide(ctx, request_id, option, ALLOW_KINDS, "permit")


@app.command()
def deny(
    ctx: typer.Context,
    request_id: Annotated[int, typer.Argument(metavar="REQ", help="The request id.")],
) -> None:
    """Refuse what a permission request is asking to do."""

    from athanore.agents.policies import REJECT_KINDS

    _decide(ctx, request_id, None, REJECT_KINDS, "deny")


# --------------------------------------------------------------------------
# Steering a run
# --------------------------------------------------------------------------


def _run_verb(ctx: typer.Context, run: str, verb: str) -> None:
    """``POST /api/runs/{id}/<verb>``, and print what came back."""

    options = Options.of(ctx)
    with options.client() as client:
        result = client.post(f"/api/runs/{run}/{verb}")
    _emit(options, result)


@app.command()
def pause(
    ctx: typer.Context, run: Annotated[str, typer.Argument(help="The run id.")]
) -> None:
    """Stop a run dispatching; an attempt already in flight finishes."""

    _run_verb(ctx, run, "pause")


@app.command()
def resume(
    ctx: typer.Context, run: Annotated[str, typer.Argument(help="The run id.")]
) -> None:
    """Let a paused run dispatch again."""

    _run_verb(ctx, run, "resume")


@app.command()
def cancel(
    ctx: typer.Context, run: Annotated[str, typer.Argument(help="The run id.")]
) -> None:
    """End a run and every attempt still outstanding under it."""

    _run_verb(ctx, run, "cancel")


@app.command()
def rm(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask; for a script.")
    ] = False,
) -> None:
    """Delete a run and everything stored under it.

    The prompt is not ceremony: deleting a run takes its attempts, its
    events, its work log and its agent transcripts with it, and none of
    that is recoverable from another server (07 §Retention).
    """

    options = Options.of(ctx)
    if not yes:
        typer.confirm(f"Delete run {run} and everything stored under it?", abort=True)
    with options.client() as client:
        # 204 and an empty body: there is no API shape to pass through,
        # so what is printed is what was deleted.
        client.delete(f"/api/runs/{run}")
    _emit(options, {"deleted": run})


@app.command()
def rerun(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
    node: Annotated[str, typer.Argument(help="The node to run again.")],
) -> None:
    """Queue a fresh attempt of a node, with the payload it last had."""

    options = Options.of(ctx)
    with options.client() as client:
        queued = client.post(f"/api/runs/{run}/rerun", {"node": node})
    _emit(options, queued)


@app.command()
def edit(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
    title: Annotated[str | None, typer.Option("--title", help="The new title.")] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="The new description.")
    ] = None,
) -> None:
    """Change a run's title, its description, or both.

    A field not named is left alone, which is why an edit that names
    neither is accepted and changes nothing: an edit is not the place to
    refuse a caller for being redundant.
    """

    options = Options.of(ctx)
    body = {
        key: value
        for key, value in (("title", title), ("description", description))
        if value is not None
    }
    with options.client() as client:
        detail = client.patch(f"/api/runs/{run}", body)
    _emit(options, detail, _RUN)


@app.command()
def position(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
    where: Annotated[
        str,
        typer.Argument(
            metavar="up|down|INDEX",
            help="Swap with a neighbour, or move to a zero-based index.",
        ),
    ],
) -> None:
    """Move a run in the dispatch list (D57).

    ``up`` and ``down`` swap with a neighbour and are a no-op at the
    ends; an index is **zero-based** and clamped to the list, so ``0`` is
    the top and there is nothing to bounds-check.
    """

    options = Options.of(ctx)
    if where in _DIRECTIONS:
        body: dict[str, Any] = {"direction": _DIRECTIONS[where]}
    else:
        try:
            body = {"index": int(where)}
        except ValueError:
            raise typer.BadParameter(
                f"{where!r} is not `up`, `down` or a list index."
            ) from None
    with options.client() as client:
        moved = client.post(f"/api/runs/{run}/position", body)
    _emit(options, moved)


# --------------------------------------------------------------------------
# Steering a task
# --------------------------------------------------------------------------


@app.command()
def retry(
    ctx: typer.Context,
    task: Annotated[int, typer.Argument(help="The task id.")],
) -> None:
    """Queue another attempt of a task that has stopped."""

    options = Options.of(ctx)
    with options.client() as client:
        queued = client.post(f"/api/tasks/{task}/retry")
    _emit(options, queued)


@app.command()
def move(
    ctx: typer.Context,
    task: Annotated[int, typer.Argument(help="The task id.")],
    node: Annotated[str, typer.Argument(help="The node to enqueue the work at.")],
) -> None:
    """Move a task's work to another node, cancelling the attempt it left."""

    options = Options.of(ctx)
    with options.client() as client:
        moved = client.post(f"/api/tasks/{task}/move", {"node": node})
    _emit(options, moved)


@app.command("set-status")
def set_status(
    ctx: typer.Context,
    task: Annotated[int, typer.Argument(help="The task id.")],
    status: Annotated[
        SettableStatus,
        typer.Argument(
            help="`ready` re-dispatches, `cancelled` stops, `dead_letter` "
            "files it as failed for good."
        ),
    ],
) -> None:
    """Write one of the three statuses an operator may set on a task."""

    options = Options.of(ctx)
    with options.client() as client:
        result = client.post(f"/api/tasks/{task}/status", {"status": status.value})
    _emit(options, result)
