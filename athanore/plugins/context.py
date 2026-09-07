"""What a plugin handler is handed, and what its scope entitles it to.

09 §Context and scopes. :class:`PluginContext` is the one argument every
route, action and ``on`` handler takes: the ids the caller supplied, the
rows they resolve to, the narrow services a node body gets, and the
operator operations. It is built by :class:`PluginHost`, which is the
only thing here that knows about the store and the engine.

Two rules make the object trustworthy:

**Nothing is partially resolved.** A ``run_id`` that does not exist, or
that exists and belongs to another workflow, is a 404 *before* the
handler runs (09 §Declarations: "scope follows ownership"). A handler
therefore never has to ask whether the run it was given is really its
own, and a plugin cannot reach another workflow's runs (12 §Plugins).

**A service the scope cannot have raises rather than returns.** In a
``workflow`` or ``global`` context there is no run, so ``services.log``,
``stream``, ``submissions`` and ``requests`` raise
``PluginError(400, "no run in scope")`` where they are reached for.
``services.run.list()``, ``services.events.publish`` and ``ops`` — which
take explicit ids — work. Returning ``None`` instead would move the
failure to whatever the handler did with it next, which is the one place
the author cannot read it.

``services.run.list()`` is scoped too: it lists **this workflow's** runs.
An unscoped list would be the reach across workflows the manifest and the
404 above are there to prevent.

``services.run`` is also where a pane *reads* a run: :meth:`detail`,
:meth:`log_entries` and :meth:`events` answer the three questions a run
pane asks — what did the attempts cost, what is in the work log, and
what happened. They are the run in scope and nothing wider, so they
carry the same ownership the 404 above establishes (D140).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

from athanore.engine.services import (
    EventPort,
    LogService,
    RequestBackend,
    RequestsPort,
    StreamService,
    SubmissionService,
    TaskRequests,
    UnwiredRequests,
)
from athanore.plugins.decl import PluginError
from athanore.plugins.registry import BUILTIN_WORKFLOW
from athanore.store.rows import (
    EventRow,
    LogEntryRow,
    RunRow,
    RunStats,
    RunSummary,
    TaskRow,
)
from athanore.store.uow import Store

if TYPE_CHECKING:  # pragma: no cover - imported for types only
    from fastapi import FastAPI

    from athanore.engine import Engine
    from athanore.engine.ops import Ops

__all__ = [
    "NO_RUN",
    "NO_TASK",
    "PluginContext",
    "PluginHost",
    "PluginRuns",
    "PluginServices",
    "RunDetailRows",
    "owns_run",
]

#: What a run-scoped service says in a context that has no run. 09 fixes
#: the wording, so the SPA and the CLI can recognise it.
NO_RUN = "no run in scope"

#: The same refusal one level in: a run is in scope but no task is, and
#: the work log, the transcript and the submissions all belong to an
#: attempt rather than to a run.
NO_TASK = "no task in scope"


class RunDetailRows(NamedTuple):
    """A run, its every attempt, and the totals of their stats entries.

    What :meth:`PluginRuns.detail` answers with, and the same three
    values ``RunRepo.detail`` returns — so a pane that totals a run and
    ``GET /api/runs/{id}`` read the same numbers out of the same query
    rather than summing them twice and disagreeing.
    """

    run: RunRow
    tasks: list[TaskRow]
    stats: RunStats


class PluginRuns:
    """The runs a plugin may see: its own workflow's.

    :meth:`get` is the run in scope and refuses when there is none;
    :meth:`list` works in every scope, which is what a ``global`` pane
    showing "everything queued" needs (09 §Context and scopes), and is
    filtered to this workflow so a plugin cannot enumerate another's.

    :meth:`detail`, :meth:`log_entries` and :meth:`events` are the reads
    a pane makes *about* the run in scope: its attempts and totals, its
    work log, and its history. They are run-scoped like :meth:`get` and
    refuse the same way, and they are here rather than anywhere narrower
    because a pane that draws a run is the most ordinary plugin there is
    — the builtin overview and log panes are written against exactly
    these three and get no more than any other plugin does (D140).

    The builtin scope (``_builtin``) is the exception on both counts: its
    panels apply to every run, so its list is every run.
    """

    def __init__(self, store: Store, *, workflow: str, run_id: str | None) -> None:
        self._store = store
        self._workflow = workflow
        self._run_id = run_id

    async def get(self) -> RunRow:
        """The run this context is scoped to, freshly read."""

        if self._run_id is None:
            raise PluginError(400, NO_RUN)
        async with self._store.reader() as reader:
            row = await reader.runs.get(self._run_id)
        if row is None:
            raise PluginError(404, f"run {self._run_id!r} no longer exists")
        return row

    async def list(self, status: str | None = None) -> list[RunSummary]:
        """This workflow's runs, in list order (07 §Repositories)."""

        workflow = None if self._workflow == BUILTIN_WORKFLOW else self._workflow
        async with self._store.reader() as reader:
            return await reader.runs.list(status=status, workflow=workflow)

    async def detail(self) -> RunDetailRows:
        """The run in scope, its attempts, and their summed stats.

        One read, and the same one ``GET /api/runs/{id}`` makes: the
        totals span every attempt, failed ones included, because the
        tokens a dead-lettered attempt spent were still spent (05 §Stats
        entry).
        """

        run_id = self._run_id
        if run_id is None:
            raise PluginError(400, NO_RUN)
        async with self._store.reader() as reader:
            detail = await reader.runs.detail(run_id)
        if detail is None:
            raise PluginError(404, f"run {run_id!r} no longer exists")
        run, tasks, stats = detail
        return RunDetailRows(run, tasks, stats)

    async def log_entries(
        self, after: int = 0, limit: int | None = None
    ) -> list[LogEntryRow]:
        """The work log of the run in scope, oldest first (03 §LogEntry).

        The whole run's, not one attempt's: ``services.log`` is the
        attempt's *append*, and a pane that draws the log draws all of
        it. Returned whole because a run's log is bounded by the number
        of stages (08 §Agent-facing).
        """

        if self._run_id is None:
            raise PluginError(400, NO_RUN)
        async with self._store.reader() as reader:
            return await reader.log.list(self._run_id, after=after, limit=limit)

    async def events(self, after: int = 0, limit: int | None = None) -> list[EventRow]:
        """The stored events of the run in scope, oldest first (03).

        The run's history as the audit trail kept it, which is what a
        pane needs to show what happened between two log entries.
        ``task.stream`` is never stored, so it never appears here.
        """

        if self._run_id is None:
            raise PluginError(400, NO_RUN)
        async with self._store.reader() as reader:
            return await reader.events.list_for_run(
                self._run_id, after=after, limit=limit
            )


