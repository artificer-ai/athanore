"""`feature` — one change to this repository, from a branch to `main`.

    prepare ─▶ implement ─▶ gate ─▶ review ─▶ qa ─▶ approve ─▶ merge
                   ▲          │       │        │       │
                   └──────────┴───────┴────────┘       └─▶ halted

This is the v0 driver's seat, rebuilt on v1 and pointed at v1. The shape
is deliberately the one that built this repository, because it is the one
that worked for seventy-nine tasks; what changed is underneath it.

**Only three nodes spend tokens.** `prepare`, `gate`, `approve`, `merge`
and `halted` are pure Python: git and an exit code decide, never a model.
That is the property the whole pipeline is built to have — no agent ever
rules on its own work, and none of the three verdicts between a branch
and `main` comes from the model that wrote the code. They also run
cheapest-first: the free gate before a paid review, the review before the
expensive QA.

**Athanore runs on the host; only the agents are containerised.** v0 had
to live in its own image because it was a second `athanore` distribution
that must never share an environment with this one (D67). That reason is
gone — this is v1 maintaining v1 — so the workflow runs in the checkout's
own venv and reaches the sandbox one way, through `scripts/agent.sh`
(:mod:`workflows.feature.agents`).

**The rules do the bookkeeping.** Rule 1: the signature is the graph, so
every loop-back edge is a parameter. Rule 2: the return value is the
routing. Rule 3: the exception is the failure policy — blowing a loop cap
raises, which ends the run as failed with its branch left behind to read,
rather than looping until somebody notices.

**What has no v1 equivalent, on purpose.** v0's `_halt_queue` paused every
queued run behind a failure. A node body reaches the store only through
:class:`~athanore.engine.context.TaskContext`, which carries `services`
and deliberately not `ops` — bodies do not reach across into other runs.
Serialisation is the pool instead: :mod:`workflows.__main__` registers
this on a capacity-1 pool, so the next feature starts when this one is
finished either way.

Run it::

    python -m workflows                 # the host, on 127.0.0.1:4002
    athanore submit feature T080 "..."  # from another shell
"""

from __future__ import annotations

import os
from typing import Any

from athanore import Workflow, current_task, human_input

from .agents import ImplementerAgent, QAAgent, ReviewerAgent
from .models import QAVerdict, ReviewVerdict, TaskReport
from .sandbox import (
    GATE_COMMAND,
    branch_name,
    git,
    git_try,
    plan_docs,
    run_gate,
    unique_branch,
)

__all__ = ["MAX_ATTEMPTS", "MAX_LOOPS", "wf"]

wf = Workflow("feature")

#: Loop-backs to `implement` per lane, and in total, before rule 3 ends
#: the run. Three and six are v0's numbers, kept because they were tuned
#: on a real build: a lane that has bounced three times is not converging,
#: and the branch is more useful read than retried.
MAX_LOOPS = int(os.environ.get("FEATURE_MAX_LOOPS", "3"))
MAX_ATTEMPTS = int(os.environ.get("FEATURE_MAX_ATTEMPTS", "6"))

#: Whether a person is asked before anything reaches `main`. On by
#: default: this repository is released, and `approve` waiting costs
#: nothing but time — a `human_input` gives its worker slot back for the
#: duration of the wait (04 §Waiting), so the pool is not held while you
#: read.
ATTENDED = os.environ.get("FEATURE_ATTENDED", "1") == "1"


async def _log(text: str) -> None:
    """Append to the run's work log, which is what the next stage reads."""

    await current_task().services.log.append(text)


def _title(payload: dict[str, Any]) -> str:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise RuntimeError("a run needs a title: the feature or task id")
    return title


def _bounce(payload: dict[str, Any], lane: str, feedback: str) -> dict[str, Any]:
    """The payload for a loop-back to `implement`, with the caps applied.

    Counting lives here rather than in each lane because the cap is one
    policy, and a lane that counted for itself would drift from the
    others. Blowing either cap raises: rule 3 decides what a run that is
    not converging does, and what it does is stop with its branch intact.
    """

    loops = {**payload.get("loops", {})}
    loops[lane] = loops.get(lane, 0) + 1
    attempts = int(payload.get("attempts", 1)) + 1

    if loops[lane] > MAX_LOOPS:
        raise RuntimeError(
            f"{_title(payload)}: {lane} has sent the work back {loops[lane]} "
            f"times (cap {MAX_LOOPS}). Stopping with the branch intact.\n\n"
            f"{feedback}"
        )
    if attempts > MAX_ATTEMPTS:
        raise RuntimeError(
            f"{_title(payload)}: {attempts} implement attempts (cap "
            f"{MAX_ATTEMPTS}). Stopping with the branch intact.\n\n{feedback}"
        )
    return {**payload, "loops": loops, "attempts": attempts, "feedback": feedback}


