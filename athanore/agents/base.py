"""The agent façade's base class, and the prompt an agent is handed.

05 §Agent classes is the shape of the class, 05 §AgentResult the shape of
what it returns, and **19 is the prompt, byte for byte**. Everything in
this module is one of those three things; the ACP subprocess that makes
the class do something is `athanore/agents/acp.py` (T039), and the doubles
a test runs on are `athanore.testing` (T037).

.. code-block:: python

    class Reviewer(Agent):
        system_prompt = "You review one branch."
        output_model = Review
        ask_policy = "http"

A façade is a class carrying its configuration, and its prompt is
**inlined text on that class** — never a template file, never a string a
body assembles (AGENTS.md §Architecture rules). What ``render_prompt``
adds to it is the part the agent cannot know: which task it is working
on, and the four things it may do with it.

**The blocks are normative.** :data:`_KICKOFF`, :data:`_HTTP_TIER`,
:data:`_ASK` and :data:`_SUBMIT` are copies of the fenced blocks of
``docs/v1/19-agent-prompts.md``, and ``tests/agents/test_prompt.py``
compares them against that document rather than against a second copy.
The wording is behaviour: small models are sensitive to it, every example
workflow was tuned against it, and ``FakeACPAgent`` parses it. Changing a
block is a decision (15) and a minor release (19 §Rules).

**The token appears only in a header.** Not as ``?token=``, not as a
``_token`` field, not anywhere in a URL — a token in a URL ends up in an
access log, a shell history and a proxy trace, and this is the one place
in the package that writes the clear-text token into text at all (12
§Task tokens). The substitution is a single pass for the same reason: a
value that lands in the prompt is never re-scanned for placeholders.

**One tier is implemented here, and it is the fallback one.** 05 §Tooling
tiers gives an agent three ways to reach its task; ``http`` — the curl
lines — is the one that always works and the one the base class has,
because ``tooling`` is an :class:`ACPAgent` attribute and the tier is
chosen from what a session advertises (T039b). The assembly is a list of
sections joined by a blank line precisely so that the tier block is one
entry in it.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from athanore.engine.context import TaskContext
from athanore.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "Agent",
    "AgentError",
    "AgentResult",
    "ask_instructions",
    "http_tier",
    "kickoff",
    "run_title",
    "submission_instructions",
    "task_base",
]


class AgentError(Exception):
    """An agent run, or its submission, is unusable.

    Raised for timeouts, transport failures and a missing or invalid
    submission — the outcomes a node body cannot route on because there
    is no result to route with. A refusal, a cancellation or a truncated
    final turn is *returned* instead, as an :class:`AgentResult` with
    ``status="failed"``, because those are answers a body may legitimately
    decide what to do about (05 §AgentResult).
    """


@dataclass
class AgentResult:
    """What one ``run()`` produced (05 §AgentResult).

    ``output`` is the validated ``output_model`` instance when the class
    declared one, and the raw submission when it did not. ``text`` is the
    assistant text concatenated, ``stats`` the entry that was recorded for
    this run (T036) — recorded on every exit path, so it is a dict here
    rather than an optional.
    """

    status: Literal["complete", "failed"] = "complete"
    output: Any = None
    text: str = ""
    session_id: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether the run completed. ``status="failed"`` is not an error."""

        return self.status == "complete"


