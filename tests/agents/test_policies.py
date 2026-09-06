"""Permissions and elicitations, resolved by policy (05 §Policies, D10).

Two things reach a façade from inside an agent's turn, and this suite is
what happens to them. The subject is
:mod:`athanore.agents.policies`; what it is asserted against is a real
store, a real :class:`~athanore.requests.service.RequestService` and a
real request port, because every question these tests ask is about a row:
*was a request opened at all*, *what did it carry*, *who is recorded as
having answered it*. A stubbed port would let this suite agree with
itself about all three.

It carries the assertions of the MVP's ``tests/test_permissions.py`` and
``tests/test_elicitation.py`` that do not need a subprocess (the ones
that do are T039a's). The first of them is the reason the module exists:
**a reject-first option list must still resolve to ``allow_once`` under
``auto_allow``**. ``claude-agent-acp`` lists rejection first, the MVP
picked ``options[0]``, and every tool call in every run was denied while
the run reported ``ok`` (20 §Finding 1).

Two doubles, and no more. :class:`Facade` is the four configuration
attributes ``ACPAgent`` will carry (05 §Agent classes), spelled with
their exact types so that a change to either side stops type-checking
rather than drifting; :class:`Option` and :class:`ToolCall` are the ACP
values the client passes through, by attribute, so a case is three
fields rather than a protocol handshake.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, Field
from structlog.testing import capture_logs

from athanore.agents.base import AgentError
from athanore.agents.policies import (
    ALLOW_KINDS,
    RAW_INPUT_CHARS,
    REJECT_KINDS,
    ask_allowed,
    choose_by_kind,
    option_dict,
    resolve_elicitation,
    resolve_permission,
    tool_call_summary,
)
from athanore.engine.context import TaskContext
from athanore.engine.services import TaskRequests, TaskServices
from athanore.events.bus import EventBus
from athanore.requests.errors import InvalidAnswer
from athanore.requests.service import RequestService
from athanore.store.engine import make_engine
from athanore.store.rows import (
    AnswerAuthor,
    RequestKind,
    RequestMode,
    RequestSource,
    RequestView,
)
from athanore.store.tables import metadata
from athanore.store.uow import Store

WORKFLOW = "demo"
NODE = "build"
API_BASE = "http://127.0.0.1:4002"
TOKEN = "tok-fdb0a1c2e3f4"

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 5.0

#: Short enough not to pace a test, long enough not to be flaky under a
#: loaded container: what a timeout test gives the operator.
BLINK = 0.05


# --------------------------------------------------------------------------
# The doubles
# --------------------------------------------------------------------------


@dataclass
class Facade:
    """The four attributes of ``ACPAgent`` a policy reads (05 §Agent classes).

    Spelled with the annotations of 05 rather than as plain strings: the
    protocols in :mod:`athanore.agents.policies` state the same types, so
    a drift between the façade and its policies is a type error here
    before it is a behaviour nobody notices in a run.
    """

    permission_policy: Literal["ask", "auto_allow", "auto_deny"] = "ask"
    permission_timeout: float | None = None
    permission_timeout_action: Literal["deny", "allow"] = "deny"
    elicitation_policy: Literal["ask", "decline"] = "ask"


@dataclass
class Option:
    """One ACP ``PermissionOption``: what the agent offered, verbatim."""

    option_id: str
    name: str
    kind: str


@dataclass
class ToolCall:
    """The ACP tool call a permission is about, as much of it as matters."""

    title: str | None = "edit a.py"
    kind: str | None = "edit"
    raw_input: Any = None


#: ``claude-agent-acp``'s own list, in its own order (20 §Finding 1). The
#: order is the point: rejection first.
REJECT_FIRST = [
    Option("reject", "Deny", "reject_once"),
    Option("allow", "Allow Once", "allow_once"),
    Option("allow_always", "Always Allow", "allow_always"),
]

#: An agent that offers no way to say yes.
ONLY_REJECT = [Option("reject", "Deny", "reject_once")]

#: An agent that offers no way to say no.
ONLY_ALLOW = [Option("allow", "Allow Once", "allow_once")]


class SchemaModel(BaseModel):
    """A stand-in for the SDK's ``ElicitationSchema``: a model with a dump.

    ``field_meta``/``_meta`` is ACP's extension slot and is aliased here
    exactly as the SDK aliases it, because dropping it is part of what
    turns a parsed model back into the schema document the agent sent.
    """

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] | None = None
    title: str | None = None
    field_meta: dict[str, Any] | None = Field(default=None, alias="_meta")


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "mood": {"type": "string", "enum": ["ok", "meh"]},
    },
    "required": ["name"],
}


# --------------------------------------------------------------------------
# A store, a service, and one attempt that can ask
# --------------------------------------------------------------------------


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def store(tmp_path: Path, bus: EventBus) -> AsyncIterator[Store]:
    """A store on an empty SQLite file, publishing to :func:`bus`.

    The bus matters: ``RequestService.wait`` is woken by
    ``request.answered``, so a service built over a store that published
    nowhere would only ever time out.
    """

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside its engine (T031)."""

    return RequestService(store, bus)


