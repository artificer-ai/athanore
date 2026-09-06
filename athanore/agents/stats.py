"""What one agent run cost, recorded once and never invented.

05 §Stats entry is the field list, D46 is where the entry is stored, and
D27 is why the two fields no protocol carries — cost, and whether the
final turn was cut off at the model's token limit — arrive through a
:class:`SessionStatsProvider` rather than out of this package. The MVP
read pi's session JSONL from ``~/.pi/agent/sessions`` to get them; that
is vendor knowledge, so v1 states the protocol here and ships the pi
implementation in ``examples/pi/stats.py`` (T040).

**Unknown is omitted.** Every helper here drops a field it cannot
determine instead of writing a zero (`AGENTS.md` §Real data only, 01). A
``0`` in this entry is a lie that propagates: ``RunStats`` sums the
per-attempt entries, so one invented zero cost makes a run's total a
number nobody measured, and one invented zero token count makes it
smaller than it was. A real zero — a tool-call count of none, a
provider reporting ``$0.0000`` — is data and is kept.

**Two sources, one precedence.** Tokens may arrive twice: from the ACP
prompt response's ``usage`` field (still marked UNSTABLE in SDK 0.12.1)
and from the provider reading the agent's own session file. They
disagree routinely — the provider sums per-message usage over a session
that may have started before this run — so the precedence is fixed once,
in :func:`merge_usage`, rather than decided per call site: **ACP wins for
tokens, the provider supplies cost** (and the model it reports, which the
agent class only guesses at). Neither source is required.

**Recording never fails a run.** :func:`record_entry` is called from the
``finally`` of a façade's ``run()`` (T039a), on the success path and on
every failure path. A task that did its work must not be failed by the
bookkeeping about it, so the one transaction is guarded and its errors
go to the structured log. It is also guarded against being called twice
with the same entry, because that same ``finally`` runs on paths that
have already recorded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol
from weakref import ReferenceType, ref

from pydantic import BaseModel

from athanore.engine.context import TaskContext
from athanore.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "SessionStats",
    "SessionStatsProvider",
    "StatsReason",
    "StatsStatus",
    "build_entry",
    "format_stats_line",
    "merge_usage",
    "record_entry",
    "usage_from_acp",
]

#: How the entry says the run ended (05 §Stats entry).
StatsStatus = Literal["ok", "failed"]

#: Why it failed, with ``status="failed"`` (05 §Stats entry). Mirrored by
#: ``events.payloads.AgentStats``, which is what refuses a value outside
#: this list when the event is published; stated here as well so that a
#: call site is checked where it is written rather than where it lands.
StatsReason = Literal[
    "refusal",
    "cancelled",
    "truncated",
    "timeout",
    "shutdown",
    "transport",
    "no_submission",
]

#: The three counters the ACP prompt response carries, in the order the
#: SDK names them. All three or nothing: a partial object is a shape this
#: code does not understand, not a measurement.
_ACP_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


class SessionStats(BaseModel):
    """What a provider could read about one session (05 §Truncation).

    Every field is optional, and ``None`` means *not determined* — a
    provider that found the session file but no cost in it leaves ``cost``
    unset rather than claiming zero. ``model`` is the provider's, and it
    beats the one the agent class was configured with: the class says
    what was asked for, the session says what answered.
    """

    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


class SessionStatsProvider(Protocol):
    """Vendor knowledge about a finished session, kept out of the package.

    ``ACPAgent.stats_provider`` defaults to ``None``: without one, tokens
    come from the ACP ``usage`` field when the agent sends it and are
    omitted when it does not, and there is no truncation detection. An
    example implementation ships in ``examples/pi`` (D27).

    ``cwd`` is the working directory the session ran in, because a
    provider may key its store by it, and it is ``None`` when the façade
    was given none.
    """

    async def stats(self, session_id: str, cwd: str | None) -> SessionStats | None:
        """Token counts, cost and model for ``session_id``, if readable."""
        ...

    async def final_stop_reason(self, session_id: str, cwd: str | None) -> str | None:
        """The last turn's stop reason — ``"length"`` means truncated."""
        ...


def usage_from_acp(usage: Any) -> dict[str, int] | None:
    """The ACP prompt response's ``usage``, or ``None``.

    ``PromptResponse.usage`` is UNSTABLE in SDK 0.12.1 and absent
    entirely from some adapters, so the read is by ``getattr`` (or by key,
    for an adapter that hands back a plain object) and a missing field is
    an absent measurement rather than an error.

    All three counters or nothing. A response carrying two of them is not
    a response this function knows how to read, and guessing the third —
    from the other two, or from zero — is the invention the whole module
    exists to avoid. ``bool`` is excluded explicitly: it is an ``int`` to
    Python and a mistake here.
    """

    if usage is None:
        return None
    out: dict[str, int] = {}
    for field in _ACP_FIELDS:
        if isinstance(usage, Mapping):
            value = usage.get(field)
        else:
            value = getattr(usage, field, None)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        out[field] = value
    return out


