"""The ACP subprocess behind a façade: spawn it, talk to it, account for it.

05 §The ACP client and §Session lifecycle are the specification, 20 is the
evidence behind three of the rules in it, and everything a façade is
*configured* with is on :class:`~athanore.agents.base.Agent` and
:class:`ACPAgent` rather than in here. This module is the transport: a
child process on stdio, a JSON-RPC conversation with it, and one
:class:`~athanore.agents.base.AgentResult` at the end.

Two objects, and the split is 20 §Finding 3. :class:`ACPClient` is the
callback side — what the agent asks *us* while its turn runs — and it is
module-level and swappable through :attr:`ACPAgent.client_class`, because
the MVP defined it inside ``run()`` and changing one policy meant forking
a hundred and fifty lines. :class:`ACPAgent` is the façade: the process,
the handshake, the prompt, the repair turns, and the cleanup.

**The rules this module exists to keep**

- **A config option is resolved by category, never by id.** ``model`` and
  ``thought_level`` are categories; the ids under them differ per agent,
  and the MVP sent pi's id to claude-agent-acp, had it rejected, and hid
  the rejection under a bare ``except`` (20 §Finding 2, D11). Here a
  rejection is a WARNING *and* a ``notice`` chunk in the transcript,
  because a build that silently ran on the wrong model is exactly what
  nobody notices.
- **Nothing the child inherits is an accident.** ``CLAUDE_*``,
  ``CLAUDECODE`` and ``CLAUDE_PID`` are scrubbed, or an
  :attr:`~ACPAgent.env_allowlist` keeps nothing by default; the task
  token and URL are exported last but one, and the class's explicit
  ``env`` wins (20 §Finding 4, 12 §Agents).
- **The client owns the filesystem it is asked about, and it owns
  none.** ``fs/*`` and ``terminal/*`` answer ``method_not_found``: agents
  do their own I/O, in their own sandbox, and answering would put this
  process behind their file writes.
- **Failure inside a callback is not the agent's to swallow.** An
  exception raised in an ACP callback becomes a JSON-RPC error to the
  agent and never reaches the caller, so a policy that could not be
  honoured is *recorded* on the client and re-raised by ``run()`` once
  the turn ends. Failing loudly beats reporting success (D10).
- **Stats are recorded exactly once, on every exit path, before the
  exception.** The tokens were spent whether or not the turn worked, and
  the failure path is where a number is most worth having (05 §Stats
  entry, T039a).
- **A replay is history, not this attempt's transcript.** While the
  client is ``replaying`` — the façade sets it around a ``session/load``
  and nowhere else — the updates an agent re-sends write no chunk, add
  no text and count no tool call: they were recorded by the attempt
  that ran them, and a tenth turn's transcript that carried the first
  nine would count tool calls it did not make (23 §The replay is not
  this attempt's transcript, D255).
- **A refusal is an answer.** ``refusal``, ``cancelled`` and a truncated
  final turn come back as a *failed result* the node body routes on; a
  timeout, a transport failure and a missing submission raise
  :exc:`~athanore.agents.base.AgentError`, because there is no value to
  route with (05 §AgentResult).
- **Retries are the engine's.** Nothing here retries anything. Rule 3.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn

from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent, text_block
from acp.client import ClientSideConnection
from acp.schema import (
    AcceptElicitationResponse,
    AcpMcpServer,
    AllowedOutcome,
    ClientCapabilities,
    DeclineElicitationResponse,
    ElicitationFormRequestMode,
    ElicitationFormSessionMode,
    HttpHeader,
    HttpMcpServer,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    McpServerStdio,
    PermissionOption,
    PromptResponse,
    RequestPermissionResponse,
    ResumeSessionResponse,
    SseMcpServer,
    ToolCallUpdate,
)

from athanore import __version__
from athanore.agents.base import (
    Agent,
    AgentError,
    AgentResult,
    Tier,
    task_base,
)
from athanore.agents.policies import (
    MCP_SERVER_NAME,
    Elicited,
    resolve_elicitation,
    resolve_permission,
)
from athanore.agents.stats import (
    SessionStatsProvider,
    StatsReason,
    build_entry,
    merge_usage,
    record_entry,
    usage_from_acp,
)
from athanore.agents.submissions import attach, needs_repair, repair_prompt
from athanore.engine.context import TaskContext, maybe_current_task
from athanore.logging import get_logger
from athanore.settings import AthanoreSettings

_log = get_logger(__name__)

__all__ = [
    "ACPAgent",
    "ACPClient",
    "CONFIG_CATEGORIES",
    "KILL_AFTER",
    "SCRUBBED_NAMES",
    "SCRUBBED_PREFIXES",
    "STDERR_CAP",
    "TOKEN_HEADER",
]

#: Environment variables a child never inherits: session-scoped state a
#: server started from inside a Claude Code session would otherwise hand
#: to every agent it spawns (20 §Finding 4, 12 §Agents). ``CLAUDE_PID`` is
#: covered by the prefix and named anyway, because 12 names it.
SCRUBBED_PREFIXES = ("CLAUDE_",)
SCRUBBED_NAMES = frozenset({"CLAUDECODE", "CLAUDE_PID"})

#: How much agent stderr reaches the structured log before it is only
#: drained. A crashing adapter can produce megabytes; the first 64 KiB is
#: what a diagnosis needs, and reading past the cap without logging is
#: what keeps the child from blocking on a full pipe.
STDERR_CAP = 64 * 1024

#: The stdout buffer given to the child. One ACP frame is one line, and a
#: tool call's ``rawInput`` — a file the agent just read — routinely
#: exceeds asyncio's 64 KiB default, which would fail the read rather
#: than the tool call.
STDOUT_LIMIT = 8 * 1024 * 1024

#: How long a terminated child has to exit before it is killed (05
#: §Session lifecycle, step 7).
KILL_AFTER = 5.0

#: The two ACP config categories a façade sets, and the attribute each
#: one comes from. Resolution is **by category**; the ids differ per
#: agent (20 §Finding 2, D11).
CONFIG_CATEGORIES: Mapping[str, str] = {"model": "model", "thought_level": "thinking"}

#: The header a task token travels in, everywhere (12 §Task tokens).
TOKEN_HEADER = "X-Athanore-Token"

#: What ``session/new`` takes for ``mcp_servers``. The list is invariant
#: and the ``mcp`` tier only ever puts one HTTP server in it, so the
#: union is spelled once here rather than at the call.
_McpServers = list[HttpMcpServer | SseMcpServer | AcpMcpServer | McpServerStdio]

#: The transcript kinds this module writes. Plain strings rather than
#: ``store.rows.ChunkKind``: ``athanore.agents`` reaches the store only
#: through ``TaskContext``, and ``StreamService.append`` coerces (02
#: §Layering).
_CHUNKS: Mapping[str, str] = {
    "agent_message_chunk": "text",
    "agent_thought_chunk": "thought",
    "tool_call": "tool_call",
    "tool_call_update": "tool_result",
}


# --------------------------------------------------------------------------
# The policies one run answers with
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Policies:
    """The façade's policy configuration, after ``settings`` has had its say.

    ``settings.permission_policy`` may force a global default — the CI
    case of 05 §Policies — and
    :func:`~athanore.agents.policies.resolve_permission` reads the policy
    off the object it is handed, so the override is applied by handing it
    a different object rather than by mutating the agent (a class
    attribute, shared by every run of every task).
    """

    permission_policy: Literal["ask", "auto_allow", "auto_deny"]
    permission_timeout: float | None
    permission_timeout_action: Literal["deny", "allow"]
    elicitation_policy: Literal["ask", "decline"]


def _policies(agent: ACPAgent, settings: AthanoreSettings) -> _Policies:
    """The effective policies for one run, and a line when they were forced."""

    forced = settings.permission_policy
    if forced is not None and forced != agent.permission_policy:
        _log.info(
            "settings.permission_policy overrides the agent's",
            agent=type(agent).__name__,
            configured=agent.permission_policy,
            forced=forced,
        )
    return _Policies(
        permission_policy=forced or agent.permission_policy,
        permission_timeout=agent.permission_timeout,
        permission_timeout_action=agent.permission_timeout_action,
        elicitation_policy=agent.elicitation_policy,
    )


# --------------------------------------------------------------------------
# The client: what the agent asks us while its turn runs
# --------------------------------------------------------------------------


class ACPClient(Client):
    """The ACP callback side of a running turn (05 §The ACP client).

    Three jobs, and no decisions. It **transcribes** — assistant text,
    thoughts and tool-call updates become ``StreamChunk`` rows through
    ``ctx.services.stream``; it **counts** — tool calls and denied
    permissions, for the stats entry; and it **delegates** — a permission
    request and an elicitation go to :mod:`athanore.agents.policies`,
    which is the only thing that decides either. While it is
    :attr:`replaying` it does the first two of those to nothing: a
    ``session/load``'s re-sent history is dropped and counted, and only
    the delegating goes on (23 §The replay is not this attempt's
    transcript).

    Module-level and referenced by :attr:`ACPAgent.client_class` so a
    façade can substitute one (20 §Finding 3). A subclass takes the same
    three arguments.

    **A failure here has to be carried out by hand.** The SDK turns an
    exception raised in a callback into a JSON-RPC error to the agent, so
    an :exc:`~athanore.agents.base.AgentError` from a policy would end up
    as an error response and a run that reported ``ok`` — the exact shape
    of 20 §Finding 1. It is therefore recorded in :attr:`failure` on the
    way past, and ``ACPAgent.run()`` raises it once the turn is over.

    **The transcript never fails a turn.** A chunk that cannot be
    appended — the attempt's transcript already closed, the store
    unavailable — is logged and dropped: the work log carries the
    deliverables, and a turn killed by its own diagnostics is a worse
    outcome than a gap in them.
    """

    def __init__(
        self,
        agent: ACPAgent,
        ctx: TaskContext | None,
        policies: _Policies | None = None,
    ) -> None:
        self.agent = agent
        self.ctx = ctx
        #: The policies to answer with. The agent's own, unless a run
        #: built them from ``settings`` (:func:`_policies`).
        self.policies: Any = agent if policies is None else policies
        #: Assistant text, in order, for :attr:`AgentResult.text`.
        self.text: list[str] = []
        #: ACP ``ToolCallStart`` count, for the stats entry (05).
        self.tool_calls = 0
        #: How many permissions were answered with a ``reject_*`` option.
        self.denied_permissions = 0
        #: The first policy failure of the turn, re-raised by ``run()``.
        self.failure: AgentError | None = None
        #: The connection this client was bound to, from ``on_connect``.
        self.connection: Any = None
        #: Whether ``session/update`` is a replay to be dropped. Set by the
        #: façade around a ``session/load`` and nowhere else (23, D255).
        self.replaying: bool = False
        #: How many updates arrived while :attr:`replaying` was set.
        self.replayed: int = 0

    # -- the transcript --------------------------------------------------

    async def append(self, kind: str, text: str) -> None:
        """Put one chunk in this attempt's transcript, or log why not."""

        if self.ctx is None:
            _log.debug("transcript chunk with no task context", kind=kind)
            return
        try:
            await self.ctx.services.stream.append(kind, text)
        except Exception:
            _log.warning(
                "transcript chunk dropped",
                task_id=self.ctx.task_id,
                kind=kind,
                exc_info=True,
            )

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        """One ``session/update`` notification, mapped onto a chunk kind.

        The four kinds of 05, and nothing else: a plan update, an
        available-commands list or a mode change describes the agent's
        own UI and is not part of the transcript an operator reads.

        Under :attr:`replaying` every update is dropped and counted,
        whatever its kind, before anything is awaited: the replay is what
        the agent sent between ``session/load`` and its answer (23
        §Terms), and the count a reader of the DEBUG line gets is that.
        """

        if self.replaying:
            self.replayed += 1
            return
        kind = _CHUNKS.get(str(getattr(update, "session_update", "")))
        if kind is None:
            return
        if kind == "tool_call":
            self.tool_calls += 1
        text = _update_text(update, kind)
        if kind == "text":
            self.text.append(text)
        await self.append(kind, text)

    # -- the two questions an agent may ask ------------------------------

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        """Resolve one permission and answer with the ``option_id`` chosen.

        By ``kind``, never by index, and by
        :func:`~athanore.agents.policies.resolve_permission` rather than
        here: an agent's own turn may not widen its policy (D10).
        """

        option_id = await self._guarded(
            resolve_permission(self.policies, self.ctx, tool_call, options)
        )
        self._count_denial(option_id, options)
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=option_id)
        )

    async def create_elicitation(
        self, message: str, mode: Any, **kwargs: Any
    ) -> AcceptElicitationResponse | DeclineElicitationResponse:
        """Bridge one elicitation onto the request channel, or decline it.

        The SDK hands the mode as an object; 06's request channel wants
        the two facts inside it — is this a form, and what schema does it
        want — so they are unpacked here and everything else is the
        policy's call (05 §Policies).
        """

        form = isinstance(
            mode, (ElicitationFormSessionMode, ElicitationFormRequestMode)
        )
        elicited: Elicited = await self._guarded(
            resolve_elicitation(
                self.policies,
                self.ctx,
                message,
                "form" if form else "url",
                mode.requested_schema if form else None,
            )
        )
        return _elicited(elicited)

    async def complete_elicitation(self, elicitation_id: str, **kwargs: Any) -> None:
        """``elicitation/complete``: accepted and ignored (05 §Policies).

        It tells a client that an elicitation it was showing is over.
        This client showed nothing of its own — the request row is what
        an operator answered, and it was already resolved — so there is
        nothing to take down.
        """

    async def _guarded(self, resolving: Any) -> Any:
        """Await a policy, keeping its failure where ``run()`` can find it.

        The SDK answers the agent with a JSON-RPC error for anything
        raised in here, so an unrecorded :exc:`AgentError` is a run that
        fails silently and reports ``ok``. It is recorded and re-raised:
        the agent still gets its error, and the façade still fails.
        """

        try:
            return await resolving
        except AgentError as exc:
            if self.failure is None:
                self.failure = exc
            _log.warning("agent policy could not be honoured", error=str(exc))
            raise

    def _count_denial(
        self, option_id: str, options: Sequence[PermissionOption]
    ) -> None:
        """Count a ``reject_*`` answer, so a run refused everything shows it.

        By the ``kind`` of the option that was chosen, looked up by id:
        05 §Stats entry counts denials, and a run whose agent was denied
        every tool call is almost certainly failed however it reported
        (20 §Finding 1).
        """

        for option in options:
            if option.option_id == option_id and str(option.kind).startswith("reject"):
                self.denied_permissions += 1
                return

    # -- what this client does not do ------------------------------------
    #
    # `fs/*` and `terminal/*` answer `method_not_found` (05, 20 §Checked
    # and found sound): agents do their own I/O in their own sandbox.
    # They are spelled out rather than left to the protocol base class,
    # whose stubs would answer `null` — a client that says "no such
    # method" is honest; one that says "here is nothing" is a bug the
    # agent cannot see.

    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs: Any
    ) -> NoReturn:
        raise RequestError.method_not_found("fs/write_text_file")

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> NoReturn:
        raise RequestError.method_not_found("fs/read_text_file")

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: list[Any] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> NoReturn:
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> NoReturn:
        raise RequestError.method_not_found("terminal/output")

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> NoReturn:
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> NoReturn:
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> NoReturn:
        raise RequestError.method_not_found("terminal/kill")

    async def ext_method(self, method: str, params: dict[str, Any]) -> NoReturn:
        raise RequestError.method_not_found(f"_{method}")

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        _log.debug("unhandled ACP extension notification", method=method)

    def on_connect(self, conn: Any) -> None:
        """Keep the connection the SDK just built over this client.

        Nothing here uses it — the façade holds its own reference and
        drives the session — but a ``client_class`` that wants to send
        something of its own mid-turn (a ``session/cancel``, a vendor
        extension) has no other way to reach it (20 §Finding 3).
        """

        self.connection = conn