class PluginServices:
    """The narrow store surface of 04, scoped to what the caller asked for.

    The same objects a node body gets — 09 says so in as many words — so
    a plugin route that appends to the work log writes the same row, in
    the same transaction, emitting the same ``log.appended`` as the node
    that ran there. What differs is only that a plugin may be called
    without a run or without a task, and each member says which of the
    two it needs.

    The members are properties rather than attributes so that reaching
    for one out of scope raises where it is reached for, and so that a
    context resolved for a route that touches none of them opens nothing.
    """

    def __init__(
        self,
        store: Store,
        *,
        workflow: str,
        run_id: str | None,
        task_id: int | None,
        node: str | None,
        flush_interval: float,
        requests: RequestBackend | None = None,
    ) -> None:
        self._store = store
        self._workflow = workflow
        self._run_id = run_id
        self._task_id = task_id
        self._node = node
        self._flush_interval = flush_interval
        self._backend = requests
        self._stream: StreamService | None = None

    @property
    def log(self) -> LogService:
        """The work log of the attempt in scope (03 §LogEntry)."""

        run_id, task_id, node = self._attempt()
        return LogService(self._store, run_id=run_id, task_id=task_id, node=node)

    @property
    def stream(self) -> StreamService:
        """The transcript of the attempt in scope (07 §Transcript writes).

        Cached for the life of the context, and closed with it: the
        service starts a background flusher on its first append, and one
        per property read would be one flusher per read.
        """

        run_id, task_id, _ = self._attempt()
        if self._stream is None:
            self._stream = StreamService(
                self._store,
                run_id=run_id,
                task_id=task_id,
                flush_interval=self._flush_interval,
            )
        return self._stream

    @property
    def submissions(self) -> SubmissionService:
        """What the attempt in scope submitted, and the verbs over it (04)."""

        run_id, task_id, node = self._attempt()
        return SubmissionService(self._store, run_id=run_id, task_id=task_id, node=node)

    @property
    def requests(self) -> RequestsPort:
        """The questions the attempt in scope has open (06).

        The port of a host composed without a request service raises on
        every method, exactly as a node body's does: a plugin that could
        not ask anybody anything should say so rather than return an
        empty answer.
        """

        run_id, task_id, _ = self._attempt()
        if self._backend is None:
            return UnwiredRequests()
        return TaskRequests(self._backend, run_id=run_id, task_id=task_id)

    @property
    def run(self) -> PluginRuns:
        """The run in scope, and this workflow's runs."""

        return PluginRuns(self._store, workflow=self._workflow, run_id=self._run_id)

    @property
    def events(self) -> EventPort:
        """Publishing ``plugin.<workflow>.<name>``, and nothing else (18).

        Available in every scope: the ids it stamps on the event are
        whatever the context resolved, and an event published from a
        ``global`` pane carries neither, which is what
        :class:`~athanore.events.model.Event` already allows.
        """

        return EventPort(
            self._store,
            run_id=self._run_id,
            task_id=self._task_id,
            workflow=self._workflow,
        )

    async def aclose(self) -> None:
        """Flush and stop anything this context started. Idempotent."""

        if self._stream is not None:
            await self._stream.close()
            self._stream = None

    def _attempt(self) -> tuple[str, int, str]:
        """The run, task and node of the attempt in scope, or the refusal.

        The node comes with the task — :class:`PluginHost` resolves it
        from the row when the caller did not name one — so a task in
        scope without one is a context nothing built, and the refusal is
        the same one.
        """

        if self._run_id is None:
            raise PluginError(400, NO_RUN)
        if self._task_id is None or self._node is None:
            raise PluginError(400, NO_TASK)
        return self._run_id, self._task_id, self._node