def merge_usage(
    acp: Mapping[str, int] | None, provider: SessionStats | None
) -> dict[str, Any] | None:
    """One set of measurements out of the two sources (05 §Stats entry).

    **ACP wins for tokens**: it is what this run's turns reported, and it
    is honoured even when the provider found nothing, because it is real
    data the agent sent. The provider is the fallback for tokens, and the
    only source of ``cost`` and of the model that actually answered.

    ``total_tokens`` is always input + output. The ACP total is used when
    it is non-zero and the derived sum otherwise (an adapter that fills
    ``total`` with a zero it did not measure); the provider's tokens are
    only totalled when both sides are known, because half a sum is not a
    total. Cache reads and context re-reads are deliberately outside it:
    summing a per-turn "total" that includes the re-read context would
    multiply-count the same tokens once per turn.

    Returns ``None`` when neither source said anything at all, which is
    what :func:`build_entry` writes no token fields for.
    """

    out: dict[str, Any] = {}
    if acp is not None:
        out["input_tokens"] = acp["input_tokens"]
        out["output_tokens"] = acp["output_tokens"]
        out["total_tokens"] = (
            acp["total_tokens"] or acp["input_tokens"] + acp["output_tokens"]
        )
    elif provider is not None:
        if provider.input_tokens is not None:
            out["input_tokens"] = provider.input_tokens
        if provider.output_tokens is not None:
            out["output_tokens"] = provider.output_tokens
        if "input_tokens" in out and "output_tokens" in out:
            out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    if provider is not None:
        if provider.cost is not None:
            out["cost"] = provider.cost
        if provider.model:
            out["model"] = provider.model
    return out or None


def build_entry(
    *,
    node: str,
    attempt: int,
    status: StatsStatus,
    duration_s: float,
    reason: StatsReason | None = None,
    model: str | None = None,
    usage: Mapping[str, Any] | None = None,
    tool_calls: int | None = None,
    session_id: str | None = None,
    repair_turns: int = 0,
    denied_permissions: int = 0,
) -> dict[str, Any]:
    """The stats entry for one ``run()``, with its unknowns left out.

    ``node``, ``attempt``, ``status`` and ``duration_s`` are always
    present: the façade knows all four whatever happened, and 18 makes
    them required in the ``agent.stats`` payload. Everything else is
    written only when it was determined — the assertion a test makes here
    is that the *key is absent*, not that it is ``None``.

    ``usage`` is :func:`merge_usage`'s dict. ``model`` is the agent
    class's configured model and is the fallback: what the provider
    reported answered the prompt, what the class holds was requested, and
    a rejected config option means those differ (D11).

    ``repair_turns`` and ``denied_permissions`` are counts, and a count of
    none is written as nothing: there is no repair to report on a run that
    needed none, and 05 asks for ``denied_permissions`` "when > 0".
    ``tool_calls`` is not one of those — a run that called no tool
    measured zero calls, and that is a fact worth keeping.

    ``duration_s`` is rounded to whole seconds, which is the resolution
    the work-log line quotes and the resolution an agent run is worth
    measuring at.
    """

    entry: dict[str, Any] = {"node": node, "attempt": attempt, "status": status}
    if reason:
        entry["reason"] = reason
    if session_id:
        entry["session_id"] = session_id
    entry["duration_s"] = int(round(duration_s))
    if tool_calls is not None:
        entry["tool_calls"] = tool_calls
    if repair_turns:
        entry["repair_turns"] = repair_turns
    if denied_permissions:
        entry["denied_permissions"] = denied_permissions

    usage = usage or {}
    for field in _ACP_FIELDS:
        if usage.get(field) is not None:
            entry[field] = usage[field]
    if usage.get("cost") is not None:
        entry["cost"] = usage["cost"]

    reported = usage.get("model") or model
    if reported:
        entry["model"] = reported
    return entry


