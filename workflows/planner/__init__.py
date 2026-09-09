"""`planner` — one request, from a sentence to a queue of `feature` runs.

    enhance ─▶ prepare ─▶ architect ─▶ verify ─▶ approve ─▶ adopt ─▶ dispatch
                              ▲          │         │
                              └──────────┴─────────┴─▶ abandoned

This is the seat in front of `feature`. `feature` builds one task and is
told which one; something has to decide what the tasks are, write the
specification they are built against, and get a person to agree to it
before a single branch is cut. That is this.

**Two nodes spend tokens.** `prepare`, `verify`, `approve`, `adopt`,
`dispatch` and `abandoned` are pure Python: git, a regex and a person
decide. The property is the one `feature` has — no agent rules on its own
work — and here it matters more, because a plan is prose and prose is
what a model is most able to make look finished. The architect says it
wrote a design document and eleven plan files; `verify` reads
`git diff --name-only` and finds out.

**The human gate is the point of the workflow.** Everything before
`approve` is cheap and reversible: a branch of documents. Everything
after it is expensive — one `feature` run per task, each one an
implementer, a gate, a reviewer and a QA engineer. So the operator is
asked once, with the open points in front of them, and a `revise` goes
back to the architect on the same branch carrying their words.

**The plan lands before the work is queued, and that ordering is load
bearing.** `feature` branches from `main` and resolves a task's plan from
the working tree at the moment its implementer needs it, so `adopt`
merges the plan branch into `main` *before* `dispatch` queues anything.
Queued first, the first implementer would branch from a `main` with no
plan on it.

**The rules do the bookkeeping.** Rule 1: the signature is the graph, so
every loop-back edge is a parameter. Rule 2: the return value is the
routing. Rule 3: the exception is the failure policy — blowing a loop cap
raises, which ends the run as failed with its branch left behind to read.

**One tree, one pool.** This mutates the working tree exactly as
`feature` does, so :mod:`workflows.__main__` registers both on the same
capacity-1 `checkout` pool. Note what that does *not* cover: a
`human_input` gives its worker slot back for the duration of the wait (04
§Waiting), so a `feature` run queued behind an unanswered `approve` will
start, branch, and be on its own branch when you finally answer. `adopt`
refuses a dirty tree rather than merging over somebody's work — but the
honest guidance is to answer the gate before queueing other work, and it
is why `approve` is the only question this workflow asks.

Run it::

    python -m workflows                       # the host, on 127.0.0.1:4002
    athanore submit planner "SSE replay cap" "..."   # from another shell
"""

from __future__ import annotations

import os
from typing import Any

from athanore import Workflow, current_task, human_input
from workflows.checkout import branch_name, git, git_try, unique_branch

from .agents import ArchitectAgent, EnhancerAgent
from .checks import verify as verify_proposal
from .models import Brief, Decision, PlanProposal
from .submit import submit_feature

__all__ = ["MAX_REVISIONS", "wf"]

wf = Workflow("planner")

#: Loop-backs to `architect` before rule 3 ends the run. Five rather than
#: `feature`'s three: a rejection here is usually a person changing their
#: mind about the design, which is the gate working, not a stage failing
#: to converge. It is still a cap, because a plan that has been rewritten
#: five times is a conversation to have rather than a run to continue.
MAX_REVISIONS = int(os.environ.get("PLANNER_MAX_REVISIONS", "5"))


async def _log(text: str) -> None:
    """Append to the run's work log, which is what the next stage reads."""

    await current_task().services.log.append(text)


def _title(payload: dict[str, Any]) -> str:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise RuntimeError("a run needs a title: what is being planned")
    return title


def _bounce(payload: dict[str, Any], lane: str, feedback: str) -> dict[str, Any]:
    """The payload for a loop-back to `architect`, with the cap applied.

    Counting lives here rather than in each lane because the cap is one
    policy, and a lane that counted for itself would drift from the
    other. Blowing it raises: rule 3 decides what a run that is not
    converging does, and what it does is stop with its branch intact, so
    the design so far is still there to read.
    """

    revisions = int(payload.get("revisions", 0)) + 1
    if revisions > MAX_REVISIONS:
        raise RuntimeError(
            f"{_title(payload)}: the plan has been sent back {revisions} times "
            f"(cap {MAX_REVISIONS}). Stopping with `{payload['branch']}` "
            f"intact.\n\nThe last rejection came from {lane}:\n{feedback}"
        )
    return {**payload, "revisions": revisions, "feedback": feedback, "lane": lane}