@dataclass
class PluginContext:
    """The one argument a plugin handler takes (09 §Declarations).

    ``run_id`` / ``task_id`` / ``node`` are what the caller asked for,
    resolved: a route reads them from its query parameters, an action
    from the ``scope`` of its body, an ``on`` handler from the event. The
    rows beside them are ``None`` exactly when the id is, because a
    handler is never given an id it could not resolve.

    Explicit ``ctx``, not signature injection: a node's parameters
    already mean edges (09), and one meaning per signature is the whole
    of why the graph reads the way it does.
    """

    workflow: str
    services: PluginServices
    run_id: str | None = None
    task_id: int | None = None
    node: str | None = None
    run: RunRow | None = None
    task: TaskRow | None = None
    _ops: Ops | None = field(default=None, repr=False)

    @property
    def ops(self) -> Ops:
        """The operator operations of 04, unscoped by design.

        Every one of them takes an explicit run or task id, which is why
        09 has them working in a ``global`` context: an action that
        pauses the run it was invoked on and an action that pauses
        another are the same call, and the operator installed the plugin.

        Raises when the application was built without an engine — a
        server that runs no workflows has no operations to offer, and
        that is a wiring failure rather than a refusal of this request.
        """

        if self._ops is None:
            raise PluginError(
                500, "this server has no engine: there are no operations to run"
            )
        return self._ops

    async def aclose(self) -> None:
        """Release what the context opened. Idempotent."""

        await self.services.aclose()