def _elicited(
    elicited: Elicited,
) -> AcceptElicitationResponse | DeclineElicitationResponse:
    """One :data:`~athanore.agents.policies.Elicited` as its ACP response.

    An ``accept`` carries an object matching the requested schema. A
    value that is not one is declined rather than sent: the protocol's
    ``content`` is an object, and an agent handed something else would
    have to guess.
    """

    action, content = elicited
    if action == "accept" and isinstance(content, Mapping):
        return AcceptElicitationResponse(action="accept", content=dict(content))
    if action == "accept":
        _log.warning(
            "elicitation answered with something that is not an object; declining",
            answer=type(content).__name__,
        )
    return DeclineElicitationResponse(action="decline")


def _update_text(update: Any, kind: str) -> str:
    """What one ``session/update`` reads as in the transcript.

    A message or a thought is its content block. A tool call is its
    title — the human-readable line an operator scans for — and a tool
    call update is whatever the tool produced, falling back to the status
    it reported, because "completed" is the whole of what most updates
    say.
    """

    if kind in ("text", "thought"):
        return _content_text(getattr(update, "content", None))
    if kind == "tool_call":
        return str(getattr(update, "title", "") or getattr(update, "tool_call_id", ""))
    parts = [
        _content_text(getattr(item, "content", None))
        for item in getattr(update, "content", None) or []
        if getattr(item, "type", None) == "content"
    ]
    body = "\n".join(part for part in parts if part)
    if body:
        return body
    status = getattr(update, "status", None)
    if status is not None:
        return str(status)
    return str(getattr(update, "title", "") or getattr(update, "tool_call_id", ""))


