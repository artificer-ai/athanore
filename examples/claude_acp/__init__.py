"""claude_acp — the ACP portability check, not a Claude integration.

The same :class:`~athanore.agents.acp.ACPAgent` façade every other
example runs on, pointed at ``@agentclientprotocol/claude-agent-acp``
instead of ``pi-acp``. The **only** differences from a pi seat are
``command`` and ``model``: there is no Claude-specific code path here or
anywhere else, and permission handling, config options, the tooling tier
and the environment scrub all go through the generic ACP code in
:mod:`athanore.agents` (05 §User-land adapters, 20 §Findings 1-4).

    implement → wrap

`implement` gives one adapter one small, unambiguous edit to make in a
scratch repository; `wrap` reads the file back and says whether it
landed. Nothing about that verdict is a model's opinion — the file either
says :data:`GOAL` or it does not — which is what makes this a check
rather than a demonstration.

**What it is checking.** That a second vendor's adapter completes a whole
athanore session: handshake, ``session/new``, a ``model`` config option
resolved *by category* (an id that is pi's would be rejected here, and
the rejection is logged rather than swallowed — 20 §Finding 2, D11), a
permission request answered by kind rather than by index (this adapter
lists rejection **first**; 20 §Finding 1), the work log written and the
turn ended. A single run exercises the code path every other workflow
depends on, against the one adapter that is not pi.

**The permission policy is ``ask``, on purpose.** These agents run on the
host, in a directory the operator owns, with no container around them, so
every tool call the adapter asks about reaches the operator (05
§Policies). That is also half of what the check is for: the request card
this raises is the one 20 §Finding 1 is about.

Run it with ``athanore serve`` (it is an entry point of the
``athanore-examples`` distribution) or with ``python -m examples``::

    athanore submit claude_acp "portability check"

The assignment is the workflow's, not the operator's: a check whose task
came from the submission would be checking something different every
time. Whatever the run is titled, :data:`ASSIGNMENT` is what the agent is
asked to do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from athanore import ACPAgent, AgentResult, NonRetryable, Workflow, current_task
from athanore.settings import AthanoreSettings

__all__ = [
    "ASSIGNMENT",
    "CLAUDE",
    "CLAUDE_ACP_VERSION",
    "GOAL",
    "MODEL",
    "SANDBOX_FILE",
    "START",
    "ClaudeAgent",
    "ImplementerAgent",
    "prepare",
    "sandbox",
    "wf",
]

#: The Claude Code ACP adapter, pinned rather than floating: an example
#: that runs `npx -y @agentclientprotocol/claude-agent-acp` picks up
#: whatever was published this morning (12 §Supply chain). It matches
#: ``CLAUDE_ACP_VERSION`` in `compose.yaml`, which is the same adapter
#: inside the dev sandbox, and the one `examples/projects` runs its
#: seats on — `examples/tests/test_adapters.py` asserts all three are the
#: same string, because a pin that only holds in one of three places is
#: not a pin.
CLAUDE_ACP_VERSION = "0.75.1"

#: The command this seat spawns.
CLAUDE = ["npx", "-y", f"@agentclientprotocol/claude-agent-acp@{CLAUDE_ACP_VERSION}"]

#: One of the four model ids this adapter advertises (``opus[1m]``,
#: ``sonnet``, ``haiku``, ``default``). An id it does not know is not
#: silently swapped for its default: the façade resolves ``model`` as a
#: config option by category and logs the rejection into the transcript
#: (20 §Finding 2). The cheapest model that can do the edit is the right
#: one for a check that is about the wire and not about the answer.
MODEL = "sonnet"

#: The one file in the scratch repository, and the two states it has.
SANDBOX_FILE = "a.py"
START = "x = 1\n"
GOAL = "x = 2"

#: What the agent is asked to do, every run. Stated here rather than
#: taken from the submission, so the verdict below means one thing.
ASSIGNMENT = (
    f"In `{SANDBOX_FILE}`, in the current directory, change the line "
    f"`{START.strip()}` to `{GOAL}`. Change nothing else, and create no "
    "other file."
)


def sandbox() -> Path:
    """The scratch repository, under the server's ``root_path``.

    A directory the check owns, so a run never edits a workspace somebody
    cares about; ``root_path`` rather than this package's own directory
    because an installed copy of these examples has no checkout to write
    into (02 §Settings — it defaults to the directory the server was
    started in, which in this repository is the checkout, whose
    ``output/`` is git-ignored).
    """

    return AthanoreSettings().root_path / "output" / "claude-acp-sandbox"


def prepare() -> Path:
    """Put the scratch repository in its :data:`START` state, and say where.

    Written on every run rather than only when missing: the check asks
    whether one edit was made, and an ``a.py`` a previous run already
    left at :data:`GOAL` would answer that question with yesterday's
    work. What the agent leaves behind stays there afterwards, for
    somebody to read.
    """

    where = sandbox()
    where.mkdir(parents=True, exist_ok=True)
    (where / SANDBOX_FILE).write_text(START, encoding="utf-8")
    return where


class ClaudeAgent(ACPAgent):
    """Claude Code over ACP: a command, a model, and nothing else.

    The whole adapter, and the whole point — a vendor seat is
    configuration, not a second façade. ``tooling`` is left at ``auto``
    because this adapter advertises MCP, so the façade negotiates the
    ``mcp`` tier and the task token never reaches the prompt (05 §Tooling
    tiers); ``permission_policy`` is left at ``ask`` because nothing here
    is sandboxed.
    """

    command = CLAUDE
    model = MODEL
    #: Claude Code keeps no session file this package knows how to read,
    #: so there is no provider to name. The ACP ``usage`` the adapter
    #: reports is what a stats entry carries, and what it does not report
    #: is omitted rather than estimated (`AGENTS.md` §Real data only,
    #: D27).
    stats_provider = None


class ImplementerAgent(ClaudeAgent):
    """The seat: the adapter above, plus the one prompt this check sends."""

    system_prompt = """# Software engineer

