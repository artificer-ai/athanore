"""The pydantic surface of the wire contract (08 §Endpoints, §OpenAPI).

Every request body and every response model the API declares lives under
this package, one module per resource, and every one of them is
re-exported here: a router imports from ``athanore.api.schemas`` and does
not have to know which file a model sits in.

These models are the API's own, not the store's read models with a new
name. The two look alike where 08 and 07 agree, and they are still
separate on purpose:

- the store's models describe **columns**, this package describes the
  **wire**, and the descriptions on these fields are what OpenAPI
  publishes and the generated TypeScript client carries;
- a change to a table is not automatically a change to the contract, and
  the pair of models is what makes the difference visible in review;
- :class:`~athanore.api.schemas.tasks.TaskView` has no ``token_hash``
  field to exclude, which is a stronger guarantee than excluding one (12
  §Task tokens).

There are two exceptions. The event envelope is re-exported from
:mod:`athanore.events.payloads` rather than restated, because 18 §Typing
says so: the payloads sit below the API so the bus and the store can
reach them too (D81). And :class:`athanore.api.schemas.errors.ApiError`
— the error body of 08 §Conventions — is deliberately *not* re-exported,
because it shares a name with the exception in :mod:`athanore.api.errors`
that a router raises: ``ApiError`` imported from here would be the wrong
one nine times out of ten, so the wire model has to be spelled out by
module (D137).
"""

from __future__ import annotations

from athanore.api.schemas.agent import (
    AgentTask,
    AnswerPoll,
    Ask,
    AskOption,
    AskOut,
)
from athanore.api.schemas.bodies import (
    Answer,
    EditRun,
    LogText,
    Move,
    NewRun,
    Position,
    Rerun,
    SetStatus,
)
from athanore.api.schemas.common import Created, LogRef, Ok, TaskRef
from athanore.api.schemas.events import EventEnvelope
from athanore.api.schemas.graph import (
    Arrivals,
    EdgeKind,
    GraphBranch,
    GraphEdge,
    GraphNode,
    GraphOut,
    NodeState,
)
from athanore.api.schemas.requests import RequestOption, RequestView
from athanore.api.schemas.runs import (
    BranchRef,
    LogEntry,
    PositionOut,
    RunDetail,
    RunOutput,
    RunStats,
    RunSummary,
)
from athanore.api.schemas.tasks import (
    BranchFrame,
    StreamChunk,
    StreamOut,
    SubmissionOut,
    TaskDetail,
    TaskView,
)
from athanore.api.schemas.workflows import (
    NodeOut,
    SourceNode,
    SourceOut,
    WorkflowOut,
    WorkflowPlugin,
)

__all__ = [
    "AgentTask",
    "Answer",
    "AnswerPoll",
    "Arrivals",
    "Ask",
    "AskOption",
    "AskOut",
    "BranchFrame",
    "BranchRef",
    "Created",
    "EdgeKind",
    "EditRun",
    "EventEnvelope",
    "GraphBranch",
    "GraphEdge",
    "GraphNode",
    "GraphOut",
    "LogEntry",
    "LogRef",
    "LogText",
    "Move",
    "NewRun",
    "NodeOut",
    "NodeState",
    "Ok",
    "Position",
    "PositionOut",
    "RequestOption",
    "RequestView",
    "Rerun",
    "RunDetail",
    "RunOutput",
    "RunStats",
    "RunSummary",
    "SetStatus",
    "SourceNode",
    "SourceOut",
    "StreamChunk",
    "StreamOut",
    "SubmissionOut",
    "TaskDetail",
    "TaskRef",
    "TaskView",
    "WorkflowOut",
    "WorkflowPlugin",
]
