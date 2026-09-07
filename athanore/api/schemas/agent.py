"""What an agent sends and is sent (08 §Agent-facing).

Its own module for the same reason the routes have their own router: the
agent surface is not the operator surface with a different credential.
The MVP overloaded ``/api/tasks/{id}`` and picked the response shape by
who was asking, which cannot be said in OpenAPI without ``oneOf`` tricks
(D39); here the four models below are the whole of what a task token can
see, and none of them has a field a token could sit in.

Two of them are worth reading twice.

:class:`AgentTask` is the agent's first call and the only read it makes.
Its ``log`` is the run's work log with the ``stats`` entries dropped
(D56): token counts and costs are operator information and an agent
reading its own back learns nothing it can act on. ``output_schema`` is
present only while a façade has declared an ``output_model`` on the live
context — the ``native`` tier fetches it to build its ``submit_result``
tool (05 §Tooling tiers) — and absent, rather than null-shaped, when no
model is declared.

:class:`Ask` is the one body with a choice in it: ``options`` **or**
``schema``, never both, and neither means a ``text`` question. That is
what decides the request's mode, so the mode is a consequence of the body
rather than a fourth field a caller could contradict itself with.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from athanore.api.schemas.runs import LogEntry
from athanore.store import rows

__all__ = ["AgentTask", "AnswerPoll", "Ask", "AskOption", "AskOut"]


class AgentTask(BaseModel):
    """One attempt as the agent running it sees it (08 §Agent-facing).

    The identity of the attempt, the run's title and description, the
    payload the node was called with, and the work log that is the
    inter-stage channel (D4). Everything an agent needs to start, and
    nothing an operator route would add.
    """

    task_id: int = Field(description="This attempt's id; the one the token is for.")
    run_id: str = Field(description="The run the attempt belongs to.")
    workflow: str = Field(description="The workflow being run.")
    node: str = Field(description="The node this attempt executes.")
    attempt: int = Field(description="Which attempt of this node this is, from 1.")
    title: str = Field(description="The operator's title for the run.")
    description: str = Field(description="The operator's longer brief for the run.")
    input: Any = Field(
        default=None,
        description="The payload the node was enqueued with; null when it had none.",
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        description="The JSON Schema a submission must fit, when the agent "
        "façade running this attempt declared an `output_model`.",
    )
    log: list[LogEntry] = Field(
        description="The run's work log, oldest first and never truncated, "
        "without the `stats` entries."
    )


class AskOption(BaseModel):
    """One choice an agent offers the operator (08 §Agent-facing).

    ``option_id`` is what an answer names and what comes back from the
    long-poll; ``name`` is what the operator is shown and defaults to the
    id, which is what a bare string in ``options`` is short for.
    """

    option_id: str = Field(min_length=1, description="The id an answer names.")
    name: str | None = Field(
        default=None,
        description="What to show the operator; the `option_id` when omitted.",
    )
    kind: str | None = Field(
        default=None, description="A label for the option; carried through as given."
    )


class Ask(BaseModel):
    """A question an agent puts to the operator (`POST …/ask`, 06).

    ``schema`` is spelled ``schema_`` in Python, as it is in
    :class:`~athanore.api.schemas.requests.RequestView`, and keeps
    ``schema`` as its alias — the name 08 and the curl line of 19 fix on
    the wire.
    """

    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(
        min_length=1, description="The question, as the operator will read it."
    )
    options: list[str | AskOption] | None = Field(
        default=None,
        description="The choices, for a pick-one question. A bare string is "
        "an option that is its own id and label.",
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        validation_alias="schema",
        serialization_alias="schema",
        description="A JSON Schema the answer must fit, for a form question.",
    )

    @model_validator(mode="after")
    def _one_shape(self) -> Ask:
        """``options`` or ``schema``, and an empty ``options`` is neither.

        A body carrying both asks for two different answers to one
        question, and a body carrying an empty list asks a pick-one
        question that offers nothing to pick — which
        :meth:`~athanore.requests.service.RequestService.create` refuses
        anyway (D115). Both are the caller's mistake, and the body is
        where a caller can see it.
        """

        if not self.prompt.strip():
            raise ValueError("`prompt` may not be blank")
        if self.options is not None and self.schema_ is not None:
            raise ValueError("give `options` or `schema`, not both")
        if self.options is not None and not self.options:
            raise ValueError("`options` may not be empty")
        return self

    @property
    def mode(self) -> rows.RequestMode:
        """The mode this body asks for: what was given decides it."""

        if self.options is not None:
            return rows.RequestMode.options
        if self.schema_ is not None:
            return rows.RequestMode.form
        return rows.RequestMode.text

    def option_dicts(self) -> list[dict[str, Any]] | None:
        """The options as a request row carries them: `{option_id, name, kind}`.

        The three keys 06 §The model fixes, which is the shape
        ``athanore.agents.policies`` writes for an ACP permission and the
        shape ``RequestService.answer`` checks an ``option_id`` against.
        """

        if self.options is None:
            return None
        return [
            {"option_id": one, "name": one, "kind": None}
            if isinstance(one, str)
            else {
                "option_id": one.option_id,
                "name": one.name if one.name is not None else one.option_id,
                "kind": one.kind,
            }
            for one in self.options
        ]


class AskOut(BaseModel):
    """The request an ask opened (08 §Agent-facing).

    ``mode`` is reported back because the agent did not choose it
    directly: it sent options, a schema or neither, and this is what that
    was read as — which is also what tells it what shape of answer to
    expect from the long-poll.
    """

    request_id: int = Field(description="The id to poll for an answer.")
    mode: rows.RequestMode = Field(description="The shape of the answer expected.")


class AnswerPoll(BaseModel):
    """The result of one long-poll (`GET …/requests/{rid}`, 06 §Surfaces).

    ``answered`` is the field to branch on. Until it is true the other
    two are absent, because a request with no answer has no author
    either; once it is true ``answer`` is the chosen ``option_id`` of an
    ``options`` request and the value of a ``text`` or ``form`` one —
    the same folding :class:`~athanore.store.rows.RequestView` does, so
    an operator reading the request and the agent reading its answer see
    the same value.

    Re-delivery is idempotent: nothing is claimed by a poll, so an agent
    that lost a response and asked again gets the same answer again.
    """

    request_id: int = Field(description="The request that was polled.")
    answered: bool = Field(description="Whether an answer has been recorded.")
    answer: Any = Field(
        default=None,
        description="The chosen `option_id`, or the value of a `text` or `form` "
        "answer. Null before an answer, and for an answer that was null.",
    )
    answered_by: rows.AnswerAuthor | None = Field(
        default=None,
        description="Who answered: the operator, or the engine on a headless "
        "fallback. Null until answered.",
    )