class Agent:
    """The base façade: configuration, a prompt, and a ``run()`` to override.

    The three attributes are the whole of what a base agent is
    configurable with, and each one changes the prompt: ``system_prompt``
    is its first section, ``output_model`` adds the submission block (and
    is what the submit endpoint validates against for the duration of the
    run), ``ask_policy="http"`` adds the ask block (and is what the ask
    endpoint checks before it opens a request).

    ``run()`` raises here. This class is the shape and the prompt; the
    subprocess is :class:`~athanore.agents.acp.ACPAgent`, and the doubles
    a test runs on are in :mod:`athanore.testing`.
    """

    #: Inlined prompt text (AGENTS.md). Stripped, and sent as-is.
    system_prompt: str | None = None
    #: The shape a submission must have. ``None``: submissions are raw.
    output_model: type[BaseModel] | None = None
    #: Whether this agent may open a request for the operator over HTTP.
    ask_policy: Literal["off", "http"] = "off"

    async def run(self, prompt: str = "") -> AgentResult:
        """Run the agent on ``prompt``. Overridden by a real façade."""

        raise NotImplementedError(
            f"{type(self).__name__} has no run(): subclass ACPAgent, or one of "
            "the doubles in athanore.testing"
        )

    @asynccontextmanager
    async def declare(self, ctx: TaskContext | None) -> AsyncIterator[None]:
        """Publish this agent's declarations on ``ctx`` for the block.

        The submit endpoint validates against ``ctx.output_model`` and the
        ask endpoint reads ``ctx.ask_policy`` (04 §TaskContext), so the
        context is where an in-flight agent's configuration has to live:
        the API sees the task, not the object that spawned the agent.

        The previous values are restored on the way out, on every path,
        because a body may run several agents in sequence or nest one
        inside another's context — and an agent that left its own model
        declared would have the endpoint validate the *next* agent's
        submission against a schema nobody handed that agent.
        ``last_rejection`` is cleared rather than saved-and-restored on
        entry for the same reason: it belongs to this run's repair loop,
        and inheriting an earlier run's 422 would quote the wrong errors.

        With no context — an agent run outside a body — there is nothing
        to declare and this is a no-op.
        """

        if ctx is None:
            yield
            return
        previous = (ctx.output_model, ctx.ask_policy, ctx.last_rejection)
        ctx.output_model = self.output_model
        ctx.ask_policy = self.ask_policy
        ctx.last_rejection = None
        try:
            yield
        finally:
            ctx.output_model, ctx.ask_policy, ctx.last_rejection = previous

    async def render_prompt(
        self, prompt: str = "", ctx: TaskContext | None = None
    ) -> str:
        """The full text handed to the agent (19 §Assembly).

        Sections, joined by a blank line: the system prompt, ``---``, the
        assignment, ``---``, then the task sections — the tool-agnostic
        kickoff, the ``http`` tier block, the ask block when
        ``ask_policy == "http"`` and the submission block when an
        ``output_model`` is declared.

        A section that has nothing to say is omitted **with its
        separator**: no assignment heading without an assignment, and no
        leading ``---`` on an agent that carries no system prompt. With
        neither, the assignment is sent alone (19 §Assembly).

        It is a coroutine because of one word in 19's kickoff: the run's
        title, which is a row in the store and reaches an agent façade the
        only way the store ever does — through ``ctx.services`` (02
        §Layering, 04 §TaskContext).
        """

        sections: list[str] = []
        if self.system_prompt:
            sections.append(self.system_prompt.strip())
            if prompt:
                sections += ["---", f"## Your assignment\n\n{prompt}"]
        elif prompt:
            sections.append(prompt)

        if ctx is None:
            _log.warning(
                "agent prompt rendered outside a task context",
                agent=type(self).__name__,
            )
            return "\n\n".join(sections)

        if sections:
            sections.append("---")
        sections.append(kickoff(ctx, await run_title(ctx)))
        sections.append(http_tier(ctx))
        if self.ask_policy == "http":
            sections.append(ask_instructions(ctx))
        if self.output_model is not None:
            sections.append(submission_instructions(ctx, self.output_model))
        return "\n\n".join(sections)


def task_base(ctx: TaskContext) -> str:
    """``{base}``: this task's root on the agent API (08 §Agent, 12)."""

    return f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}"


async def run_title(ctx: TaskContext) -> str:
    """``{title}``: the run's title, quoted and space-prefixed, or empty.

    A run has a title in every path that creates one, but the column
    permits an empty string, and ``Work on task 12 "" — stage …`` reads as
    a bug. Empty means the placeholder contributes nothing.
    """

    run = await ctx.services.run.get()
    return f' "{run.title}"' if run.title else ""


def kickoff(ctx: TaskContext, title: str) -> str:
    """The tool-agnostic core of 19: which task, and what to do with it."""

    return _fill(
        _KICKOFF,
        task_id=str(ctx.task_id),
        title=title,
        node=ctx.node,
        workflow=ctx.workflow,
        run_id=ctx.run_id,
    )