class PluginHost:
    """Where a :class:`PluginContext` is resolved from.

    One object holding the three collaborators a context needs — the
    store, the engine, and the flush interval the transcript writes on —
    so that the FastAPI dependency of :mod:`athanore.plugins.mount` and
    the event dispatcher build contexts the same way. Read off
    ``app.state`` per request rather than closed over, like every other
    collaborator in the API (08 §Endpoints).
    """

    def __init__(
        self,
        store: Store | None,
        engine: Engine | None = None,
        *,
        flush_interval: float = 0.25,
    ) -> None:
        self.store = store
        self.engine = engine
        self.flush_interval = flush_interval

    @classmethod
    def from_app(cls, app: FastAPI) -> PluginHost:
        """The host for an application, from what ``create_app`` put on it."""

        settings = getattr(app.state, "settings", None)
        return cls(
            getattr(app.state, "store", None),
            getattr(app.state, "engine", None),
            flush_interval=(
                settings.stream_flush_interval if settings is not None else 0.25
            ),
        )

    async def context(
        self,
        *,
        workflow: str,
        run_id: str | None = None,
        task_id: int | None = None,
        node: str | None = None,
        strict: bool = True,
    ) -> PluginContext:
        """Resolve the ids into a context, or refuse.

        The refusals are 09's: a run or task that does not exist is a
        404, a run of another workflow is a 404 (never a 403 — whether a
        run exists is not something one workflow's plugin learns about
        another's), and a node the workflow does not have is a 404.

        ``strict=False`` is what the event dispatcher uses: an event
        about a run that has just been deleted still has to reach the
        handler that subscribed to ``run.deleted``, and the row it names
        is already gone. The ownership check still applies to every run
        that *can* be read.
        """

        store = self._store()
        task: TaskRow | None = None
        if task_id is not None:
            task = await self._task(store, task_id, strict=strict)
            if task is not None:
                if run_id is not None and task.run_id != run_id:
                    raise PluginError(
                        404, f"task {task_id} does not belong to run {run_id!r}"
                    )
                run_id = task.run_id

        run: RunRow | None = None
        if run_id is not None:
            run = await self._run(store, run_id, strict=strict)
            if run is not None and not owns_run(workflow, run.workflow):
                raise PluginError(
                    404,
                    f"run {run_id!r} belongs to workflow {run.workflow!r}, "
                    f"not to {workflow!r}",
                )
        if run is None:
            # An unresolved run leaves nothing under it in scope either:
            # a task without its run is exactly the partially-resolved
            # context 09 rules out.
            task, task_id, run_id = None, None, None

        node = self._node(workflow, run, node, task)
        services = PluginServices(
            store,
            workflow=workflow,
            run_id=run.id if run is not None else None,
            task_id=task.id if task is not None else None,
            node=node,
            flush_interval=self.flush_interval,
            requests=self.engine.requests if self.engine is not None else None,
        )
        return PluginContext(
            workflow=workflow,
            services=services,
            run_id=run.id if run is not None else run_id,
            task_id=task.id if task is not None else None,
            node=node,
            run=run,
            task=task,
            _ops=self.engine.ops if self.engine is not None else None,
        )

    async def workflow_of(self, run_id: str) -> str | None:
        """The workflow a run belongs to, or ``None`` if it is gone.

        What the event dispatcher asks once per event, so that a spec
        whose workflow does not own the run is skipped rather than
        refused per handler.
        """

        if self.store is None:
            return None
        async with self.store.reader() as reader:
            row = await reader.runs.get(run_id)
        return row.workflow if row is not None else None

    def _store(self) -> Store:
        """The store, or the wiring failure that says there is none."""

        if self.store is None:
            raise PluginError(
                500, "this server has no store: there is nothing to resolve against"
            )
        return self.store

    async def _run(self, store: Store, run_id: str, *, strict: bool) -> RunRow | None:
        async with store.reader() as reader:
            row = await reader.runs.get(run_id)
        if row is None and strict:
            raise PluginError(404, f"run {run_id!r} does not exist")
        return row

    async def _task(
        self, store: Store, task_id: int, *, strict: bool
    ) -> TaskRow | None:
        async with store.reader() as reader:
            row = await reader.tasks.get(task_id)
        if row is None and strict:
            raise PluginError(404, f"task {task_id} does not exist")
        return row

    def _node(
        self, workflow: str, run: RunRow | None, node: str | None, task: TaskRow | None
    ) -> str | None:
        """The node in scope: the one asked for, or the task's own.

        A named node is checked against the graph of the workflow whose
        run this is — which for the builtin scope is the run's, not
        ``_builtin`` — so a typo is a 404 here rather than a pane that
        never lights up.
        """

        if node is None:
            return task.node if task is not None else None
        owner = run.workflow if run is not None else workflow
        graphs = self.engine.graphs if self.engine is not None else {}
        graph = graphs.get(owner)
        if graph is not None and node not in graph.nodes:
            raise PluginError(
                404, f"workflow {owner!r} has no node {node!r}: {sorted(graph.nodes)}"
            )
        return node


def owns_run(workflow: str, run_workflow: str) -> bool:
    """May a plugin of ``workflow`` see a run of ``run_workflow``?

    Its own, always. Every run, for the builtin scope, whose panels are
    the operator views the core ships and apply to every run there is (09
    §Builtins are plugins).
    """

    return workflow in (run_workflow, BUILTIN_WORKFLOW)