@wf.node(start=True, retries=0, timeout=600)
async def prepare(implement, *, payload):
    """Branch from `main`. No agent decides where work goes.

    A dirty checkout is a hard stop rather than something to tidy: the
    uncommitted work is somebody's, and it is not this run's to discard.
    `retries=0` because branching is not improved by doing it twice.
    """

    title = _title(payload)
    dirty = await git("status", "--porcelain")
    if dirty:
        raise RuntimeError(
            f"the checkout has uncommitted changes; refusing to branch over "
            f"them:\n{dirty}"
        )

    await git("checkout", "main")
    base = await git("rev-parse", "HEAD")
    branch = await unique_branch(branch_name(title))
    await git("switch", "-c", branch)
    await _log(f"prepare: {branch} from main at {base[:12]}")

    return implement(
        {**payload, "branch": branch, "base": base, "attempts": 1, "loops": {}}
    )


@wf.node(retries=1, timeout=None)
async def implement(gate, *, payload):
    """The agent takes the feature.

    `timeout=None` because the node's own budget is the agent's
    (`AGENT_TIMEOUT`), and two caps on one wait means the tighter one
    fires and the other is decoration.
    """

    title = _title(payload)
    description = str(payload.get("description", "")).strip()
    feedback = str(payload.get("feedback", "")).strip()
    branch = payload["branch"]

    prompt = f"Implement {title} on branch `{branch}`."
    if description:
        prompt += f"\n\n{description}"
    if plans := plan_docs(title):
        prompt += (
            "\n\nThe implementation plan is "
            + ", ".join(f"`{p}`" for p in plans)
            + ". Follow it: it fences the scope and says what done means."
        )
    if feedback:
        prompt += (
            f"\n\nA previous attempt did not pass. Fix this, and only this:\n{feedback}"
        )

    result = await ImplementerAgent().run(prompt)
    if not result.ok:
        raise RuntimeError(
            f"the implementer did not finish: {result.error or result.stop_reason}"
        )
    report: TaskReport = result.output
    await _log(f"implement: {report.headline}")
    # The first attempt names the feature; later attempts name the fix,
    # and the merge commit wants the former.
    headline = str(payload.get("headline") or report.headline)
    return gate({**payload, "report": report.model_dump(), "headline": headline})


@wf.node(retries=0, timeout=None)
async def gate(review, implement, *, payload):
    """Deterministic, in two halves.

    git says whether there is anything to review; then the gate says
    whether it passes. The agent's account of either is not consulted.
    `retries=0`: a red gate is not a transient failure, it is an answer.
    """

    branch, base = payload["branch"], payload["base"]

    on = await git("rev-parse", "--abbrev-ref", "HEAD")
    if on != branch:
        raise RuntimeError(
            f"the checkout is on {on!r}, not {branch!r}: the agent moved off "
            "its branch, so `main` may have been written to. Stopping."
        )

    dirty = await git("status", "--porcelain", "--untracked-files=no")
    commits = (await git("rev-list", f"{base}..HEAD")).split()
    if dirty or not commits:
        problem = (
            "You left tracked changes uncommitted; everything the feature "
            f"needs must be committed on `{branch}`:\n{dirty}"
            if dirty
            else f"You made no commit on `{branch}`. There is nothing to review."
        )
        await _log(f"gate: rejected before running\n{problem}")
        return implement(_bounce(payload, "gate", problem))

    code, tail = await run_gate()
    await _log(f"gate: {'PASS' if code == 0 else f'FAIL ({code})'}\n{tail}")
    if code == 0:
        return review({**payload, "head": commits[0], "commits": commits, "gate": tail})

    return implement(
        _bounce(
            payload,
            "gate",
            f"`{GATE_COMMAND}` failed with exit code {code}. Its last lines:\n{tail}",
        )
    )