@pytest.fixture
def context(
    store: Store, service: RequestService
) -> Callable[[], Awaitable[TaskContext]]:
    """The context of one **claimed** attempt, with its request port wired.

    Claimed, not merely enqueued: a request is answerable only while its
    task is ``in_progress`` or ``waiting`` (06 §The model), so a context
    over a ``ready`` row would make every answer here a
    ``StaleRequest`` — and the ``ask`` policy is the half of this module
    that opens rows at all.
    """

    async def make() -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, "a run")
            task = await uow.tasks.enqueue(
                run.id, NODE, None, priority=0, explicit=False
            )
            await uow.tasks.claim_ready(1, [WORKFLOW])
        port = TaskRequests(service, run_id=run.id, task_id=task.id)
        ctx = TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=NODE,
            attempt=1,
            token=TOKEN,
            api_base=API_BASE,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=NODE,
                workflow=WORKFLOW,
                flush_interval=0.05,
                requests=port,
            ),
        )
        port.attach(ctx)
        return ctx

    return make


Make = Callable[[], Awaitable[TaskContext]]


async def opened(service: RequestService, ctx: TaskContext) -> RequestView:
    """The one request this attempt has opened, once it has opened it."""

    async with asyncio.timeout(DEADLINE):
        while True:
            views = await service.list_for_run(ctx.run_id)
            if views:
                assert len(views) == 1, "one question at a time in this suite"
                return views[0]
            await asyncio.sleep(0.005)


async def answered(
    service: RequestService,
    ctx: TaskContext,
    *,
    option_id: str | None = None,
    value: Any = None,
) -> RequestView:
    """Answer the attempt's one request as the operator would, once it exists."""

    view = await opened(service, ctx)
    await service.answer(view.id, option_id=option_id, value=value)
    return view


def answering(
    service: RequestService,
    ctx: TaskContext,
    *,
    option_id: str | None = None,
    value: Any = None,
) -> asyncio.Task[RequestView]:
    """An operator, in the background, for a policy that is about to block."""

    return asyncio.create_task(answered(service, ctx, option_id=option_id, value=value))


# --------------------------------------------------------------------------
# choose_by_kind: the ordering bug of 20 §Finding 1
# --------------------------------------------------------------------------


def test_reject_first_ordering_still_picks_allow_once() -> None:
    """The one assertion this module exists for (20 §Finding 1, D10)."""

    assert choose_by_kind(REJECT_FIRST, ALLOW_KINDS) == "allow"


def test_the_preference_is_the_kinds_order_not_the_options_order() -> None:
    """``allow_always`` is a fallback: it installs a session-wide rule."""

    reordered = [REJECT_FIRST[2], REJECT_FIRST[1], REJECT_FIRST[0]]

    assert choose_by_kind(reordered, ALLOW_KINDS) == "allow"
    assert choose_by_kind(reordered, REJECT_KINDS) == "reject"


def test_allow_always_is_taken_when_it_is_the_only_way_to_say_yes() -> None:
    options = [Option("reject", "Deny", "reject_once"), REJECT_FIRST[2]]

    assert choose_by_kind(options, ALLOW_KINDS) == "allow_always"


def test_nothing_of_the_wanted_kind_is_none() -> None:
    assert choose_by_kind(ONLY_REJECT, ALLOW_KINDS) is None
    assert choose_by_kind([], ALLOW_KINDS) is None


def test_an_option_travels_verbatim() -> None:
    assert option_dict(REJECT_FIRST[0]) == {
        "option_id": "reject",
        "name": "Deny",
        "kind": "reject_once",
    }