def _content_text(block: Any) -> str:
    """One ACP content block as text, naming what it was when it is not.

    Non-text blocks — an image, an embedded resource — have no text, and
    dropping them silently would leave a transcript that reads as if the
    agent said nothing at all.
    """

    if block is None:
        return ""
    text = getattr(block, "text", None)
    if text is not None:
        return str(text)
    return f"[{getattr(block, 'type', 'content')}]"


# --------------------------------------------------------------------------
# What one run() accumulates, and what its `finally` has to deal with
# --------------------------------------------------------------------------


@dataclass
class _Session:
    """The mutable half of a run: the child, the counters, the outcome.

    It exists because ``run()``'s ``finally`` has to clean up and account
    for whatever the ``try`` got as far as — a spawn that failed has no
    connection, a turn that timed out has no response — and threading six
    optionals through five methods is how a cleanup path comes to miss
    one.
    """

    started: float
    process: asyncio.subprocess.Process | None = None
    connection: ClientSideConnection | None = None
    client: ACPClient | None = None
    stderr: asyncio.Task[None] | None = None
    session_id: str | None = None
    repair_turns: int = 0
    #: How the run ended, as 05 §Stats entry spells it. ``failed`` until
    #: something says otherwise: a run that stopped where nothing set an
    #: outcome did not succeed.
    status: Literal["ok", "failed"] = "failed"
    reason: StatsReason | None = None
    #: Token counters summed over every turn of this run, ACP's own.
    usage: dict[str, int] = field(default_factory=dict)
    #: The entry that was built for this run, and the guard that keeps it
    #: to one: :func:`record_entry` deduplicates by identity.
    entry: dict[str, Any] | None = None

    def add_usage(self, reported: Any) -> None:
        """Add one turn's ACP ``usage`` to the run's, if it carried one."""

        turn = usage_from_acp(reported)
        if turn is None:
            return
        for key, value in turn.items():
            self.usage[key] = self.usage.get(key, 0) + value


