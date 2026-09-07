"""The graph of one run: a node's state, and the edges between them (08 §Graph).

Not the workflow's shape — that is :class:`~athanore.api.schemas.workflows.
WorkflowOut` — but the shape *with this run's history projected onto it*,
which is what the SPA's graph pane draws.

The one thing worth stating here rather than in the router is what
:class:`NodeState` is. A node in a run has as many states as it has
attempts, and two of them can be true at once: an attempt that failed and
a retry that is ``ready`` are both facts about the same node. 08 §Graph
semantics fixes a precedence — first match wins — and this enum is that
list in its order, so the value a node reports is the one the operator
should see rather than whichever row was read last.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Arrivals",
    "EdgeKind",
    "GraphBranch",
    "GraphEdge",
    "GraphNode",
    "GraphOut",
    "NodeState",
]


class NodeState(StrEnum):
    """What a node is doing in one run, in 08 §Graph semantics' precedence.

    Declared in precedence order, highest first, so the rule is the
    member order and not a table kept somewhere else. ``failed`` outranks
    ``done`` but is itself outranked by ``ready``: a failed attempt whose
    retry is queued reports ``ready``, because that retry row exists and
    the node is going to run again. ``idle`` means no task of this node
    was ever created in this run.

    The SPA colours by this alone (10 §Status colours).
    """

    in_progress = "in_progress"
    waiting = "waiting"
    ready = "ready"
    dead_letter = "dead_letter"
    failed = "failed"
    done = "done"
    cancelled = "cancelled"
    idle = "idle"


class EdgeKind(StrEnum):
    """What kind of edge one node's arrow to another is (08 §Graph semantics)."""

    #: A step forward: the target's generation is above the source's.
    forward = "forward"
    #: A loop back: the target's generation is at or below the source's.
    back = "back"
    #: An arrow into a join node, traversed by arrivals rather than
    #: transitions. The member shadows ``str.join`` on this class, which
    #: nothing calls on an edge kind; 08 fixes the value, and naming the
    #: member anything else would put two spellings of one word in the
    #: codebase.
    join = "join"  # pyright: ignore[reportAssignmentType]


class GraphBranch(BaseModel):
    """The tasks of one node that belong to one branch of a fan-out.

    ``from_task`` is the fan-out that produced the branch — the
    ``lineage.from`` of the first task in the branch chain whose parent
    returned a list — and is ``null`` for a node reached by a single path,
    which has exactly one branch.
    """

    from_task: int | None = Field(
        default=None, description="The fan-out task this branch came out of."
    )
    tasks: list[int] = Field(
        default_factory=list,
        description="This node's attempts in that branch, oldest first.",
    )


class Arrivals(BaseModel):
    """How much of an open fan-out has reached a join (04 §Fan-in).

    The innermost pending fan-out, which is the one the operator is
    waiting on; the SPA renders it as `2 of 3 arrived` (10 §Graph pane).
    """

    arrived: int = Field(description="Branches that have reached the join.")
    count: int = Field(description="Branches the fan-out opened.")


class GraphNode(BaseModel):
    """One node of the graph, with this run's history on it."""

    name: str = Field(description="The node's name.")
    generation: int = Field(description="BFS depth from the start node.")
    join: bool = Field(description="Whether the node waits for a fan-out to complete.")
    state: NodeState = Field(description="What the node is doing, by 08's precedence.")
    live: bool = Field(
        description="Whether a `node`-slot plugin panel should show: the node is "
        "in progress or waiting, or it has at least one done attempt (09 §Slots)."
    )
    attempts: int = Field(description="How many task rows this node has in this run.")
    last_task_id: int | None = Field(
        default=None,
        description="The highest task id of the node, the one the task drawer "
        "opens; null when the node has no task.",
    )
    branches: list[GraphBranch] = Field(
        default_factory=list,
        description="The node's tasks grouped by the fan-out that produced them.",
    )
    arrivals: Arrivals | None = Field(
        default=None,
        description="For a join with a fan-out still open, how much of it has "
        "arrived; absent otherwise.",
    )


class GraphEdge(BaseModel):
    """One arrow of the finalized graph, and how often this run took it.

    ``from`` is a Python keyword, so the field is ``from_`` and carries
    ``from`` as its alias — the name 08 fixes on the wire.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(
        validation_alias="from",
        serialization_alias="from",
        description="The node the arrow leaves.",
    )
    to: str = Field(description="The node it points at.")
    kind: EdgeKind = Field(description="Forward, a loop back, or an arrow into a join.")
    traversed: int = Field(
        description="How often this run took the edge: `task.enqueued "
        "reason=transition` between the two nodes, plus `join.arrived` for a "
        "join edge."
    )


class GraphOut(BaseModel):
    """The graph of one run (08 §Runs, `/graph`)."""

    nodes: list[GraphNode] = Field(description="Every node of the workflow.")
    edges: list[GraphEdge] = Field(description="Every edge of the finalized graph.")
