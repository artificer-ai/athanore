"""The core's own panes, declared through the plugin API (09 §Builtins).

Five modules, one pane each — :mod:`~athanore.plugins.builtin.overview`,
:mod:`~athanore.plugins.builtin.log`,
:mod:`~athanore.plugins.builtin.agent`,
:mod:`~athanore.plugins.builtin.requests` and
:mod:`~athanore.plugins.builtin.graph` — and every one of them declares
what it declares with ``@wf.route`` and ``wf.panel``, reads what it reads
through a :class:`~athanore.plugins.context.PluginContext`, and gets
nothing a workflow's own plugin does not get.

**That is the point.** 09 calls the builtins "the proof the API is
sufficient": the operator views the product ships are the plugin system's
first user, so a pane the core needs and the declaration vocabulary
cannot express is a hole in the vocabulary rather than a reason to
special-case the core. The SPA ships the renderers for the three element
tags below — they are in its bundle, not in a plugin's assets — but their
*placement and liveness* travel through the manifest like anyone else's,
so the host page has no hard-coded knowledge of them.

:class:`BuiltinWorkflow` is the scope they are declared on. It is a
``Workflow`` with no graph: ``_builtin`` is not a registered workflow, no
run has it, and its panels apply to **every** run — which is the one
exception to ownership that :func:`athanore.plugins.context.owns_run` and
:func:`athanore.plugins.mount._in_scope` already make for it.

:func:`builtin_spec` is what a host mounts. Nothing here mounts itself:
``athanore.plugins.builtin`` is an independent sibling of
``athanore.api`` in the top tier (02 §Layering), so the composition root
— :class:`athanore.server.Server`, which imports both — is what puts this
spec in front of the registered workflows' and hands the list to
``create_app``. :func:`athanore.plugins.mount.mount_manifest` is what
keeps it first once it is there.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from athanore.graph import Graph, GraphError
from athanore.plugins.builtin import agent, graph, log, overview, requests
from athanore.plugins.registry import BUILTIN_WORKFLOW, PluginSpec, collect, validate
from athanore.workflow import Workflow

__all__ = [
    "BUILTIN_MODULES",
    "BuiltinWorkflow",
    "builtin_spec",
    "builtin_workflow",
    "with_builtins",
]

F = TypeVar("F", bound=Callable[..., Any])

#: The five builtins, in the order 09 §Builtins are plugins tables them —
#: which is the order their panels appear in the manifest, and therefore
#: the order the SPA cycles the builtin panes in (10 §Panes).
BUILTIN_MODULES: tuple[Callable[[Workflow], None], ...] = (
    overview.declare,
    log.declare,
    agent.declare,
    requests.declare,
    graph.declare,
)

#: The graph of a scope that runs nothing: no nodes, and no start node to
#: name. :func:`athanore.plugins.registry.validate` reads ``nodes`` to
#: check a panel's ``node=``, and no builtin panel names one — a builtin
#: pane is about whatever run is selected, whichever workflow that run
#: belongs to, so there is no graph for it to be node-scoped against.
EMPTY_GRAPH = Graph(name=BUILTIN_WORKFLOW, nodes={}, start="")


class BuiltinWorkflow(Workflow):
    """The scope the core-shipped panes are declared on (09 §Builtins).

    A ``Workflow`` in every way that the registry, the mount and the
    manifest care about, and in no other: it has no nodes, it is never
    registered on the engine, and no run carries its name. What it exists
    for is a ``name`` — ``_builtin``, spelled once in
    :data:`athanore.plugins.registry.BUILTIN_WORKFLOW` — and the four
    declaration verbs, so that the builtins are written with the same API
    a third party writes theirs with.
    """

    def __init__(self) -> None:
        super().__init__(BUILTIN_WORKFLOW)

    def node(
        self,
        *,
        start: bool = False,
        join: bool = False,
        priority: int | None = None,
        retries: int | None = None,
        timeout: float | None = None,
        label: str | None = None,
        description: str | None = None,
    ) -> Callable[[F], F]:
        """Refuse: the builtin scope declares panes, not work.

        ``_builtin`` is not dispatched — it has no runs of its own and
        nothing would ever claim a node declared here. Refusing says so
        where the mistake is made; :meth:`finalize` returns the empty
        graph, so a node accepted quietly would simply vanish.
        """

        raise GraphError(
            f"{BUILTIN_WORKFLOW!r} is the scope the core's own panes are "
            f"declared on, not a workflow: it has no nodes and nothing "
            f"dispatches it"
        )

    def finalize(self) -> Graph:
        """The empty graph, idempotently.

        ``Workflow.finalize`` runs the graph validation of 04, which a
        workflow with no start node fails — correctly, for a workflow.
        This is not one: it is a namespace for declarations, and the
        graph it finalizes to exists only so
        :func:`athanore.plugins.registry.validate` has the ``nodes`` it
        checks a panel's ``node=`` against.

        It is still recorded on the workflow, so the rule that a
        declaration made after ``finalize()`` is refused holds here too.
        """

        self._graph = EMPTY_GRAPH
        return EMPTY_GRAPH


def builtin_workflow() -> BuiltinWorkflow:
    """A fresh :class:`BuiltinWorkflow` with all five builtins declared."""

    workflow = BuiltinWorkflow()
    for declare in BUILTIN_MODULES:
        declare(workflow)
    return workflow


def builtin_spec() -> PluginSpec:
    """The collected, validated spec a host mounts for ``_builtin``.

    Built fresh on every call rather than cached at import: a spec holds
    the handler functions its routes were declared with, and a process
    that built two applications would otherwise mount one application's
    functions on the other's. Declaring five panes costs nothing.

    Validated here, by the same :func:`athanore.plugins.registry.validate`
    a registered workflow's declarations go through, because a builtin
    that broke one of the six checks would be a bug shipped in the core
    rather than one an author made.
    """

    workflow = builtin_workflow()
    spec = collect(workflow)
    validate(spec, workflow.finalize())
    return spec


def with_builtins(specs: Sequence[PluginSpec]) -> list[PluginSpec]:
    """``specs`` with the builtin spec in front (09 §Mounting).

    What a host hands ``create_app(plugins=…)``: the core's own views
    first, then the workflows in registration order.
    """

    return [builtin_spec(), *specs]