# --------------------------------------------------------------------------
# The façade
# --------------------------------------------------------------------------


class ACPAgent(Agent):
    """An agent façade backed by an ACP subprocess (05 §Agent classes).

    A subclass is configuration and an inlined prompt, and that is the
    whole of what a workflow writes:

    .. code-block:: python

        class Reviewer(ACPAgent):
            command = ["npx", "-y", "pi-acp@0.0.33"]
            system_prompt = "You review one branch."
            output_model = Review
            model = "anthropic/claude-sonnet-4"

    ``command`` is configuration, not vendor knowledge: nothing in this
    package knows what pi or Claude Code is, and the adapters live in
    ``examples/`` (02 §Small core). ``settings.agent_command`` replaces it
    on **every** subclass at spawn time, which is how the example suite
    runs on ``FakeACPAgent`` in CI (05, 13 §Running examples on the fake).
    """

    #: The ACP adapter to spawn. Overridden per instance, and by
    #: ``settings.agent_command`` regardless of subclass.
    command: list[str] = ["npx", "pi-acp"]
    #: Sent as the session config option whose ``category == "model"``.
    model: str | None = None
    #: Sent as the option whose ``category == "thought_level"``.
    thinking: str | None = None
    #: What to do with a permission request (05 §Policies).
    permission_policy: Literal["ask", "auto_allow", "auto_deny"] = "ask"
    #: How long an ``ask`` blocks the turn before the engine answers.
    permission_timeout: float | None = None
    #: What the engine answers with when it does (06 §Timeouts).
    permission_timeout_action: Literal["deny", "allow"] = "deny"
    #: Whether an elicitation reaches the operator, or is declined.
    elicitation_policy: Literal["ask", "decline"] = "ask"
    #: How many follow-up turns a missing submission is worth (05, 19).
    max_repair_turns: int = 2
    #: ``None``: inherit the scrubbed environment. A list: keep only
    #: these names, allow-nothing-by-default (12 §Agents).
    env_allowlist: list[str] | None = None
    #: How this agent reaches its task (05 §Tooling tiers, D63).
    tooling: Literal["auto", "mcp", "native", "http"] = "auto"
    #: The callback class one run is driven through (20 §Finding 3).
    client_class: type[ACPClient] = ACPClient
    #: Where cost and truncation come from, when anything knows (D27).
    stats_provider: SessionStatsProvider | None = None

    def __init__(
        self,
        command: Sequence[str] | None = None,
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        session_id: str | None = None,
    ) -> None:
        if command is not None:
            self.command = list(command)
        #: The agent's workspace. The engine never writes there (12).
        self.cwd = cwd
        #: A session an earlier run left behind, to be continued rather
        #: than a new one opened (23 §Surface, D254). ``AgentResult.
        #: session_id`` is where it comes from, and ``cwd`` has to be the
        #: one the session was opened with — the agent enforces it.
        self.session_id = session_id
        #: This agent's own timeout, or ``settings.agent_timeout``.
        self.timeout = timeout
        #: Environment merged last, so a class may state a variable the
        #: scrub or the allowlist would otherwise have removed.
        self.env = dict(env) if env else {}

    # -- what gets spawned, and with what --------------------------------

    def _command(self, settings: AthanoreSettings) -> list[str]:
        """The argv to spawn: this agent's, or the one setting that wins.

        ``settings.agent_command`` (``ATHANORE_AGENT_COMMAND``) exists for
        one purpose — running every example on ``FakeACPAgent`` with no
        model in the loop — so it overrides **every** ``ACPAgent``
        regardless of subclass, and it is refused in ``athanore.toml`` so
        a production config cannot swap agents by accident (05, 02
        §athanore.toml layout).

        A JSON list arrives as a list; anything else is shell-split, so
        ``ATHANORE_AGENT_COMMAND="python fake.py"`` works from a shell.
        """

        override = settings.agent_command
        if not override:
            return list(self.command)
        argv = list(override) if isinstance(override, list) else shlex.split(override)
        if not argv:
            raise AgentError(
                "settings.agent_command is set but empty; it must name a command"
            )
        _log.info(
            "settings.agent_command overrides the agent's command",
            agent=type(self).__name__,
            configured=list(self.command),
            command=argv,
        )
        return argv

    def _child_env(self, ctx: TaskContext | None) -> dict[str, str]:
        """The environment the child is spawned with (12 §Agents, 20 §4).

        In order, and the order is the rule:

        1. inherit — minus ``CLAUDE_*``, ``CLAUDECODE`` and
           ``CLAUDE_PID`` — or, with an :attr:`env_allowlist`, keep only
           the names it lists and nothing else;
        2. export ``ATHANORE_TASK_URL`` and ``ATHANORE_TASK_TOKEN``, so
           an adapter that reads its environment can keep the token out
           of the prompt entirely (19 §Environment);
        3. merge the explicit ``env``, which therefore wins: it is the
           one thing the workflow author stated by hand.

        A session-scoped variable reaching a child is how one agent comes
        to inherit another's credentials, and it is why the default is a
        scrub rather than a straight inherit.
        """

        if self.env_allowlist is not None:
            allowed = set(self.env_allowlist)
            env = {k: v for k, v in os.environ.items() if k in allowed}
        else:
            env = {k: v for k, v in os.environ.items() if not _scrubbed(k)}
        if ctx is not None:
            env["ATHANORE_TASK_URL"] = task_base(ctx)
            env["ATHANORE_TASK_TOKEN"] = ctx.token
        env.update(self.env)
        return env

    # -- the run ---------------------------------------------------------

    async def run(self, prompt: str = "") -> AgentResult:
        """Spawn the agent, hand it the task, and account for what happened.

        The lifecycle of 05, in order: declare this agent's
        ``output_model`` and ``ask_policy`` on the task for the duration,
        spawn, handshake, open a session — a new one, or the one
        ``session_id`` names — configure it by category, prompt,
        repair while it is worth repairing, map the outcome, and then —
        on every path, including a cancelled one — flush the transcript,
        close the connection, stop the child, and record exactly one
        stats entry.

        Returns a **failed** :class:`AgentResult` for a refusal, a
        cancellation or a truncated final turn; raises
        :exc:`AgentError` for a timeout, a transport failure and a
        missing or invalid submission. Both record their stats first (05
        §AgentResult).
        """

        ctx = maybe_current_task()
        settings = AthanoreSettings()
        session = _Session(started=time.monotonic())
        async with self.declare(ctx):
            try:
                return await self._converse(prompt, ctx, settings, session)
            except asyncio.CancelledError:
                # A shutdown or a cancelled task. The numbers still stand.
                session.reason = "shutdown"
                raise
            finally:
                await self._cleanup(ctx, session)
                await self._record(ctx, session)

    async def _converse(
        self,
        prompt: str,
        ctx: TaskContext | None,
        settings: AthanoreSettings,
        session: _Session,
    ) -> AgentResult:
        """One ACP conversation, with every failure named on the way out.

        The timeout covers the whole conversation rather than one
        ``prompt`` call: ``settings.agent_timeout`` is a run's budget (three
        hours by default), a repair turn is part of the same run, and a
        handshake that never answers would otherwise hang with no bound
        at all.
        """

        try:
            client = self.client_class(self, ctx, _policies(self, settings))
            session.client = client
            await self._spawn(session, settings, ctx)
            async with asyncio.timeout(self.timeout or settings.agent_timeout):
                return await self._exchange(prompt, ctx, session, client)
        except AgentError:
            if session.reason is None:
                session.reason = "transport"
            raise
        except TimeoutError:
            session.reason = "timeout"
            raise AgentError(
                f"the agent did not finish within "
                f"{self.timeout or settings.agent_timeout}s"
            ) from None
        except Exception as exc:
            session.reason = "transport"
            raise AgentError(f"the agent connection failed: {exc}") from exc

    async def _spawn(
        self, session: _Session, settings: AthanoreSettings, ctx: TaskContext | None
    ) -> None:
        """Start the child and put an ACP connection over its stdio."""

        command = self._command(settings)
        session.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=self._child_env(ctx),
            limit=STDOUT_LIMIT,
        )
        _log.debug(
            "agent spawned",
            agent=type(self).__name__,
            command=command,
            pid=session.process.pid,
            cwd=self.cwd,
        )
        session.stderr = asyncio.get_running_loop().create_task(
            _pump_stderr(session.process, type(self).__name__)
        )
        assert session.client is not None
        session.connection = connect_to_agent(
            session.client,
            session.process.stdin,
            session.process.stdout,
            # `elicitation/*` and `PromptResponse.usage` are both still
            # marked UNSTABLE in SDK 0.12.1, and both are specified
            # behaviour here (05 §Policies, §Stats entry). Without this
            # the SDK answers `elicitation/create` with method_not_found.
            use_unstable_protocol=True,
        )

    async def _exchange(
        self,
        prompt: str,
        ctx: TaskContext | None,
        session: _Session,
        client: ACPClient,
    ) -> AgentResult:
        """Handshake, configure, prompt, repair, and map the outcome."""

        conn = session.connection
        assert conn is not None
        initialized = await conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="athanore", version=__version__),
        )
        if initialized.protocol_version != PROTOCOL_VERSION:
            _log.warning(
                "the agent answered a different ACP protocol version",
                agent=type(self).__name__,
                ours=PROTOCOL_VERSION,
                theirs=initialized.protocol_version,
            )
        tier = self._tier(initialized, ctx)
        options = await self._open_session(session, client, initialized, tier, ctx)
        assert session.session_id is not None
        await self._configure(conn, client, session.session_id, options)

        text = await self.render_prompt(prompt, ctx, tier=tier)
        response = await self._prompt(session, client, text)
        response = await self._repair(ctx, session, client, response)
        return await self._outcome(ctx, session, client, response)

    async def _prompt(
        self, session: _Session, client: ACPClient, text: str
    ) -> PromptResponse:
        """One turn: send ``text``, count what it cost, surface a failure.

        The failure check is here rather than at the end of the run
        because a policy that could not be honoured must not be followed
        by a repair turn: the next prompt would be spent on a session
        that is already broken.
        """

        conn = session.connection
        assert conn is not None and session.session_id is not None
        response = await conn.prompt(
            session_id=session.session_id, prompt=[text_block(text)]
        )
        session.add_usage(response.usage)
        if client.failure is not None:
            raise client.failure
        return response

    # -- opening the session, one way or the other ------------------------

    async def _open_session(
        self,
        session: _Session,
        client: ACPClient,
        initialized: InitializeResponse,
        tier: Tier,
        ctx: TaskContext | None,
    ) -> Sequence[Any] | None:
        """Open the session this run is on, and hand back its config options.

        A fresh run is ``session/new`` (05 §Session lifecycle, step 2). A
        run constructed with ``session_id`` continues that session
        instead (:meth:`_continue`). Either way ``session.session_id`` is
        set only once the agent has answered: a run that never joined a
        session has none to name in its stats entry.
        """

        if self.session_id is not None:
            return await self._continue(session, client, initialized, tier, ctx)
        conn = session.connection
        assert conn is not None
        started = await conn.new_session(
            cwd=self.cwd or os.getcwd(), mcp_servers=self._mcp_servers(tier, ctx)
        )
        session.session_id = started.session_id
        return started.config_options

    async def _continue(
        self,
        session: _Session,
        client: ACPClient,
        initialized: InitializeResponse,
        tier: Tier,
        ctx: TaskContext | None,
    ) -> Sequence[Any] | None:
        """Re-open ``session_id`` by whichever method the agent advertised.

        ``session/resume`` when ``sessionCapabilities.resume`` is present,
        else ``session/load`` when ``loadSession`` is, else
        :exc:`AgentError` before anything is prompted (23 §Lifecycle of a
        continued run, step 2; D255). ``resume`` first because it is the
        cheaper of the two and produces nothing to discard; ``load``
        because it is the one every adapter that persists sessions has.
        Both carry the ``cwd`` and the tier's ``mcp_servers`` a
        ``session/new`` would — this task's token, not the one the
        session was opened under (12 §Task tokens).

        The replay a ``load`` produces is dropped by the client under
        :attr:`ACPClient.replaying`, set immediately before the call and
        cleared on every path out of it, with the count logged once at
        DEBUG. There is deliberately **no fallback** to ``session/new``:
        a run that quietly started over would answer with no memory of
        the conversation and report success (23 §Refusal, D254).
        """

        session_id = self.session_id
        assert session_id is not None
        conn = session.connection
        assert conn is not None
        capabilities = initialized.agent_capabilities
        sessions = capabilities.session_capabilities if capabilities else None
        resume = sessions is not None and sessions.resume is not None
        load = capabilities is not None and bool(capabilities.load_session)
        if not resume and not load:
            raise AgentError(
                f"{type(self).__name__} cannot continue a session: the agent "
                "advertises neither session/resume nor session/load"
            )
        cwd = self.cwd or os.getcwd()
        servers = self._mcp_servers(tier, ctx) or []
        try:
            if resume:
                opened: LoadSessionResponse | ResumeSessionResponse
                opened = await conn.resume_session(
                    session_id=session_id, cwd=cwd, mcp_servers=servers
                )
            else:
                client.replaying = True
                try:
                    opened = await conn.load_session(
                        cwd=cwd, session_id=session_id, mcp_servers=servers
                    )
                finally:
                    client.replaying = False
                    _log.debug(
                        "replay discarded",
                        agent=type(self).__name__,
                        session_id=session_id,
                        count=client.replayed,
                    )
        except RequestError as exc:
            raise AgentError(
                f"the agent could not continue session {session_id}: {exc}"
            ) from exc
        session.session_id = session_id
        await client.append("notice", f"continuing session {session_id}")
        return opened.config_options

    # -- the session's configuration -------------------------------------

    def _tier(self, initialized: InitializeResponse, ctx: TaskContext | None) -> Tier:
        """Which of 05's three tooling tiers this run uses (D63).

        ``auto`` reads the ``mcpCapabilities`` the agent just advertised:
        ``mcp`` when it can speak HTTP MCP, ``http`` otherwise. Anything
        else is the class's own choice and is honoured as written —
        ``native`` cannot be detected at all, which is why it is a
        declaration (05 §Tooling tiers).

        The one thing that is overridden is ``mcp`` with no task: the
        server it names is scoped to a task token, so a façade run
        outside a node body has no server to point at and falls back to
        the tier that needs none.
        """

        chosen = self.tooling
        if chosen == "auto":
            capabilities = initialized.agent_capabilities
            mcp = capabilities.mcp_capabilities if capabilities is not None else None
            chosen = "mcp" if mcp is not None and mcp.http else "http"
        if chosen == "mcp" and ctx is None:
            _log.warning(
                "the mcp tier needs a task to point at; falling back to http",
                agent=type(self).__name__,
            )
            return "http"
        return chosen

    def _mcp_servers(self, tier: Tier, ctx: TaskContext | None) -> _McpServers | None:
        """The task server handed to ``session/new`` in the ``mcp`` tier.

        One server, named :data:`~athanore.agents.policies.MCP_SERVER_NAME`
        — the name the permission exemption matches on — with the task
        token in a header. The token travels here instead of in the
        prompt, which is the whole reason the tier exists (05 §Tooling
        tiers, 12 §Task tokens).
        """

        if tier != "mcp" or ctx is None:
            return None
        return [
            HttpMcpServer(
                type="http",
                name=MCP_SERVER_NAME,
                url=f"{ctx.api_base}/mcp/agent",
                headers=[HttpHeader(name=TOKEN_HEADER, value=ctx.token)],
            )
        ]

    def _resolve_config_id(
        self, options: Sequence[Any] | None, category: str
    ) -> str | None:
        """The advertised config option id for ``category`` (20 §Finding 2).

        By category, because the ids differ per agent: pi calls the
        thought-level option ``thought_level`` and claude-agent-acp calls
        it ``effort``, and the MVP sent pi's id to Claude, had it
        rejected, and swallowed the rejection (D11).

        An agent that advertises no categories at all is met halfway: an
        option whose *id* is the category name is taken, which is the
        fallback 20 names. ``None`` when the session advertised neither,
        and the caller makes that visible rather than quietly not setting
        a model.
        """

        for option in options or []:
            if option.category == category:
                return option.id
        for option in options or []:
            if option.id == category:
                return option.id
        return None

    async def _configure(
        self,
        conn: ClientSideConnection,
        client: ACPClient,
        session_id: str,
        options: Sequence[Any] | None,
    ) -> None:
        """Set ``model`` and ``thinking`` on the session, loudly (D11).

        A category the agent does not advertise, and a value it refuses,
        are both **logged at WARNING and written to the transcript as a
        ``notice``**. Neither fails the run — the agent will answer on its
        own default — and neither is silent, because a whole build
        running on the wrong model is what silence bought last time.

        ``options`` is the ``configOptions`` of whichever response opened
        the session — ``session/new``, ``load`` or ``resume`` — and a
        continued session is re-told the class's choices exactly as a new
        one is: the class is the configuration, and a session that
        drifted from it is not the one the author declared (23).
        """

        for category, attribute in CONFIG_CATEGORIES.items():
            value = getattr(self, attribute)
            if not value:
                continue
            config_id = self._resolve_config_id(options, category)
            if config_id is None:
                await self._rejected(
                    client,
                    category,
                    value,
                    f"the agent advertises no {category} option",
                )
                continue
            try:
                await conn.set_config_option(
                    config_id=config_id, session_id=session_id, value=value
                )
            except Exception as exc:
                await self._rejected(client, category, value, str(exc))

    async def _rejected(
        self, client: ACPClient, category: str, value: str, why: str
    ) -> None:
        """One config option that did not take, in the log and on screen."""

        _log.warning(
            "agent config option rejected",
            agent=type(self).__name__,
            category=category,
            value=value,
            error=why,
        )
        await client.append(
            "notice",
            f"{category} could not be set to {value!r}: {why}. "
            "The agent is answering on its own default.",
        )

    # -- the repair loop --------------------------------------------------

    async def _repair(
        self,
        ctx: TaskContext | None,
        session: _Session,
        client: ACPClient,
        response: PromptResponse,
    ) -> PromptResponse:
        """Ask again, on the same session, while it is worth asking (05, 19).

        Worth asking is :func:`~athanore.agents.submissions.needs_repair`:
        the turn ended of its own accord, a shape was declared, and no
        valid submission is stored. Not a refusal, not a cancellation —
        those are outcomes, and another turn would spend the budget on
        one that cannot succeed.

        Each turn emits ``submission.repair`` and a ``notice`` chunk, so
        the run shows that it took two attempts to get a result rather
        than looking like one clean turn. The latest valid submission
        wins, which is what makes the second one the answer.
        """

        while session.repair_turns < self.max_repair_turns and await needs_repair(
            ctx, response.stop_reason
        ):
            assert ctx is not None  # needs_repair is False without a context
            session.repair_turns += 1
            reason = "rejected" if ctx.last_rejection else "nothing_submitted"
            await ctx.services.submissions.repair(session.repair_turns, reason)
            await client.append(
                "notice",
                f"no valid submission ({reason.replace('_', ' ')}); "
                f"asking again, repair turn {session.repair_turns} of "
                f"{self.max_repair_turns}.",
            )
            response = await self._prompt(
                session, client, repair_prompt(ctx, session.repair_turns)
            )
        return response

    # -- the outcome -------------------------------------------------------

    async def _outcome(
        self,
        ctx: TaskContext | None,
        session: _Session,
        client: ACPClient,
        response: PromptResponse,
    ) -> AgentResult:
        """Map how the turn ended onto a result, and build the stats entry.

        Three failures a body may route on, returned rather than raised
        (05 §AgentResult):

        - ``refusal`` and ``cancelled`` — the agent said no, or was
          stopped;
        - **truncated** — the final turn hit the model's output limit.
          ACP says so with ``max_tokens``; a provider that can read the
          agent's own session file says so with ``final_stop_reason ==
          "length"``, which is the case ACP cannot see, because a turn
          consumed by reasoning is reported as ``end_turn`` (D27, 05
          §Truncation).

        Anything else attaches the submission, and a missing or invalid
        one is the :exc:`AgentError` the body cannot route on.
        """

        stop = response.stop_reason
        result = AgentResult(
            text="".join(client.text),
            session_id=session.session_id,
            stop_reason=stop,
        )
        failure: StatsReason | None = None
        if stop in ("refusal", "cancelled"):
            failure = stop
        elif stop == "max_tokens" or await self._truncated(session):
            failure = "truncated"

        if failure is not None:
            result.status = "failed"
            result.error = failure
            session.status, session.reason = "failed", failure
        else:
            try:
                await attach(ctx, result)
            except AgentError:
                session.reason = "no_submission"
                raise
            session.status, session.reason = "ok", None
        result.stats = await self._entry(ctx, session, client)
        return result

    async def _truncated(self, session: _Session) -> bool:
        """Whether the provider says the final turn was cut off (D27).

        ``None`` — no provider, no session, a provider that could not read
        the file — is *not determined*, and not determined is not
        truncated: this decides whether a run is reported failed, and
        guessing it from nothing would fail runs that worked.
        """

        provider = self.stats_provider
        if provider is None or session.session_id is None:
            return False
        try:
            return await provider.final_stop_reason(session.session_id, self.cwd) == (
                "length"
            )
        except Exception:
            _log.warning(
                "the stats provider could not report a stop reason",
                session_id=session.session_id,
                exc_info=True,
            )
            return False

    # -- cleanup and accounting -------------------------------------------

    async def _cleanup(self, ctx: TaskContext | None, session: _Session) -> None:
        """Flush the transcript, close the connection, stop the child.

        Each step is guarded on its own: a connection that will not close
        must not leave a subprocess behind, and neither must stop the
        stats entry from being written. The transcript is **flushed, not
        closed** — it belongs to the attempt, and the runner closes it
        when the attempt ends, so a body running two agents in sequence
        still has somewhere to write.
        """

        if ctx is not None:
            with _logged("the transcript could not be flushed"):
                await ctx.services.stream.flush()
        if session.connection is not None:
            with _logged("the agent connection could not be closed"):
                await session.connection.close()
        if session.stderr is not None:
            session.stderr.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await session.stderr
        if session.process is not None:
            with _logged("the agent subprocess could not be stopped"):
                await _stop(session.process)

    async def _entry(
        self, ctx: TaskContext | None, session: _Session, client: ACPClient | None
    ) -> dict[str, Any]:
        """Build this run's stats entry, once (05 §Stats entry).

        Every unknown is left out rather than zero-filled, which is what
        :func:`~athanore.agents.stats.build_entry` is for; what is added
        here is the second source. ACP's ``usage`` — summed over the
        turns of this run, repair turns included — wins for tokens, and
        the provider supplies cost and the model that actually answered
        (:func:`~athanore.agents.stats.merge_usage`). Not on a continued
        run: a provider reports a whole *session*, and a continued run is
        a fraction of one whose size it cannot know, so there the tokens
        are ACP's or omitted and the model is the class's (23 §Stats,
        D256).

        Kept on the session, so the ``finally`` that records it and the
        result that carries it hold the same object and it can only be
        written once.
        """

        if session.entry is not None:
            return session.entry
        provider_stats = None
        provider = self.stats_provider
        if (
            provider is not None
            and session.session_id is not None
            and self.session_id is None
        ):
            try:
                provider_stats = await provider.stats(session.session_id, self.cwd)
            except Exception:
                _log.warning(
                    "the stats provider could not report usage",
                    session_id=session.session_id,
                    exc_info=True,
                )
        session.entry = build_entry(
            node="?" if ctx is None else ctx.node,
            attempt=0 if ctx is None else ctx.attempt,
            status=session.status,
            reason=session.reason,
            duration_s=time.monotonic() - session.started,
            model=self.model,
            usage=merge_usage(session.usage or None, provider_stats),
            tool_calls=None if client is None else client.tool_calls,
            session_id=session.session_id,
            repair_turns=session.repair_turns,
            denied_permissions=0 if client is None else client.denied_permissions,
        )
        return session.entry

    async def _record(self, ctx: TaskContext | None, session: _Session) -> None:
        """Record the entry, exactly once, and never raise (05 §Stats entry).

        Called from ``run()``'s ``finally``, so it runs on the path that
        returned a result and on the path that is about to raise —
        :func:`~athanore.agents.stats.record_entry` deduplicates by the
        identity of the entry, and :meth:`_entry` hands back the same one
        every time.
        """

        try:
            entry = await self._entry(ctx, session, session.client)
            await record_entry(ctx, entry)
        except Exception:
            _log.error(
                "the agent stats entry could not be built",
                agent=type(self).__name__,
                exc_info=True,
            )


