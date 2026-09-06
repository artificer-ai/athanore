"""What happens when an agent asks for permission, or asks a question.

05 §Policies is the specification and 20 §Finding 1 is the bug behind
half of it. Two things arrive from inside an agent's turn and neither is
an answer the agent may give itself: a **permission request** for a tool
call it is about to make, and an **elicitation** — a form it wants a
person to fill in. This module is the policy that resolves both, either
headlessly from the agent's own configuration or by opening a request on
the channel of 06 and blocking the turn until somebody answers it.

**Selection is by ``kind``, never by index.** ACP's
``PermissionOption.kind`` carries the semantics and the list order is
unspecified; ``claude-agent-acp`` lists rejection *first*, so the MVP's
``options[0]`` "auto-approve" denied every tool call and reported the run
``ok`` (20 §Finding 1, D10). :func:`choose_by_kind` is the one place an
option is picked, it takes the kinds it wants in preference order, and
``*_once`` comes before ``*_always`` in both directions: in that adapter
``allow_always`` installs a whole-tool session rule that silently
disables per-call policy for the rest of the run.

**A policy that cannot be honoured fails loudly.** An agent that offers
no option of the wanted kind gets an :exc:`~athanore.agents.base.AgentError`
rather than a quiet fallback to whatever it did offer — failing beats
reporting success, which is exactly what the MVP did.

**An agent may never widen its own policy.** Everything here reads the
façade's configuration and the answer of a person; nothing reads the
agent's turn. The only degradation is downward and it is announced:
``ask`` **outside a task context** — a façade used standalone, with no
task to open a request against — warns and falls back to ``auto_allow``,
because there is nobody to escalate to and, where that happens, the
container is the guardrail (05 §User-land adapters).

**The tool-call summary is bounded.** A permission request carries what
the operator needs to decide — the title, the tool kind, and the raw
input the agent is about to run with — and a tool call's raw input can be
a whole file. :data:`RAW_INPUT_CHARS` is the cap, applied to the JSON
rendering of the input as a whole rather than per string inside it, so
the row a request writes is bounded whatever shape the input has.

The functions take the façade as an argument instead of being methods on
it: a policy is not something an :class:`~athanore.agents.base.Agent`
subclass overrides (that is what the configuration is for), and taking
``agent`` and ``ctx`` explicitly is what lets the ACP client (T039) call
them from a callback that has both in hand. What they need of the façade
is stated structurally, as :class:`PermissionAgent` and
:class:`ElicitationAgent`, so this module does not import the class that
satisfies them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, TypeGuard

from pydantic import BaseModel

from athanore.agents.base import AgentError
from athanore.engine.context import TaskContext
from athanore.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "ALLOW_KINDS",
    "AnswerLike",
    "DEFAULT_ELICITATION_PROMPT",
    "DEFAULT_TOOL_TITLE",
    "Elicited",
    "ElicitationAgent",
    "PermissionAgent",
    "PermissionOptionLike",
    "RAW_INPUT_CHARS",
    "REJECT_KINDS",
    "ToolCallLike",
    "ask_allowed",
    "choose_by_kind",
    "option_dict",
    "resolve_elicitation",
    "resolve_permission",
    "tool_call_summary",
]

#: The allow kinds, in preference order. ``allow_once`` first: in
#: claude-agent-acp ``allow_always`` installs a session-wide rule
#: (``addRules: [{toolName}]``) that disables per-call policy for the rest
#: of the run (20 §Finding 1).
ALLOW_KINDS = ["allow_once", "allow_always"]

#: The reject kinds, in preference order, for the same reason.
REJECT_KINDS = ["reject_once", "reject_always"]

#: How much of a tool call's raw input a permission request carries.
RAW_INPUT_CHARS = 500

#: The prompt of a permission request whose tool call has no title.
DEFAULT_TOOL_TITLE = "tool call"

#: The prompt of an elicitation that arrived without a message.
DEFAULT_ELICITATION_PROMPT = "the agent has a question"

#: What :func:`resolve_elicitation` answers ACP with: the action, and the
#: content that goes with an ``accept`` (06 §The model).
Elicited = tuple[Literal["accept", "decline"], Any]

_DECLINED: Elicited = ("decline", None)


class PermissionOptionLike(Protocol):
    """One ACP ``PermissionOption``: an id, a label, and its semantics.

    Read-only, and spelled structurally rather than imported from the SDK,
    so a test states a case in three attributes and the real
    ``acp.schema.PermissionOption`` satisfies it unchanged. ``kind`` is
    the field that decides — ``allow_once``, ``allow_always``,
    ``reject_once``, ``reject_always`` — and the id is what goes back to
    the agent.
    """

    @property
    def option_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...


class ToolCallLike(Protocol):
    """The part of an ACP tool call a permission request is about.

    Everything a summary carries is optional in the protocol, so
    everything here is nullable and an absent field is omitted rather
    than written as ``None`` (`AGENTS.md` §Real data only).
    """

    @property
    def title(self) -> str | None: ...

    @property
    def kind(self) -> str | None: ...

    @property
    def raw_input(self) -> Any: ...


class AnswerLike(Protocol):
    """The answer a request came back with, as a policy reads it.

    ``option_id`` for an ``options`` request and ``value`` for a ``form``
    one (06 §The model). Structural for the reason every other type here
    is: ``athanore.agents`` reaches the store only through
    ``TaskContext``, so the row this stands for is a type it never names
    (02 §Layering).
    """

    @property
    def option_id(self) -> str | None: ...

    @property
    def value(self) -> Any: ...


class PermissionAgent(Protocol):
    """What :func:`resolve_permission` needs of a façade (05 §Agent classes).

    The three attributes of ``ACPAgent`` that decide a permission, and
    nothing else. Stated here because ``athanore.agents.acp`` is written
    against *this* module rather than the other way round, and because a
    test can then be one object with three fields.
    """

    permission_policy: Literal["ask", "auto_allow", "auto_deny"]
    permission_timeout: float | None
    permission_timeout_action: Literal["deny", "allow"]


class ElicitationAgent(Protocol):
    """What :func:`resolve_elicitation` needs of a façade.

    ``permission_timeout`` is shared with permissions deliberately: both
    are an agent blocked mid-turn on a person, and 06 §Timeouts gives them
    one bound.
    """

    elicitation_policy: Literal["ask", "decline"]
    permission_timeout: float | None


def ask_allowed(ctx: TaskContext | None) -> TypeGuard[TaskContext]:
    """Whether an ``ask`` policy can actually reach a person from here.

    It can when there is a task: a request is opened *against* one (06
    §The model), the operator answers it in the run it belongs to, and a
    façade with no context — an agent run outside a node body — has no run
    and no task to put the question in.

    The predicate is named because both resolvers gate on it and they
    degrade differently: a permission falls back to ``auto_allow`` with a
    warning, because the turn is blocked on an answer that cannot come and
    the sandbox is what stands in for the operator there (05 §User-land
    adapters); an elicitation declines, because a question nobody will
    read is better answered "no" than guessed at.

    It is a :class:`~typing.TypeGuard` rather than a plain ``bool`` — it
    is one at run time either way — so that the branch which *may* ask
    holds a context rather than an optional one, and the check that gates
    the request is the same check that types it.
    """

    return ctx is not None


def choose_by_kind(
    options: Sequence[PermissionOptionLike], kinds: Sequence[str]
) -> str | None:
    """The id of the first option matching ``kinds``, in *that* order.

    ``kinds`` is a preference, not a filter: the loop is over the wanted
    kinds and then over the options, so ``["allow_once", "allow_always"]``
    picks ``allow_once`` however the agent ordered its list. That is the
    whole of 20 §Finding 1 — order is unspecified, ``kind`` is the
    semantics, and an adapter that lists rejection first must not turn an
    auto-allow into a denial.

    ``None`` when the agent offered nothing of any wanted kind. The
    caller decides what that means; for a policy it means
    :exc:`~athanore.agents.base.AgentError`.
    """

    for kind in kinds:
        for option in options:
            if option.kind == kind:
                return option.option_id
    return None


def option_dict(option: PermissionOptionLike) -> dict[str, Any]:
    """One option as the request row carries it: ``{option_id, name, kind}``.

    The agent's options **verbatim** (05 §Policies): the operator picks
    from what the agent offered, under the labels it offered them, and the
    id that comes back is the id it will be given. 06 §The model fixes the
    three keys, and ``RequestService.answer`` refuses an ``option_id``
    this list does not carry.
    """

    return {
        "option_id": option.option_id,
        "name": option.name,
        "kind": option.kind,
    }


def tool_call_summary(tool_call: ToolCallLike) -> dict[str, Any]:
    """What the operator is shown about the tool call, bounded.

    Title, kind, and the first :data:`RAW_INPUT_CHARS` characters of the
    raw input rendered as JSON — enough to decide with, and small enough
    to store. The cap is on the rendering rather than on each string
    inside it, because a bound per string still lets an input with a
    thousand of them balloon the row.

    A field the protocol did not carry is omitted, so an operator never
    reads ``null`` where the agent said nothing at all.
    """

    summary: dict[str, Any] = {}
    if tool_call.title is not None:
        summary["title"] = tool_call.title
    if tool_call.kind is not None:
        summary["kind"] = tool_call.kind
    if tool_call.raw_input is not None:
        summary["raw_input"] = _bounded(tool_call.raw_input)
    return summary


async def resolve_permission(
    agent: PermissionAgent,
    ctx: TaskContext | None,
    tool_call: ToolCallLike,
    options: Sequence[PermissionOptionLike],
) -> str:
    """Resolve one ACP permission request to the ``option_id`` to answer with.

    The three policies of 05 §Policies:

    - ``auto_allow`` — ``allow_once``, then ``allow_always``;
    - ``auto_deny`` — ``reject_once``, then ``reject_always``;
    - ``ask`` — open an ``options`` request carrying the agent's options
      verbatim and a bounded tool-call summary, and block the turn on it
      for ``agent.permission_timeout``.

    A timeout applies ``permission_timeout_action`` and records the answer
    with author ``engine`` (06 §Timeouts), so the request shows afterwards
    that nobody answered it and the engine chose — which is the one thing
    a silently defaulted permission never showed in the MVP.

    Raises :exc:`~athanore.agents.base.AgentError` when the policy cannot
    be honoured: no option of the wanted kind, or a policy value that is
    not one of the three. Both are the failure D10 exists to make loud.
    """

    policy = agent.permission_policy
    if policy == "auto_allow":
        return _picked(options, ALLOW_KINDS, "auto_allow")
    if policy == "auto_deny":
        return _picked(options, REJECT_KINDS, "auto_deny")
    if policy != "ask":
        raise AgentError(
            f"unknown permission_policy {policy!r}: expected 'ask', "
            "'auto_allow' or 'auto_deny'"
        )
    if ask_allowed(ctx):
        return await _ask_permission(agent, ctx, tool_call, options)

    _log.warning(
        "permission policy 'ask' with no task context: falling back to auto_allow",
        agent=type(agent).__name__,
        title=tool_call.title,
    )
    return _picked(options, ALLOW_KINDS, "auto_allow")


async def _ask_permission(
    agent: PermissionAgent,
    ctx: TaskContext,
    tool_call: ToolCallLike,
    options: Sequence[PermissionOptionLike],
) -> str:
    """The ``ask`` arm: open the request, block the turn, answer the agent.

    ``source="agent"`` and no ordinal, because a re-executed attempt does
    not reproduce a turn statement for statement and numbering a
    permission by position would replay one answer onto a different
    question (06 §Restart durability). The wait is
    :meth:`RequestsPort.wait
    <athanore.engine.services.RequestsPort.wait>`'s, which claims the
    answer, and the pool slot is not released around it: the attempt is
    holding an agent subprocess open, so there is nothing to hand back.
    """

    request = await ctx.services.requests.create_agent_request(
        f"permission: {tool_call.title or DEFAULT_TOOL_TITLE}",
        mode="options",
        kind="permission",
        options=[option_dict(option) for option in options],
        tool_call=tool_call_summary(tool_call),
    )
    try:
        answer = await ctx.services.requests.wait(
            request.id, timeout=agent.permission_timeout
        )
    except TimeoutError:
        answer = await _timed_out(agent, ctx, request.id, options)
    if answer.option_id is None:  # pragma: no cover - the service refuses it
        raise AgentError(
            f"request {request.id} was answered without an option_id, and a "
            "permission is answered with one"
        )
    return answer.option_id


async def resolve_elicitation(
    agent: ElicitationAgent,
    ctx: TaskContext | None,
    message: str,
    mode: str,
    requested_schema: BaseModel | Mapping[str, Any] | None,
) -> Elicited:
    """Bridge one ACP elicitation onto the request channel (06 §The model).

    A form-mode elicitation becomes a ``form`` request carrying the
    agent's ``requestedSchema``, with
    :func:`~athanore.requests.validators.json_schema_validator` registered
    over that schema so a misfitting answer is refused to the operator who
    gave it rather than to the agent several seconds later. The answer
    comes back as ``("accept", content)``.

    Everything else is ``("decline", None)``, and each decline is a
    decision rather than a failure:

    - ``elicitation_policy="decline"`` — the façade said so;
    - no task context — there is nobody to ask (:func:`ask_allowed`);
    - a mode other than ``form`` — URL mode would have the *operator*
      visit a link on the agent's behalf, which is not a question the
      request channel models, and 05 §Policies declines it;
    - no schema — a form with no fields is not a form;
    - the wait timing out — 06 §Timeouts.
    """

    schema = _schema_dict(requested_schema)
    if (
        agent.elicitation_policy == "ask"
        and mode == "form"
        and schema is not None
        and ask_allowed(ctx)
    ):
        return await _elicit(agent, ctx, message, schema)
    return _DECLINED


async def _elicit(
    agent: ElicitationAgent,
    ctx: TaskContext,
    message: str,
    schema: dict[str, Any],
) -> Elicited:
    """The ``ask`` arm of an elicitation: a ``form`` request, and its answer.

    The validator is registered before the wait and forgotten after it, on
    every path, because it belongs to *this* waiter: left behind, it would
    validate the next answer to a request nobody is waiting on any more
    (06 §Service).

    A timeout leaves the request pending rather than declining it in the
    store: the agent has been told no and has moved on, so an answer given
    afterwards has nobody to reach and goes stale with the attempt — which
    is what 06 §Restart durability says becomes of an agent-raised request
    its session outlived.
    """

    requests = ctx.services.requests
    request = await requests.create_agent_request(
        message or DEFAULT_ELICITATION_PROMPT,
        mode="form",
        kind="elicitation",
        schema=schema,
    )
    requests.register_schema_validator(request.id, schema)
    try:
        answer = await requests.wait(request.id, timeout=agent.permission_timeout)
    except TimeoutError:
        _log.warning(
            "elicitation not answered in time: declining",
            request_id=request.id,
            timeout=agent.permission_timeout,
        )
        return _DECLINED
    finally:
        requests.unregister_validator(request.id)
    return ("accept", answer.value)


async def _timed_out(
    agent: PermissionAgent,
    ctx: TaskContext,
    request_id: int,
    options: Sequence[PermissionOptionLike],
) -> AnswerLike:
    """The answer to a permission nobody gave one to, authored by the engine.

    The operator is checked for first, without waiting: an answer that
    landed in the moment the clock ran out is a person's decision, and
    overwriting it with the timeout action would be the engine answering a
    question that had already been answered.

    Otherwise ``permission_timeout_action`` is applied through
    ``answer_as_engine``, which is what makes the record say *the engine
    chose this* rather than leaving a request that looks like it was never
    asked.
    """

    given = await ctx.services.requests.poll(request_id, 0)
    if given is not None:
        return given
    allow = agent.permission_timeout_action == "allow"
    chosen = _picked(
        options,
        ALLOW_KINDS if allow else REJECT_KINDS,
        f"permission_timeout_action={agent.permission_timeout_action!r}",
    )
    _log.warning(
        "permission not answered in time: answering as the engine",
        request_id=request_id,
        timeout=agent.permission_timeout,
        action=agent.permission_timeout_action,
        option_id=chosen,
    )
    return await ctx.services.requests.answer_as_engine(request_id, chosen)


def _picked(
    options: Sequence[PermissionOptionLike], kinds: Sequence[str], policy: str
) -> str:
    """:func:`choose_by_kind`, or the refusal a policy owes when it cannot.

    D10: "a policy that cannot be honoured raises ``AgentError``. Failing
    loudly beats reporting success." The message names both what was
    wanted and what was offered, because the alternative — an agent whose
    option list does not match its adapter's documentation — is otherwise
    invisible.
    """

    chosen = choose_by_kind(options, kinds)
    if chosen is None:
        offered = [option.kind for option in options]
        raise AgentError(
            f"{policy} needs an option of kind {' or '.join(kinds)}, and the "
            f"agent offered {offered}"
        )
    return chosen


def _schema_dict(
    requested_schema: BaseModel | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """An elicitation's ``requestedSchema`` as the plain JSON it is.

    The SDK parses it into a model and the wire name of every field is its
    alias, so the dump is ``by_alias`` — what is stored has to be the
    document the agent sent, because that is what the SPA renders a form
    from and what the validator enforces. ``exclude_none`` drops the
    keywords it did not send, and ``_meta`` is ACP's own extension slot,
    which is not part of the schema.
    """

    if requested_schema is None:
        return None
    if isinstance(requested_schema, BaseModel):
        schema = requested_schema.model_dump(by_alias=True, exclude_none=True)
    else:
        schema = dict(requested_schema)
    schema.pop("_meta", None)
    return schema


def _bounded(raw_input: Any) -> str:
    """``raw_input`` as JSON, capped at :data:`RAW_INPUT_CHARS` characters.

    Never raises: a tool call's raw input is whatever the agent put in a
    JSON-RPC message, and failing to summarise it would turn a permission
    prompt into a failed turn. Anything that will not serialise is
    rendered with ``str``.
    """

    text = json.dumps(raw_input, default=str)
    if len(text) <= RAW_INPUT_CHARS:
        return text
    return text[:RAW_INPUT_CHARS] + "…"