# --------------------------------------------------------------------------
# The headless policies
# --------------------------------------------------------------------------


async def test_auto_allow_picks_allow_once_from_a_reject_first_list(
    context: Make, service: RequestService
) -> None:
    """The MVP's bug, as a policy: no request, and not a denial."""

    ctx = await context()

    chosen = await resolve_permission(
        Facade(permission_policy="auto_allow"), ctx, ToolCall(), REJECT_FIRST
    )

    assert chosen == "allow"
    assert await service.list_for_run(ctx.run_id) == []


async def test_auto_deny_picks_reject_once(context: Make) -> None:
    ctx = await context()

    chosen = await resolve_permission(
        Facade(permission_policy="auto_deny"), ctx, ToolCall(), REJECT_FIRST
    )

    assert chosen == "reject"


async def test_a_policy_that_cannot_be_honoured_raises() -> None:
    """D10: failing loudly beats reporting success."""

    with pytest.raises(AgentError) as raised:
        await resolve_permission(
            Facade(permission_policy="auto_allow"), None, ToolCall(), ONLY_REJECT
        )

    assert "allow_once or allow_always" in str(raised.value)
    assert "reject_once" in str(raised.value), "it names what was offered"

    with pytest.raises(AgentError):
        await resolve_permission(
            Facade(permission_policy="auto_deny"), None, ToolCall(), ONLY_ALLOW
        )


async def test_an_unrecognised_policy_raises_rather_than_guessing() -> None:
    """A typo may not become "allow everything" silently."""

    agent = Facade()
    agent.permission_policy = "auto-allow"  # type: ignore[assignment]

    with pytest.raises(AgentError) as raised:
        await resolve_permission(agent, None, ToolCall(), REJECT_FIRST)

    assert "auto-allow" in str(raised.value)


# --------------------------------------------------------------------------
# `ask` with nobody to ask
# --------------------------------------------------------------------------


def test_ask_allowed_is_the_presence_of_a_task() -> None:
    assert ask_allowed(None) is False


async def test_ask_allowed_is_true_inside_an_attempt(context: Make) -> None:
    assert ask_allowed(await context()) is True


async def test_ask_outside_a_task_context_warns_and_allows() -> None:
    """No task, no request to open: degrade downward, and say so."""

    with capture_logs() as logged:
        chosen = await resolve_permission(Facade(), None, ToolCall(), REJECT_FIRST)

    assert chosen == "allow"
    assert [entry["log_level"] for entry in logged] == ["warning"]
    assert logged[0]["event"] == (
        "permission policy 'ask' with no task context: falling back to auto_allow"
    )
    assert logged[0]["agent"] == "Facade"
    assert logged[0]["title"] == "edit a.py"


async def test_the_degraded_fallback_is_still_a_policy_that_can_fail() -> None:
    """``auto_allow`` outside a context is ``auto_allow``, refusal included."""

    with pytest.raises(AgentError), capture_logs():
        await resolve_permission(Facade(), None, ToolCall(), ONLY_REJECT)


# --------------------------------------------------------------------------
# `ask` with somebody to ask
# --------------------------------------------------------------------------


async def test_ask_opens_an_options_request_and_returns_the_operators_choice(
    context: Make, service: RequestService
) -> None:
    ctx = await context()
    operator = answering(service, ctx, option_id="allow_always")

    chosen = await resolve_permission(Facade(), ctx, ToolCall(), REJECT_FIRST)

    view = await operator
    assert chosen == "allow_always", "the operator's pick, not the policy's"
    assert view.mode is RequestMode.options
    assert view.kind is RequestKind.permission
    assert view.source is RequestSource.agent
    assert view.prompt == "permission: edit a.py"
    assert view.options == [option_dict(one) for one in REJECT_FIRST]
    assert view.tool_call == {"title": "edit a.py", "kind": "edit"}


async def test_a_tool_call_with_no_title_still_reads_as_a_question(
    context: Make, service: RequestService
) -> None:
    ctx = await context()
    operator = answering(service, ctx, option_id="reject")

    await resolve_permission(
        Facade(), ctx, ToolCall(title=None, kind=None), REJECT_FIRST
    )

    view = await operator
    assert view.prompt == "permission: tool call"
    assert view.tool_call == {}, "unknown is omitted, not written as null"


