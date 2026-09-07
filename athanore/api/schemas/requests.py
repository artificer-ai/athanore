"""A request for a human, on the wire (08 §Requests).

One model, because a request and its answer are one thing to everybody
who reads them: the inbox, a run's request list, the panel that answers
one, and the response to answering it are all this shape. The three
derived fields are what the join produces —

- ``pending`` — unanswered, and its task is still ``in_progress`` or
  ``waiting``, so somebody is actually waiting for the answer;
- ``stale`` — unanswered, and its task is not: the attempt that asked is
  gone, so nothing will consume an answer. It stays in history and leaves
  the inbox (06 §Restart durability), which is why the SPA needs to tell
  the two apart rather than reading "not pending";
- ``age`` — seconds since ``created``, measured when the view was read.

``answered_by`` is the field to test for "has an answer at all", because
``answer`` may legitimately be ``null``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from athanore.store import rows

__all__ = ["RequestOption", "RequestView"]


class RequestOption(BaseModel):
    """One choice an ``options`` request offers (06 §The model).

    The agent's options verbatim for an ACP permission: the operator
    picks under the labels the agent used, and the ``option_id`` that
    goes back is the one it will be given (05 §Policies).
    """

    option_id: str = Field(description="The id an answer names.")
    name: str = Field(description="What to show the operator.")
    kind: str | None = Field(
        default=None,
        description="The ACP permission kind, when the option came from one.",
    )


class RequestView(BaseModel):
    """A request, its answer, and the node that asked (08 §Requests).

    ``schema`` is spelled ``schema_`` in Python — a field named ``schema``
    shadows an attribute of ``BaseModel`` — and keeps ``schema`` as its
    alias, which is the name 08 fixes on the wire.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int = Field(description="The request id.")
    run_id: str = Field(description="The run it belongs to.")
    task_id: int = Field(description="The attempt that asked.")
    node: str = Field(description="The node that attempt runs.")
    prompt: str = Field(description="What the operator is being asked.")
    mode: rows.RequestMode = Field(description="The shape of the answer expected.")
    source: rows.RequestSource = Field(
        description="Whether the agent asked mid-turn or the node body did."
    )
    kind: rows.RequestKind = Field(description="What the request is about; a label.")
    options: list[RequestOption] | None = Field(
        default=None, description="The choices, for an `options` request."
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        validation_alias="schema",
        serialization_alias="schema",
        description="The JSON Schema the answer must fit, for a `form` request.",
    )
    tool_call: dict[str, Any] | None = Field(
        default=None,
        description="What the agent was about to do, for a permission request.",
    )
    pending: bool = Field(description="Unanswered, with an attempt still waiting.")
    stale: bool = Field(
        description="Unanswered, with no attempt left to consume an answer: in "
        "history, out of the inbox, and no longer answerable."
    )
    answer: Any = Field(
        default=None,
        description="The chosen `option_id`, or the value of a `text` or `form` "
        "answer. Null both before an answer and for an answer that was null.",
    )
    answered_by: rows.AnswerAuthor | None = Field(
        default=None,
        description="Who answered; the field to test for having an answer at all.",
    )
    created: datetime = Field(description="When the request was opened.")
    age: float = Field(description="Seconds since it was opened, when it was read.")

    @classmethod
    def of(cls, view: rows.RequestView) -> RequestView:
        """The wire view of one joined request."""

        return cls(
            id=view.id,
            run_id=view.run_id,
            task_id=view.task_id,
            node=view.node,
            prompt=view.prompt,
            mode=view.mode,
            source=view.source,
            kind=view.kind,
            options=(
                None
                if view.options is None
                else [RequestOption.model_validate(one) for one in view.options]
            ),
            schema_=view.schema_,
            tool_call=view.tool_call,
            pending=view.pending,
            stale=view.stale,
            answer=view.answer,
            answered_by=view.answered_by,
            created=view.created,
            age=view.age,
        )