@wf.node(retries=1, timeout=None)
async def review(qa, implement, *, payload):
    """A second model reads the whole branch diff, and the gate's output.

    It is told what the suite did so it knows what the suite did *not*
    prove: green is agreement, not correctness.
    """

    title, branch, base = _title(payload), payload["branch"], payload["base"]
    log = await git("log", "--format=%h %s", f"{base}..HEAD")
    stat = await git("diff", "--stat", f"{base}..HEAD")

    result = await ReviewerAgent().run(
        f"Review branch `{branch}` against {title}.\n\n"
        f"{str(payload.get('description', '')).strip()}\n\n"
        f"The diff is `git diff {base}..HEAD` — read all of it.\n\n"
        f"Commits:\n{log}\n\nFiles:\n{stat}\n\n"
        f"The gate ({GATE_COMMAND}) passed. Its last lines:\n"
        f"{payload.get('gate', '')}"
    )
    if not result.ok:
        raise RuntimeError(
            f"the reviewer did not finish: {result.error or result.stop_reason}"
        )
    verdict: ReviewVerdict = result.output
    blocking = "\n".join(f"- {b}" for b in verdict.blocking)
    await _log(
        f"review: {'ok' if verdict.ok else 'REJECTED'}\n{blocking}\n{verdict.notes}"
    )
    if verdict.ok:
        return qa({**payload, "review": verdict.model_dump()})

    return implement(
        _bounce(
            payload,
            "review",
            f"The reviewer rejected the branch:\n{blocking or verdict.notes}",
        )
    )


@wf.node(retries=1, timeout=None)
async def qa(approve, implement, *, payload):
    """Exercise it for real: the suite passing is not the feature working."""

    title, branch = _title(payload), payload["branch"]
    report = payload.get("report") or {}

    result = await QAAgent().run(
        f"QA {title} on branch `{branch}`.\n\n"
        f"{str(payload.get('description', '')).strip()}\n\n"
        f"What was built: {report.get('summary', '')}\n\n"
        "How the implementer says to exercise it: "
        f"{report.get('how_to_exercise') or '(not stated — work it out)'}"
    )
    if not result.ok:
        raise RuntimeError(f"QA did not finish: {result.error or result.stop_reason}")
    verdict: QAVerdict = result.output
    checks = "\n".join(f"- {c}" for c in verdict.checks)
    await _log(f"qa: {'ok' if verdict.ok else 'FAILED'}\n{checks}\n{verdict.notes}")
    if verdict.ok:
        return approve({**payload, "qa": verdict.model_dump()})

    return implement(
        _bounce(
            payload,
            "qa",
            f"QA could not make the feature work:\n{verdict.notes}\n\n"
            f"What it ran:\n{verdict.evidence}",
        )
    )


@wf.node(retries=0, timeout=None)
async def approve(merge, halted, *, payload):
    """The human gate, and the only node that is optional.

    With `FEATURE_ATTENDED=0` the pipeline merges its own passing work
    and review and QA are the last word before `main`. Waiting here does
    not hold the pool: a `human_input` gives its worker slot back for the
    duration (04 §Waiting).
    """

    title = _title(payload)
    if not ATTENDED:
        return merge(payload)

    answer = await human_input(
        f"{title}: gate green, review passed, QA passed on "
        f"`{payload['branch']}` — merge to main?",
        options=["merge", "stop"],
    )
    await _log(f"approve: operator said {answer!r}")
    return merge(payload) if answer == "merge" else halted(payload)


@wf.node(retries=0, timeout=900)
async def merge(*, payload):
    """`--no-ff` onto `main`, then the branch is gone.

    One merge commit per feature with its work underneath, so reverting a
    feature is reverting one commit. `retries=0`: a merge that half
    happened is not improved by doing it again.
    """

    title, branch, base = _title(payload), payload["branch"], payload["base"]
    report = payload.get("report") or {}
    headline = str(payload.get("headline") or report.get("headline") or "").strip()

    # QA ran after the gate and may have scribbled on tracked files while
    # exercising the feature. Everything real was committed before the
    # gate, so this is scratch — but say what is being dropped first.
    scratch = await git("diff", "--stat")
    if scratch:
        await _log(f"merge: discarding post-gate scratch in the tree:\n{scratch}")
        await git("checkout", "--", ".")

    await git("checkout", "main")
    subject = f"{title}: {headline}" if headline else title
    code, out = await git_try(
        "merge", "--no-ff", "-m", subject, "-m", str(report.get("summary", "")), branch
    )
    if code:
        await git_try("merge", "--abort")
        await git_try("switch", branch)
        raise RuntimeError(f"{title}: merge of {branch} into main failed:\n{out}")

    merge_commit = await git("rev-parse", "HEAD")
    await git("branch", "-d", branch)
    await _log(f"merge: {subject}\n{merge_commit[:12]} on main; {branch} deleted")

    return {
        "title": title,
        "merged": True,
        "merge_commit": merge_commit,
        "base": base,
        "commits": payload.get("commits", []),
        "report": report,
        "review": payload.get("review"),
        "qa": payload.get("qa"),
    }


@wf.node(retries=0, timeout=60)
async def halted(*, payload):
    """Terminal: the operator said stop. The branch stays, unmerged."""

    return {
        "title": _title(payload),
        "merged": False,
        "branch": payload["branch"],
        "report": payload.get("report"),
    }