def format_stats_line(entry: Mapping[str, Any]) -> str:
    """The ``[stats]`` work-log line, the MVP's text form unchanged (05).

    .. code-block:: text

        [stats] node=qa attempt=2 ok — model=llama-server/qwen3.8-27b,
        tokens=12,406 in / 1,204 out / 13,610 total, tools=23 calls,
        repairs=1, cost=$0.0000, 142s, session=01a01646

    A failed run carries its reason in parentheses after the status. An
    unknown field is simply absent, never a ``0`` placeholder — and when
    only one side of a token pair is real (a provider whose session file
    has usage on some assistant messages and not others), the missing side
    is the ``n`` marker rather than a zero that would read as a
    measurement.
    """

    head = f"[stats] node={entry.get('node', '?')}"
    if entry.get("attempt") is not None:
        head += f" attempt={entry['attempt']}"
    head += f" {entry.get('status', '?')}"
    if entry.get("status") == "failed" and entry.get("reason"):
        head += f" ({entry['reason']})"

    parts: list[str] = []
    if entry.get("model"):
        parts.append(f"model={entry['model']}")
    if "input_tokens" in entry or "output_tokens" in entry:
        tokens = "tokens="
        tokens += f"{entry['input_tokens']:,} in" if "input_tokens" in entry else "n in"
        tokens += " / "
        tokens += (
            f"{entry['output_tokens']:,} out" if "output_tokens" in entry else "n out"
        )
        if "total_tokens" in entry:
            tokens += f" / {entry['total_tokens']:,} total"
        parts.append(tokens)
    if entry.get("tool_calls") is not None:
        parts.append(f"tools={entry['tool_calls']} calls")
    if entry.get("repair_turns"):
        parts.append(f"repairs={entry['repair_turns']}")
    if entry.get("cost") is not None:
        parts.append(f"cost=${entry['cost']:.4f}")
    if entry.get("duration_s") is not None:
        parts.append(f"{entry['duration_s']}s")
    if entry.get("session_id"):
        parts.append(f"session={str(entry['session_id'])[:8]}")
    if not parts:
        return head
    return head + " — " + ", ".join(parts)


async def record_entry(ctx: TaskContext | None, entry: Mapping[str, Any]) -> bool:
    """Record ``entry`` for this attempt, once, without ever raising.

    One transaction writes all three of 05's destinations — the
    ``[stats]`` work-log line (author ``engine``, kind ``stats``), the
    ``tasks.stats`` column D46 makes a run's totals a ``SUM`` over, and
    the ``agent.stats`` event — because they are one fact and a reader
    that saw two of them would be reading a run that half-finished.
    ``ctx.services.stats`` owns that transaction: a façade reaches the
    store only through :class:`~athanore.engine.context.TaskContext` (02
    §Layering).

    Returns whether it wrote. Two things make that ``False``:

    - **Nothing to record it against.** An agent run outside a node body
      has no task, no log and no event; the entry goes to the structured
      log so the numbers are not simply lost.
    - **This entry was already recorded.** A façade's ``finally`` runs on
      paths that recorded on the way out — the outcome mapping records
      before it raises ``AgentError`` (T039a) — so the guard is on the
      identity of the entry, not on the context: a body that runs two
      agents in sequence builds two entries and records both, and a
      second call with the one entry a ``run()`` built is the double
      write this exists to stop.

    A failure of the write itself is logged at ``error`` and returns
    ``False``. It must not propagate: this is called from a ``finally``,
    where an exception would replace the outcome the body was about to be
    given — a task that succeeded failed by the accounting of it.
    """

    if ctx is None:
        _log.warning("agent stats recorded outside a task context", stats=dict(entry))
        return False
    if _already_recorded(ctx, entry):
        return False
    _mark_recorded(ctx, entry)
    try:
        await ctx.services.stats.record(dict(entry), text=format_stats_line(entry))
    except Exception:
        _log.error(
            "agent stats could not be recorded",
            task_id=ctx.task_id,
            node=ctx.node,
            stats=dict(entry),
            exc_info=True,
        )
        return False
    return True


#: Which entries have been recorded, for the attempts still running.
#:
#: The identity of the entry object is the key, because "once per
#: ``run()``" is a property of the thing being recorded rather than of a
#: scope this module can see: ``record_entry`` is called from a
#: ``finally``, and the call site that already recorded on the way to
#: raising is a different frame with the same dict in hand. The weak
#: reference to the context is what bounds the list — an attempt that has
#: been collected can have nothing left to record — so a server running
#: for weeks keeps one row per live attempt and not one per agent run it
#: has ever made.
_recorded: list[tuple[ReferenceType[TaskContext], Mapping[str, Any]]] = []


def _already_recorded(ctx: TaskContext, entry: Mapping[str, Any]) -> bool:
    """Whether this exact entry has been recorded for this attempt."""

    _recorded[:] = [row for row in _recorded if row[0]() is not None]
    return any(alive() is ctx and seen is entry for alive, seen in _recorded)


def _mark_recorded(ctx: TaskContext, entry: Mapping[str, Any]) -> None:
    """Claim the entry **before** the write, not after.

    The transaction is an await, and a second call that reached the guard
    while the first was still in it would write the row twice. Marking
    first makes a failed write a lost entry rather than a duplicated one,
    which is the right way round: the failure is already logged, and a
    retry is not this module's to decide (rule 3).
    """

    _recorded.append((ref(ctx), entry))