@wf.node(start=True, retries=1, timeout=None)
async def enhance(prepare, *, payload):
    """Read the request and the specs, and say what is actually being asked.

    First, and before anything is branched, because a dirty checkout is
    the one thing that stops this run either way and finding it out here
    costs nothing. `timeout=None` because the node's own budget is the
    agent's (`AGENT_TIMEOUT`), and two caps on one wait means the tighter
    one fires and the other is decoration.
    """

    title = _title(payload)
    dirty = await git("status", "--porcelain")
    if dirty:
        raise RuntimeError(
            f"the checkout has uncommitted changes; refusing to plan over "
            f"them:\n{dirty}"
        )

    description = str(payload.get("description", "")).strip()
    result = await EnhancerAgent().run(
        f"An operator asked for: {title}\n\n"
        f"{description or '(no further description was given)'}\n\n"
        "Read the request against this repository and its specs, and write "
        "the brief the architect after you will design from."
    )
    if not result.ok:
        raise RuntimeError(
            f"the enhancer did not finish: {result.error or result.stop_reason}"
        )
    brief: Brief = result.output
    await _log(f"enhance: {brief.goal}")
    return prepare({**payload, "brief": brief.model_dump()})


@wf.node(retries=0, timeout=600)
async def prepare(architect, *, payload):
    """Branch from `main`. No agent decides where work goes.

    `plan/` rather than `feat/`: this branch carries the design that
    produces the `feat/` branches, and the two must not collide in a
    listing or in a name. `retries=0` because branching is not improved
    by doing it twice.
    """

    title = _title(payload)
    await git("checkout", "main")
    base = await git("rev-parse", "HEAD")
    branch = await unique_branch(branch_name(title, "plan"))
    await git("switch", "-c", branch)
    await _log(f"prepare: {branch} from main at {base[:12]}")

    return architect({**payload, "branch": branch, "base": base, "revisions": 0})


@wf.node(retries=1, timeout=None)
async def architect(verify, *, payload):
    """Write the design and the plan files, and commit them on the branch."""

    title = _title(payload)
    branch = payload["branch"]
    brief = Brief.model_validate(payload["brief"])
    feedback = str(payload.get("feedback", "")).strip()
    lane = str(payload.get("lane", ""))

    prompt = (
        f"Design {title} and split it into implementation tasks. You are on "
        f"branch `{branch}`; commit everything you write on it.\n\n"
        f"{brief.as_markdown()}"
    )
    if feedback:
        prompt += (
            f"\n\n## What came back\n\nA previous proposal was not accepted "
            f"by {lane}. Fix this, and only this:\n{feedback}"
        )

    result = await ArchitectAgent().run(prompt)
    if not result.ok:
        raise RuntimeError(
            f"the architect did not finish: {result.error or result.stop_reason}"
        )
    proposal: PlanProposal = result.output
    tasks = "\n".join(
        f"- {task.id} {task.title} ({task.plan})" for task in proposal.tasks
    )
    await _log(f"architect: {proposal.document}\n{proposal.summary}\n{tasks}")
    return verify({**payload, "proposal": proposal.model_dump()})


@wf.node(retries=0, timeout=300)
async def verify(approve, architect, *, payload):
    """Deterministic: git says what the branch wrote, not the architect.

    The gate `feature` has, for a branch a test suite cannot judge. It
    checks the design document and every plan file against
    `git diff --name-only`, that the task ids are free, and that nothing
    outside `docs/` was touched. `retries=0`: a proposal that does not
    check out is not a transient failure, it is an answer.
    """

    branch, base = payload["branch"], payload["base"]
    proposal = PlanProposal.model_validate(payload["proposal"])

    on = await git("rev-parse", "--abbrev-ref", "HEAD")
    if on != branch:
        raise RuntimeError(
            f"the checkout is on {on!r}, not {branch!r}: the agent moved off "
            "its branch, so `main` may have been written to. Stopping."
        )

    dirty = await git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        problems = (
            "You left tracked changes uncommitted; everything the plan needs "
            f"must be committed on `{branch}`:\n{dirty}"
        )
    else:
        problems = await verify_proposal(proposal, branch=branch, base=base)

    if problems:
        await _log(f"verify: REJECTED\n{problems}")
        return architect(_bounce(payload, "the checks", problems))

    await _log(f"verify: ok — {proposal.document} and {len(proposal.tasks)} plans")
    return approve(payload)


