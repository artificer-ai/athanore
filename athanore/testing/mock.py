"""Agent doubles with no subprocess, and a scripted stats provider.

05 §Testing doubles. :class:`FakeACPAgent` is the fixture for everything
that is *about* the ACP wire; these three are for everything that is not.
An engine test about fan-in wants a node body that submits a value and
returns, not a process to spawn, and a stats test wants an entry with
known numbers in it, not a session file to parse.

They are doubles, not shortcuts (`AGENTS.md` §Quality bar). Each one
takes the same path through the same objects as the real façade does:
:class:`MockAgent` declares its ``output_model`` on the
:class:`~athanore.engine.context.TaskContext` for the duration of the
run, **submits over HTTP to the agent API** with the task token — the
same endpoint, the same validation, and the same 422 that records the
rejection and sets ``ctx.last_rejection`` — and attaches the latest
submission at the end. :class:`StatsMockAgent` records exactly one
entry per ``run()``, on the success path and on the failure path, through
:func:`~athanore.agents.stats.record_entry`. What they leave out is the
subprocess.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, get_args

import httpx
from pydantic import BaseModel

from athanore.agents.base import Agent, AgentError, AgentResult, task_base
from athanore.agents.stats import (
    SessionStats,
    StatsReason,
    build_entry,
    record_entry,
)
from athanore.agents.submissions import attach
from athanore.engine.context import TaskContext, maybe_current_task

__all__ = ["SUBMIT_TIMEOUT", "FakeStatsProvider", "MockAgent", "StatsMockAgent"]

#: How long :class:`MockAgent` gives the agent API to answer a
#: submission. Generous, because it is never the thing under test: a
#: double that timed out would report a failure about the fixture rather
#: than about the code being exercised.
SUBMIT_TIMEOUT = 30.0

#: The keys of a scripted stats dict that are :func:`build_entry` keyword
#: arguments, and the ones that belong under its ``usage``. Between them
#: they are every field of 05 §Stats entry a double gets to script; the
#: rest — node, attempt, status, duration — are measured, not scripted.
ENTRY_FIELDS = frozenset(
    {
        "model",
        "tool_calls",
        "session_id",
        "repair_turns",
        "denied_permissions",
        "reason",
    }
)
USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "total_tokens", "cost"})


class MockAgent(Agent):
    """An agent run without an agent (05 §Testing doubles).

    Each argument is one thing a real run does, and may be a value or a
    zero-argument callable — a body that runs the same agent on several
    attempts scripts the attempts by closing over a counter.

    ``output``
        What :attr:`AgentResult.output` carries. The shortest double:
        nothing is submitted and nothing is stored.
    ``submit``
        A payload to submit, over HTTP to
        ``{ctx.api_base}/api/agent/tasks/{id}/submit`` with the task
        token, which is the round trip a real agent makes. The endpoint
        validates it against the declared ``output_model``, accepts it
        when it fits and rejects it — ``submission.rejected``,
        ``ctx.last_rejection`` — when it does not.
    ``log``
        A deliverable to append to the run's work log, author ``agent``.
    ``stream``
        Transcript chunks, as strings (kind ``text``) or ``(kind, text)``
        pairs, appended through ``ctx.services.stream`` with
        ``stream_delay`` seconds between them.
    ``fail``
        A message. The run raises :exc:`AgentError` with it and does
        nothing else, which is the transport failure a body sees.
    """

    def __init__(
        self,
        output: Any | Callable[[], Any] | None = None,
        submit: Any | Callable[[], Any] | None = None,
        log: str | Callable[[], str] | None = None,
        stream: Sequence[str | tuple[str, str]] | None = None,
        fail: str | None = None,
        *,
        text: str = "mock agent output",
        stream_delay: float = 0.0,
    ) -> None:
        self._output = output
        self._submit = submit
        self._log = log
        self._stream = list(stream) if stream is not None else None
        self._fail = fail
        self._text = text
        self._stream_delay = stream_delay
        #: The last prompt this agent was handed, for the tests that assert
        #: on prompt assembly without an ACP session in the way.
        self.prompt: str = ""

    async def run(self, prompt: str = "") -> AgentResult:
        self.prompt = prompt
        ctx = maybe_current_task()
        async with self.declare(ctx):
            if self._fail is not None:
                raise AgentError(self._fail)
            await self._stream_chunks(ctx)
            await self._append_log(ctx)
            await self._submit_payload(ctx)
            result = AgentResult(text=self._text, stop_reason="end_turn")
            output = _value(self._output)
            if output is not None:
                result.output = output
                return result
            return await attach(ctx, result)

    async def _stream_chunks(self, ctx: TaskContext | None) -> None:
        if not self._stream or ctx is None:
            return
        for chunk in self._stream:
            if self._stream_delay:
                await asyncio.sleep(self._stream_delay)
            kind, text = ("text", chunk) if isinstance(chunk, str) else chunk
            await ctx.services.stream.append(kind, text)

    async def _append_log(self, ctx: TaskContext | None) -> None:
        text = _value(self._log)
        if text is None:
            return
        if ctx is None:
            raise AgentError("MockAgent(log=…) needs a task context")
        await ctx.services.log.append(str(text), author="agent")

    async def _submit_payload(self, ctx: TaskContext | None) -> None:
        """Submit the way a real agent submits: over HTTP, with the token.

        ``POST {ctx.api_base}/api/agent/tasks/{id}/submit`` carrying
        ``X-Athanore-Token`` — the same round trip an ACP subprocess
        makes from its curl line, and the same endpoint that validates
        against the declared ``output_model``, stores the fit and records
        the rejection a repair turn quotes (08 §Agent-facing). The double
        leaves out
        the subprocess and nothing else, so the decision about whether a
        payload is acceptable is not one this class gets to make.

        A 422 is a submission that did not fit: it is the endpoint's
        answer, it has already written ``submission.rejected`` and
        ``ctx.last_rejection``, and the run goes on to fail in
        :func:`~athanore.agents.submissions.attach` for want of a valid
        submission — which is what a real agent's unrepaired misfit does
        too. Any other refusal is the double being pointed at a server
        that will not take its work, and it is raised rather than passed
        over.
        """

        payload = _value(self._submit)
        if payload is None:
            return
        if ctx is None:
            raise AgentError("MockAgent(submit=…) needs a task context")
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        url = f"{task_base(ctx)}/submit"
        try:
            async with httpx.AsyncClient(timeout=SUBMIT_TIMEOUT) as client:
                response = await client.post(
                    url, json=payload, headers={"X-Athanore-Token": ctx.token}
                )
        except httpx.HTTPError as exc:
            raise AgentError(f"could not reach the agent API at {url}: {exc}") from exc
        if response.status_code in (200, 422):
            return
        raise AgentError(
            f"the agent API refused this submission: "
            f"{response.status_code} {response.text}"
        )


class StatsMockAgent(MockAgent):
    """A :class:`MockAgent` that also records the entry a façade records.

    The sanctioned double for the engine-level stats tests: exactly one
    entry per ``run()``, on the way out of a success **and** on the way
    out of a failure, written through the same
    :func:`~athanore.agents.stats.record_entry` the ACP façade calls from
    its ``finally``. ``node``, ``attempt``, ``status`` and ``duration_s``
    are measured from the context and the clock; everything in ``stats``
    is what a real provider would have supplied.

    ``fail`` is the failure to record: ``True`` for a plain transport
    failure, or one of 05's reasons (``"refusal"``, ``"timeout"``, …) to
    record that. The run then raises :exc:`AgentError`, after recording —
    which is the order the façade uses, and the reason a failed attempt
    still has numbers against it.
    """

    def __init__(
        self,
        stats: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None,
        fail: bool | str = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if isinstance(fail, str) and fail not in get_args(StatsReason):
            raise ValueError(
                f"{fail!r} is not one of 05's failure reasons: "
                f"{', '.join(get_args(StatsReason))}"
            )
        self._stats = stats
        self._fail_stats = fail

    async def run(self, prompt: str = "") -> AgentResult:
        ctx = maybe_current_task()
        started = time.monotonic()
        if self._fail_stats:
            fail = self._fail_stats
            reason = fail if isinstance(fail, str) else "transport"
            entry = self._entry(ctx, "failed", reason, started)
            await record_entry(ctx, entry)
            raise AgentError(f"mock agent failed: {reason}")
        try:
            result = await super().run(prompt)
        except AgentError:
            await record_entry(ctx, self._entry(ctx, "failed", "transport", started))
            raise
        entry = self._entry(ctx, "ok", None, started)
        await record_entry(ctx, entry)
        result.stats = entry
        return result

    def _entry(
        self,
        ctx: TaskContext | None,
        status: str,
        reason: str | None,
        started: float,
    ) -> dict[str, Any]:
        """One 05 §Stats entry: the measured fields plus the scripted ones."""

        scripted = dict(_value(self._stats) or {})
        unknown = sorted(
            key for key in scripted if key not in ENTRY_FIELDS | USAGE_FIELDS
        )
        if unknown:
            raise ValueError(
                f"StatsMockAgent(stats=…): unknown field(s) {', '.join(unknown)}; "
                f"expected {', '.join(sorted(ENTRY_FIELDS | USAGE_FIELDS))}"
            )
        usage = {
            key: scripted.pop(key) for key in list(scripted) if key in USAGE_FIELDS
        }
        scripted.setdefault("reason", reason)
        return build_entry(
            node="?" if ctx is None else ctx.node,
            attempt=0 if ctx is None else ctx.attempt,
            status="ok" if status == "ok" else "failed",
            duration_s=time.monotonic() - started,
            usage=usage or None,
            **scripted,
        )


class FakeStatsProvider:
    """A :class:`~athanore.agents.stats.SessionStatsProvider` from a script.

    What no protocol carries — the cost of a session, and whether its
    final turn was cut off at the model's token limit — arrives through a
    provider (D27), which means the truncation path and the cost path can
    only be tested with one. This is that provider with the vendor
    removed: it answers with what it was handed.

    ``None`` for either is *not determined*, and it is a real answer: it
    is what an :class:`ACPAgent` with no provider sees, and what a
    provider that could not find the session file returns.
    """

    def __init__(
        self,
        stats: SessionStats | Mapping[str, Any] | None = None,
        stop_reason: str | None = None,
    ) -> None:
        if isinstance(stats, Mapping):
            stats = SessionStats.model_validate(dict(stats))
        self._stats = stats
        self._stop_reason = stop_reason
        #: Every ``(session_id, cwd)`` this provider was asked about, in
        #: order, so a test can assert the façade asked at all.
        self.calls: list[tuple[str, str | None]] = []

    async def stats(self, session_id: str, cwd: str | None) -> SessionStats | None:
        self.calls.append((session_id, cwd))
        return self._stats

    async def final_stop_reason(self, session_id: str, cwd: str | None) -> str | None:
        self.calls.append((session_id, cwd))
        return self._stop_reason


def _value(source: Any) -> Any:
    """A scripted value, or the result of calling for one."""

    return source() if callable(source) else source