def test_the_tool_call_summary_is_bounded() -> None:
    """A tool call's raw input can be a whole file (05 §Policies)."""

    summary = tool_call_summary(ToolCall(raw_input={"content": "x" * 10_000}))

    assert summary["title"] == "edit a.py"
    assert summary["kind"] == "edit"
    assert len(summary["raw_input"]) == RAW_INPUT_CHARS + 1
    assert summary["raw_input"].startswith('{"content": "xxx')
    assert summary["raw_input"].endswith("…")


def test_a_raw_input_that_fits_is_carried_whole() -> None:
    summary = tool_call_summary(ToolCall(raw_input={"path": "a.py"}))

    assert summary["raw_input"] == '{"path": "a.py"}'


def test_a_raw_input_that_will_not_serialise_is_still_summarised() -> None:
    """Failing to quote an input must not fail the turn."""

    summary = tool_call_summary(ToolCall(raw_input={"when": object()}))

    assert summary["raw_input"].startswith('{"when": "<object object at')


# --------------------------------------------------------------------------
# The timeout: an answer the engine gave
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected"),
    [("deny", "reject"), ("allow", "allow")],
)
async def test_a_permission_timeout_is_answered_by_the_engine(
    context: Make, service: RequestService, action: str, expected: str
) -> None:
    """06 §Timeouts: the record says the engine chose, not a person."""

    ctx = await context()
    agent = Facade(
        permission_timeout=BLINK,
        permission_timeout_action="allow" if action == "allow" else "deny",
    )

    with capture_logs() as logged:
        chosen = await resolve_permission(agent, ctx, ToolCall(), REJECT_FIRST)

    assert chosen == expected
    view = await opened(service, ctx)
    assert view.answered_by is AnswerAuthor.engine
    assert view.answer == expected
    assert view.pending is False
    assert logged[0]["event"] == (
        "permission not answered in time: answering as the engine"
    )
    assert logged[0]["option_id"] == expected


async def test_a_timeout_whose_action_cannot_be_honoured_raises(
    context: Make, service: RequestService
) -> None:
    """An agent that offers no way to say no, and a policy that says no."""

    ctx = await context()

    with pytest.raises(AgentError), capture_logs():
        await resolve_permission(
            Facade(permission_timeout=BLINK), ctx, ToolCall(), ONLY_ALLOW
        )

    view = await opened(service, ctx)
    assert view.pending is True, "the question is still there to be answered"


async def test_an_answer_that_lands_as_the_clock_runs_out_stands(
    service: RequestService, context: Make
) -> None:
    """The engine never overwrites a decision a person already made.

    The race is real but narrow — the operator answers between the wait
    giving up and the timeout action being applied — so it is staged: a
    port whose ``wait`` answers as the operator and *then* raises
    ``TimeoutError`` puts the two events in exactly that order, every
    time.
    """

    ctx = await context()

    class Racing(TaskRequests):
        async def wait(
            self,
            request_id: int,
            timeout: float | None = None,  # noqa: ASYNC109 - the port's signature
        ) -> Any:
            await service.answer(request_id, option_id="allow_always")
            raise TimeoutError("the operator was a moment late")

    port = Racing(service, run_id=ctx.run_id, task_id=ctx.task_id)
    port.attach(ctx)
    ctx.services.requests = port

    chosen = await resolve_permission(
        Facade(permission_timeout=BLINK, permission_timeout_action="deny"),
        ctx,
        ToolCall(),
        REJECT_FIRST,
    )

    assert chosen == "allow_always"
    view = await opened(service, ctx)
    assert view.answered_by is AnswerAuthor.user


# --------------------------------------------------------------------------
# Elicitations
# --------------------------------------------------------------------------


async def test_a_form_elicitation_opens_a_form_request_and_accepts(
    context: Make, service: RequestService
) -> None:
    """The MVP's round trip, without the subprocess."""

    ctx = await context()
    operator = answering(service, ctx, value={"name": "ada", "count": 3})

    action, content = await resolve_elicitation(Facade(), ctx, "who?", "form", SCHEMA)

    view = await operator
    assert (action, content) == ("accept", {"name": "ada", "count": 3})
    assert view.mode is RequestMode.form
    assert view.kind is RequestKind.elicitation
    assert view.source is RequestSource.agent
    assert view.prompt == "who?"
    assert view.schema_ == SCHEMA