# --------------------------------------------------------------------------
# The subprocess
# --------------------------------------------------------------------------


def _scrubbed(name: str) -> bool:
    """Whether this variable is session-scoped state a child must not get."""

    return name in SCRUBBED_NAMES or name.startswith(SCRUBBED_PREFIXES)


async def _pump_stderr(process: asyncio.subprocess.Process, agent: str) -> None:
    """Log the child's stderr at DEBUG, capped, and drain the rest.

    Capped because a crashing adapter can produce megabytes and the
    structured log is not a place to put them (12 §Agents). Drained past
    the cap rather than abandoned, because a full pipe blocks the child
    on its next write — a silent hang that looks exactly like a slow
    model.
    """

    stream = process.stderr
    if stream is None:  # pragma: no cover - always piped by `_spawn`
        return
    written = 0
    while True:
        line = await stream.readline()
        if not line:
            return
        if written >= STDERR_CAP:
            continue
        written += len(line)
        _log.debug(
            "agent stderr",
            agent=agent,
            pid=process.pid,
            line=line.decode("utf-8", "replace").rstrip(),
        )
        if written >= STDERR_CAP:
            _log.debug("agent stderr capped", agent=agent, pid=process.pid)


async def _stop(process: asyncio.subprocess.Process) -> None:
    """End the child and reap it: terminate, then kill after five seconds.

    Always waited on, so ``returncode`` is set when this returns and the
    run leaves no zombie behind (T039a). Its stdin is closed first, which
    is how a well-behaved ACP adapter is asked to exit on its own.
    """

    if process.returncode is not None:
        await process.wait()
        return
    if process.stdin is not None:
        with suppress(Exception):
            process.stdin.close()
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=KILL_AFTER)
        return
    except TimeoutError:
        _log.warning("agent did not exit; killing it", pid=process.pid)
    with suppress(ProcessLookupError):
        process.kill()
    await process.wait()


@contextmanager
def _logged(message: str) -> Iterator[None]:
    """A cleanup step whose failure is a log line, not a lost exit path.

    ``run()``'s ``finally`` has four things to do and every one of them
    must happen: a connection that will not close must not leave the
    subprocess running, and neither may stop the stats entry from being
    written. :func:`contextlib.suppress` would hide what went wrong; this
    says what it was. A cancellation is not suppressed — it is the
    attempt being stopped, not a step that failed.
    """

    try:
        yield
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.warning(message, exc_info=True)