def http_tier(ctx: TaskContext) -> str:
    """The ``http`` tier block: how to read the task and append to the log.

    The fallback tier, and the only one the base class has — ``mcp`` and
    ``native`` are chosen from what an ACP session advertises (T039b).
    """

    return _fill(_HTTP_TIER, base=task_base(ctx), token=ctx.token)


def ask_instructions(ctx: TaskContext) -> str:
    """How to ask the operator and wait for the answer (19 §Ask)."""

    return _fill(_ASK, base=task_base(ctx), token=ctx.token)


def submission_instructions(ctx: TaskContext, output_model: type[BaseModel]) -> str:
    """How to submit, and the schema to submit (19 §Submission).

    ``output_model`` is a parameter rather than a read of
    ``ctx.output_model`` because both callers have a different one in
    hand: ``render_prompt`` states the agent's own model, and the repair
    turn (T035) states the one the endpoint rejected against.
    """

    return _fill(
        _SUBMIT,
        base=task_base(ctx),
        token=ctx.token,
        schema=json.dumps(output_model.model_json_schema(), indent=2),
    )


#: The placeholders of 19, and the only substrings ever substituted. One
#: pass over the template, so a value carrying braces of its own — a JSON
#: schema, a submitted payload quoted back in a repair turn — is text and
#: not a template.
_PLACEHOLDER = re.compile(r"\{(base|token|task_id|title|node|workflow|run_id|schema)\}")


def _fill(template: str, **values: str) -> str:
    """``template`` with its placeholders replaced, in a single pass.

    A placeholder with no value is a :exc:`KeyError` rather than a
    literal ``{token}`` reaching an agent.
    """

    return _PLACEHOLDER.sub(lambda match: _value(values, match.group(1)), template)


def _value(values: Mapping[str, str], name: str) -> str:
    if name not in values:
        raise KeyError(f"no value for the prompt placeholder {{{name}}}")
    return values[name]


# --------------------------------------------------------------------------
# 19, verbatim. Compared against the document itself by the tests.
# --------------------------------------------------------------------------

#: 19 §Kickoff. Sent in every tier; names the four capabilities without
#: saying how they are reached.
_KICKOFF = (
    "## Your task\n"
    "\n"
    'Work on task {task_id}{title} — stage "{node}" of workflow '
    '"{workflow}" (run {run_id}).\n'
    "\n"
    "Start by reading your task: the title, description, and the FULL "
    "work log — deliverables and notes from every earlier stage and "
    "attempt. Your own deliverable MUST be appended to the run's work "
    "log before you finish — the next stage reads this same log."
)

#: 19 §Tier block: ``http``. The MVP's curl text, with 08's agent paths
#: and the token moved into the header.
_HTTP_TIER = (
    "Read your task with:\n"
    "curl -sS {base} -H 'X-Athanore-Token: {token}'\n"
    "\n"
    "Append your deliverable with:\n"
    "curl -sS -X POST {base}/log -H 'Content-Type: application/json' "
    "-H 'X-Athanore-Token: {token}' -d '{\"text\": \"<text>\"}'"
)

#: 19 §Ask instructions. Only with ``ask_policy="http"``.
_ASK = (
    "If you genuinely need something from the human operator (a "
    "decision, a missing detail), you may ask — sparingly:\n"
    "curl -sS -X POST {base}/ask -H 'Content-Type: application/json' "
    "-H 'X-Athanore-Token: {token}' -d '{\"prompt\": \"<your "
    "question>\"}'\n"
    'Add "options": ["a", "b"] for a pick-one question. The response '
    "carries a request_id. Then wait for the answer, repeating until "
    'it says "answered": true:\n'
    "curl -sS '{base}/requests/<request_id>?wait=60' -H "
    "'X-Athanore-Token: {token}'\n"
    "Continue only once you have the answer."
)

#: 19 §Submission instructions. Only with an ``output_model``.
_SUBMIT = (
    "When you have finished, you MUST submit your structured result "
    "by running exactly this (replacing <json> with your JSON "
    "result):\n"
    "curl -sS -X POST {base}/submit -H 'Content-Type: "
    "application/json' -H 'X-Athanore-Token: {token}' -d '<json>'\n"
    "The JSON must conform to this schema:\n"
    "{schema}"
)