@wf.node(retries=0, timeout=None)
async def approve(adopt, architect, abandoned, *, payload):
    """The human gate: the one question this workflow asks.

    Everything before this is a branch of documents; everything after it
    is one implementer, gate, reviewer and QA engineer per task. Waiting
    does not hold the pool: a `human_input` gives its worker slot back for
    the duration (04 §Waiting).

    A `revise` with nothing said is asked again rather than sent on: an
    architect told only that its plan was rejected spends a full turn
    finding out nothing.
    """

    title = _title(payload)
    proposal = PlanProposal.model_validate(payload["proposal"])
    tasks = "\n".join(
        f"- **{task.id}** {task.title} — {task.plan}" for task in proposal.tasks
    )
    prompt = (
        f"{title}: the plan is on `{payload['branch']}`.\n\n"
        f"{proposal.summary}\n\nDesign: `{proposal.document}`\n\n"
        f"Tasks, in build order:\n{tasks}\n\n"
        + (f"Open points:\n{proposal.open_points}\n\n" if proposal.open_points else "")
        + "Approve to merge it to `main` and queue a run per task."
    )

    nag = (
        "\n\n**Say what to change.** A revision with no feedback sends the "
        "architect back with nothing to act on."
    )
    asked = prompt
    while True:
        decision = Decision.model_validate(
            await human_input(asked, output_model=Decision)
        )
        if decision.decision != "revise" or decision.feedback.strip():
            break
        asked = prompt + nag

    await _log(f"approve: operator said {decision.decision!r}\n{decision.feedback}")
    if decision.decision == "approve":
        return adopt(payload)
    if decision.decision == "abandon":
        return abandoned({**payload, "feedback": decision.feedback})
    return architect(_bounce(payload, "the operator", decision.feedback))


@wf.node(retries=0, timeout=900)
async def adopt(dispatch, *, payload):
    """`--no-ff` onto `main`, then the branch is gone.

    One merge commit per plan with its documents underneath, so backing a
    plan out is reverting one commit. This is before `dispatch` and not
    after it because `feature` branches from `main` and reads the plan
    file out of the working tree: queued first, the first implementer
    would branch from a `main` with no plan on it.

    A dirty tree is refused rather than discarded. `feature`'s merge
    drops post-gate scratch because it knows QA made it; here anything
    uncommitted belongs to somebody else — most likely a `feature` run
    that claimed the pool while the approval was waiting — and it is not
    this run's to throw away. `retries=0`: a merge that half happened is
    not improved by doing it again.
    """

    title, branch = _title(payload), payload["branch"]
    proposal = PlanProposal.model_validate(payload["proposal"])

    dirty = await git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise RuntimeError(
            f"{title}: the checkout has uncommitted changes that are not this "
            f"run's; refusing to merge `{branch}` over them:\n{dirty}"
        )

    await git("checkout", "main")
    code, out = await git_try(
        "merge", "--no-ff", "-m", f"{title}: plan", "-m", proposal.summary, branch
    )
    if code:
        await git_try("merge", "--abort")
        await git_try("switch", branch)
        raise RuntimeError(f"{title}: merge of {branch} into main failed:\n{out}")

    merge_commit = await git("rev-parse", "HEAD")
    await git("branch", "-d", branch)
    await _log(f"adopt: {merge_commit[:12]} on main; {branch} deleted")

    return dispatch({**payload, "merge_commit": merge_commit})


@wf.node(retries=0, timeout=300)
async def dispatch(*, payload):
    """Queue one `feature` run per task, in build order.

    One `POST /api/workflows/feature/runs` each, through the same wire
    contract the CLI and the SPA use: a body reaches the store through
    `TaskContext`, whose services deliberately carry no `ops`, so a run
    queued here is queued the way an operator queues one.

    They are submitted in order and the `checkout` pool has capacity 1,
    so they build in order — which is what the plan promised when it said
    each task may rely on every task before it.

    A submission that fails raises, with the ids that got through named:
    the plan is already on `main` at this point, so the honest end is a
    failed run that says exactly which tasks are queued and which are not.
    """

    title = _title(payload)
    proposal = PlanProposal.model_validate(payload["proposal"])
    api_base = current_task().api_base

    queued: dict[str, str] = {}
    for task in proposal.tasks:
        try:
            run_id = await submit_feature(api_base, task, document=proposal.document)
        except Exception as exc:
            done = ", ".join(f"{one}={run}" for one, run in queued.items()) or "none"
            raise RuntimeError(
                f"{title}: {proposal.document} is merged, but queueing "
                f"{task.id} failed: {exc}\n\nQueued so far: {done}. Submit the "
                "rest by hand."
            ) from exc
        queued[task.id] = run_id

    await _log(
        "dispatch: queued "
        + ", ".join(f"{one} as {run}" for one, run in queued.items())
    )
    return {
        "title": title,
        "approved": True,
        "document": proposal.document,
        "merge_commit": payload["merge_commit"],
        "summary": proposal.summary,
        "decisions": proposal.decisions,
        "queued": queued,
    }


@wf.node(retries=0, timeout=60)
async def abandoned(*, payload):
    """Terminal: the operator said stop. The branch stays, unmerged."""

    proposal = PlanProposal.model_validate(payload["proposal"])
    return {
        "title": _title(payload),
        "approved": False,
        "branch": payload["branch"],
        "document": proposal.document,
        "tasks": [task.id for task in proposal.tasks],
        "feedback": str(payload.get("feedback", "")),
    }