You are the implementation stage of an athanore workflow pipeline that
exists to check one thing: that your ACP adapter can complete a whole
athanore session end to end.

implement → wrap

`wrap` is deterministic code, not an agent: it reads the file back and
reports whether your edit landed.

## How this pipeline works (important)

- **Start by reading your task.** The `## Your task` block at the end of this
  message says how — a tool your harness gave you, or a `curl` line. It
  returns the title, description, and the FULL work log — deliverables and
  notes from every earlier stage and attempt. **Before you finish, append
  your deliverable to the run's work log** the same way — the next stage
  reads this same log.
- Routing is automatic: when you finish, the engine runs the next stage. You
  never create tasks, move tasks, or call any workflow API.
- If structured output instructions are appended to the end of this message,
  follow them exactly.

## Your job

1. Make exactly the edit this message asks for, in the current directory.
2. Change nothing else. Create no other file. Run nothing.

## Deliverable

Append one line to the run's log saying what the file contains now, and say
the same as your output.

## If blocked

If the file is not there, or is not what this message says it is, say exactly
that as your entire output rather than creating it — a check that repaired
its own fixture would have checked nothing.
"""


wf = Workflow("claude_acp")


@wf.node(start=True, retries=1, timeout=600)
async def implement(wrap):
    """Hand the assignment to the adapter, in the scratch repository.

    ``retries=1``: the failure this stage has is a turn that went wrong,
    and a second turn is exactly what fixes it. A stop reason that is not
    an answer — a refusal, a cancellation — is a dead letter instead, so
    the run stops where somebody can read why (04 §Failure classes).
    """

    where = prepare()
    result = await ImplementerAgent(cwd=str(where)).run(ASSIGNMENT)
    if not result.ok:
        raise NonRetryable(
            result.error
            or f"the agent stopped: {result.stop_reason or 'no reason given'}"
        )
    return wrap(_said(result))


@wf.node(retries=0)
async def wrap(*, said):
    """Read the file back and say whether the edit landed. Terminal.

    No agent and no retries: this node runs one `read_text` and compares
    two strings, and re-reading the same file cannot change the answer.
    What it returns is the run's output (04 §Routing interpretation) and
    it is also the last line of the work log, so a client that reads
    either sees the same verdict.
    """

    text = _payload(said)
    path = sandbox() / SANDBOX_FILE
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    landed = content.strip() == GOAL
    verdict = f"claude_acp: {SANDBOX_FILE} now contains {content.strip()!r} — " + (
        "the edit landed" if landed else "the edit did NOT land"
    )
    await current_task().services.log.append(
        verdict if not text else f"{verdict}\nthe agent said: {text}",
        author="engine",
        kind="deliverable" if landed else "failure",
    )
    return {"landed": landed, "content": content, "verdict": verdict}


def _said(result: AgentResult) -> str:
    """The one line of the agent's own text `wrap` quotes back."""

    return " ".join(result.text.split())[:500]


def _payload(said: Any) -> str:
    """``said``, whatever shape the payload arrived in.

    Payloads are coerced with ``jsonable()`` (04 §Routing interpretation)
    and an operator may move a task onto `wrap` by hand, in which case
    there is no agent and nothing it said: the verdict is then the file
    alone, which is the one thing this node was ever going to check.
    """

    return said if isinstance(said, str) else ""
