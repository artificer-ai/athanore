"""The showcase of 09 §Declarations, on a pipeline that really runs.

Three declarations, which are the three 09's example carries: a
``/words`` route, an ``override`` action whose model is its form, and a
``Words`` table pane sourced from the route. They are the worked example
a plugin author copies, so none of them is a stub — the route reads the
run's own work log, the action writes to it through the operator
operations, and the pane refreshes on the event that write emits.

**What a "word" is here.** A game has a name, and the name is the one
thing about a finished game an operator can change cheaply: it is the
title screen and the HUD, not the file on disk. The director records the
name it chose for each branch, the ``override`` action records the name
an operator wants instead, and the ``Words`` pane is the list of both —
so the pane and the action are about the same subject, and the engineer,
who reads the whole work log, is told either way.

**Why the action writes through ``ctx.ops``.** Its scope is ``run``, and
the run-scoped *services* — the work log, the transcript, submissions —
belong to an **attempt** (09 §Context and scopes): reached from a run
with no task in scope they refuse with ``no task in scope``. ``ops`` is
the half of the context that takes explicit ids, so
``ops.append_log(run_id, text)`` is what a run-scoped action has. It
files the entry under the run's in-flight node with author ``user``, and
emits the ``log.appended`` this pane's ``refresh_on`` names — which is
the seam closing on itself: the action does not tell the pane to reload,
the event does.
"""

from __future__ import annotations

from typing import Any

from athanore import PluginContext, PluginError, Workflow
from athanore.plugins.context import NO_RUN
from athanore.store.rows import LogEntryRow

from .models import Override

__all__ = [
    "OVERRIDE_ACTION",
    "WORD",
    "WORD_ARROW",
    "WORD_DASH",
    "WORD_COLUMNS",
    "WORDS_PANEL",
    "WORDS_ROUTE",
    "declare",
    "overridden",
    "word_entry",
    "word_row",
]

#: The prefix of a work-log entry that records a name. Every stage of the
#: pipeline reads the log as prose; this is the one line in it that is
#: also data, so it is written by the *node* and by the action rather
#: than by an agent — a row that depended on a model's phrasing would be
#: a table that empties itself on a bad turn.
WORD = "word:"

#: What separates a name from the file it goes in, on a director's
#: entry, and from the reason, on an operator's. Two separators rather
#: than one because the two halves mean different things and land in
#: different columns; both are spelled with spaces around them, so a
#: game called "Snake II" keeps its name and one called "Snake (2026)"
#: keeps its parenthesis.
WORD_ARROW = " → "
WORD_DASH = " — "

#: The route the ``Words`` pane is sourced from, and the action, and the
#: pane: named here so a test, the manifest and the SPA agree on one
#: spelling of each.
WORDS_ROUTE = "/words"
OVERRIDE_ACTION = "override"
WORDS_PANEL = "Words"

#: The columns of the ``table`` panel, with the column hints of 09. A
#: director's row has a file and no reason and an operator's has the
#: other way round, and each omits the key it has no value for rather
#: than sending an empty string: unknown is absent (01 §Real data only),
#: and the renderer draws the gap.
WORD_COLUMNS: list[dict[str, str]] = [
    {"key": "word", "label": "WORD", "kind": "text"},
    {"key": "file", "label": "FILE", "kind": "text"},
    {"key": "why", "label": "WHY", "kind": "text"},
    {"key": "author", "label": "BY", "kind": "text"},
]


def overridden(workflow: str) -> str:
    """The event the ``override`` action publishes.

    Derived from the workflow's name rather than written out: a plugin
    may publish only in its own ``plugin.<workflow>.`` namespace (18
    §Plugins), and deriving it is what keeps that true of a workflow
    registered under any name.
    """

    return f"plugin.{workflow}.overridden"


def word_entry(word: str, *, file_path: str = "", reason: str = "") -> str:
    """One work-log line recording a name, in the form :func:`word_row` reads.

    ``file_path`` is the director's half — the file the name's game goes
    in — and ``reason`` the operator's. Neither is required, and a line
    carrying neither is still a row.
    """

    line = f"{WORD} {word}"
    if file_path:
        line = f"{line}{WORD_ARROW}{file_path}"
    if reason:
        line = f"{line}{WORD_DASH}{reason}"
    return line


def word_row(entry: LogEntryRow) -> dict[str, Any]:
    """One row of the ``Words`` table, from a work-log entry.

    The inverse of :func:`word_entry`, and deliberately forgiving of the
    half it cannot find: an override has no file, so the row has no
    ``file`` key at all.
    """

    body = entry.text.removeprefix(WORD).strip()
    word, _, file_path = body.partition(WORD_ARROW)
    word, _, why = word.partition(WORD_DASH)
    row: dict[str, Any] = {"word": word.strip(), "author": entry.author.value}
    if file_path.strip():
        row["file"] = file_path.strip()
    if why.strip():
        row["why"] = why.strip()
    return row


def declare(wf: Workflow) -> None:
    """Attach the three declarations of 09 §Declarations to ``wf``.

    A function rather than three calls at import time in
    ``__init__.py``: the graph and the plugin surface are two subjects,
    and the package they belong to keeps them in two modules for the
    same reason :mod:`athanore.workflow` is not :mod:`athanore.graph`.
    """

    @wf.route(WORDS_ROUTE)
    async def words(ctx: PluginContext, limit: int = 50) -> dict[str, Any]:
        """Every name this run's games have been given, oldest first.

        ``limit`` is an ordinary FastAPI parameter — parsed, defaulted
        and documented without this workflow doing anything about it,
        which is 09's "any other parameter follows normal FastAPI
        rules". It caps from the **end**, because the interesting names
        are the recent ones.
        """

        entries = await ctx.services.run.log_entries()
        rows = [word_row(entry) for entry in entries if entry.text.startswith(WORD)]
        return {"columns": WORD_COLUMNS, "rows": rows[-limit:] if limit > 0 else []}

    @wf.action(
        OVERRIDE_ACTION,
        title="Override the game's name",
        scope="run",
        confirm=True,
    )
    async def override(ctx: PluginContext, input: Override) -> dict[str, Any]:
        """Rename the game this run is building, in the work log.

        ``confirm=True`` because it is an instruction to a pipeline that
        may already have written a title screen: the operator is asked
        before it lands, not after.

        The event is published after the entry is written, so a
        subscriber that sees the event can already read the row — and it
        is in this workflow's own namespace, the only one a plugin may
        publish in (18 §Plugins).
        """

        if ctx.run_id is None:  # pragma: no cover - the endpoint refuses first
            # `_in_declared_scope` rejects a `run`-scoped action with no
            # run before the handler is entered (09 §Context and scopes).
            # Stated anyway: it is what makes `run_id` a `str` below, and
            # a handler that read `None` here would write to a run id of
            # "None".
            raise PluginError(400, NO_RUN)
        entry = await ctx.ops.append_log(
            ctx.run_id, word_entry(input.word, reason=input.reason)
        )
        await ctx.services.events.publish(
            overridden(ctx.workflow),
            {"word": input.word, "reason": input.reason, "entry_id": entry.id},
        )
        return {"entry_id": entry.id, "word": input.word, "node": entry.node}

    wf.panel(
        WORDS_PANEL,
        slot="run",
        kind="table",
        source=words,
        refresh_on=["log.appended"],
    )