async def test_the_registered_validator_refuses_a_misfitting_answer(
    context: Make, service: RequestService
) -> None:
    """Validation happens where the answer lands (06 §Service)."""

    ctx = await context()

    async def operator() -> None:
        view = await opened(service, ctx)
        with pytest.raises(InvalidAnswer) as raised:
            await service.answer(view.id, value={"count": 1})
        assert sorted(error["loc"][0] for error in raised.value.errors) == ["name"]
        await service.answer(view.id, value={"name": "ada"})

    answering_task = asyncio.create_task(operator())
    action, content = await resolve_elicitation(Facade(), ctx, "who?", "form", SCHEMA)
    await answering_task

    assert (action, content) == ("accept", {"name": "ada"})


async def test_the_validator_is_forgotten_when_the_waiter_leaves(
    context: Make, service: RequestService
) -> None:
    """A validator left behind would validate somebody else's answer."""

    ctx = await context()
    operator = answering(service, ctx, value={"name": "ada"})

    await resolve_elicitation(Facade(), ctx, "who?", "form", SCHEMA)
    view = await operator

    # The registry is private, and it is also the only record of the pair:
    # a validator is registered and forgotten, and neither is a row.
    assert view.id not in service._validators


async def test_a_pydantic_schema_is_stored_as_the_agent_sent_it(
    context: Make, service: RequestService
) -> None:
    """The SDK parses ``requestedSchema`` into a model; the row is the JSON."""

    ctx = await context()
    operator = answering(service, ctx, value={"name": "ada"})

    await resolve_elicitation(
        Facade(),
        ctx,
        "who?",
        "form",
        SchemaModel(
            properties={"name": {"type": "string"}},
            required=["name"],
            _meta={"acp": "extension"},
        ),
    )

    view = await operator
    assert view.schema_ == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }


@pytest.mark.parametrize(
    ("agent", "mode", "schema"),
    [
        (Facade(elicitation_policy="decline"), "form", SCHEMA),
        (Facade(), "url", None),
        (Facade(), "url", SCHEMA),
        (Facade(), "other", SCHEMA),
        (Facade(), "form", None),
    ],
    ids=["policy", "url", "url-with-schema", "other", "no-schema"],
)
async def test_an_elicitation_that_cannot_be_asked_declines(
    context: Make,
    service: RequestService,
    agent: Facade,
    mode: str,
    schema: dict[str, Any] | None,
) -> None:
    """Each decline is a decision, and none of them opens a request."""

    ctx = await context()

    assert await resolve_elicitation(agent, ctx, "q", mode, schema) == (
        "decline",
        None,
    )
    assert await service.list_for_run(ctx.run_id) == []


async def test_an_elicitation_outside_a_task_context_declines() -> None:
    """Nobody to ask: better answered "no" than guessed at."""

    assert await resolve_elicitation(Facade(), None, "q", "form", SCHEMA) == (
        "decline",
        None,
    )


async def test_an_elicitation_timeout_declines_and_leaves_the_question_open(
    context: Make, service: RequestService
) -> None:
    """06 §Timeouts. The row stays: it goes stale with the attempt."""

    ctx = await context()

    with capture_logs() as logged:
        answer = await resolve_elicitation(
            Facade(permission_timeout=BLINK), ctx, "who?", "form", SCHEMA
        )

    assert answer == ("decline", None)
    view = await opened(service, ctx)
    assert view.pending is True
    assert view.answered_by is None
    assert logged[0]["event"] == "elicitation not answered in time: declining"


async def test_an_elicitation_with_no_message_still_reads_as_a_question(
    context: Make, service: RequestService
) -> None:
    ctx = await context()
    operator = answering(service, ctx, value={"name": "ada"})

    await resolve_elicitation(Facade(), ctx, "", "form", SCHEMA)

    assert (await operator).prompt == "the agent has a question"


def test_the_kinds_are_the_four_acp_names() -> None:
    """A rename on either side is a bug, not a refactor (20 §Finding 1)."""

    assert ALLOW_KINDS == ["allow_once", "allow_always"]
    assert REJECT_KINDS == ["reject_once", "reject_always"]


def test_sequences_are_all_that_is_asked_of_an_option_list() -> None:
    """The client hands over whatever the SDK parsed; a tuple is fine."""

    options: Sequence[Option] = tuple(REJECT_FIRST)

    assert choose_by_kind(options, ALLOW_KINDS) == "allow"
