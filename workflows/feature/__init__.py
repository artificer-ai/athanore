"""`feature` — one change to this repository, from a branch to `main`.

    prompt ─▶ prepare ─▶ planner ─▶ implement ─▶ gate ─▶ review ─▶ qa
                                        ▲          │        │       │
                                        └──────────┴────────┴───────┘

    qa ─▶ approve ─▶ publish ─▶ merge
                │        └──▶ implement   (CI red)
                └──▶ halted

This is the v0 driver's seat, rebuilt on v1 and pointed at v1. The shape
is deliberately the one that built this repository, because it is the one
that worked for seventy-nine tasks; what changed is underneath it.

**Five nodes spend tokens, and they are not equal.** `prompt` is haiku
sharpening a sentence; `planner` is opus reading the codebase and filing
the plan `implement` then follows; the three after it build, judge and
exercise the work. `prepare`, `gate`, `approve`, `publish`, `merge` and
`halted` are pure Python: git and an exit code decide, never a model.

**The plan is written per run, on the branch.** `docs/plans/<title>*.md`
used to be something a human wrote before submitting; `planner` writes it
inside the run, commits it, and `implement` resolves it by the same glob
as before. So the plan lands in the same merge commit as the code it
describes, and the two can never drift.

**The branch lands through a pull request, and only after every
verdict** (AGENTS.md §Landing a change, D260, D269). `gate` runs the
suite on the worktree — the fast answer, with its tail quoted back to
the implementer — and nothing leaves the machine until the review, the
QA pass and `approve` have all said yes. Then `publish` pushes the
branch, opens the PR and waits for CI on it, the same gate on a runner
and the run that counts; a red there goes back to `implement` like a
red gate does. `merge` is `gh pr merge --merge`, so the merge commit is
GitHub's, titled and bodied like the PR. The PR list is the record of
what this workflow landed, one PR per feature and not one per attempt.
That is the property the whole pipeline is built to have — no agent ever
rules on its own work, and none of the three verdicts between a branch
and `main` comes from the model that wrote the code. They also run
cheapest-first: haiku before opus, the free gate before a paid review,
the review before the expensive QA.

**Athanore runs on the host; only the agents are containerised.** v0 had
to live in its own image because it was a second `athanore` distribution
that must never share an environment with this one (D67). That reason is
gone — this is v1 maintaining v1 — so the workflow runs in the checkout's
own venv and reaches the sandbox one way, through `scripts/agent.sh`
(:mod:`workflows.shared.agents`).

**Every run builds in a worktree of its own** (`.worktrees/<branch>`,
D263), cut from `origin/main`, and the operator's checkout is never
checked out, dirtied or merged into. The deterministic nodes are thin:
what they do is in :mod:`workflows.shared.steps`, shared with `quick`,
and the node here holds the edges and routes on the step's answer.

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
    athanore submit feature T083 "..."  # from another shell

`approve` is **unattended by default** (:data:`ATTENDED`): the node is
still in the graph and still routes, it just does not stop. Set
`FEATURE_ATTENDED=1` to be asked before anything reaches `main`.
"""

from __future__ import annotations

import os

from athanore import Workflow, human_input
from workflows.shared import steps
from workflows.shared.sandbox import GATE_COMMAND, git, plan_docs
from workflows.shared.steps import MAX_ATTEMPTS, MAX_LOOPS
from workflows.shared.steps import bounce as _bounce
from workflows.shared.steps import log as _log
from workflows.shared.steps import title_of as _title
from workflows.shared.steps import tree_of as _tree

from .agents import (
    ImplementerAgent,
    PlannerAgent,
    PromptAgent,
    QAAgent,
    ReviewerAgent,
)
from .cron import declare as declare_cron
from .files import declare as declare_files
from .models import Brief, PlanDoc, QAVerdict, ReviewVerdict

__all__ = ["MAX_ATTEMPTS", "MAX_LOOPS", "wf"]

# `assets=` is the escape hatch's one requirement: the directory is served
# at `/plugins/feature/static/` and every `.js` in it is injected once, which
# is how `files.declare` gets an element to name (09 §Escape hatch).
wf = Workflow("feature", assets="./static")
declare_files(wf)
declare_cron(wf)

#: Whether a person is asked before anything reaches `main`. **Off by
#: default**, which is a change: the node stays in the graph and still
#: routes, it simply does not stop.
#:
#: The reason is not that the question was worthless — it is that waiting
#: for it was. A `human_input` gives its worker slot back for the duration
#: of the wait (04 §Waiting), and on a capacity-1 pool that is the one
#: moment a stale `ready` task can claim the slot. An answered `approve`
#: then queues behind whatever took it, which is how a merge that was
#: approved sat unmerged behind a second lineage of its own run (D203).
#: `FEATURE_ATTENDED=1` puts the question back.
ATTENDED = os.environ.get("FEATURE_ATTENDED", "0") == "1"


@wf.node(start=True, retries=1, timeout=None)
async def prompt(prepare, *, payload):
    """Rewrite what the operator typed into what the architect will read.

    Before anything is branched: it only reads, so it runs against the
    checkout as it stands. `timeout=None` because the node's own budget
    is the agent's (`AGENT_TIMEOUT`), and two caps on one wait means the
    tighter one fires and the other is decoration.
    """

    title = _title(payload)
    description = str(payload.get("description", "")).strip()
    result = await PromptAgent().run(
        f"An operator asked for: {title}\n\n"
        f"{description or '(no further description was given)'}\n\n"
        "Read the request against this repository and rewrite it as the "
        "brief the architect after you will design from."
    )
    if not result.ok:
        raise RuntimeError(
            f"the prompt rewriter did not finish: {result.error or result.stop_reason}"
        )
    brief: Brief = result.output
    await _log(f"prompt: {brief.description}")
    return prepare(
        {
            **payload,
            "original_description": description,
            "description": brief.description,
            "brief": brief.model_dump(),
        }
    )


@wf.node(retries=0, timeout=600)
async def prepare(planner, *, payload):
    """Branch and worktree from `origin/main`. No agent decides where
    work goes.

    `retries=0` because cutting a worktree is not improved by doing it
    twice; a half-made one is evidence to read.
    """

    return planner(await steps.prepare(payload))


@wf.node(retries=1, timeout=None)
async def planner(implement, *, payload):
    """Architect the change and file the plan the implementer follows.

    On the branch, so the plan is part of the feature and lands in the
    same merge commit as the code it describes — a plan that lived only
    in a run's payload would be gone the moment the run was pruned.

    **The plan is read back off the branch, not off the answer.** The
    agent says it wrote a file; git says whether it did, and
    :func:`~workflows.shared.sandbox.plan_docs` says whether it is the
    one `implement` will actually resolve. A plan under a name the glob
    misses is a plan nobody reads, and the first sign of it would be an
    implementer building from nothing.

    Committing here is why `gate` counts from ``plan_base`` rather than
    from ``base``: this commit is not the implementer's work, and a gate
    that counted it would stop noticing an implementer that did nothing.
    """

    title = _title(payload)
    branch = payload["branch"]
    description = str(payload.get("description", "")).strip()
    brief = payload.get("brief") or {}
    out_of_scope = "\n".join(f"- {one}" for one in brief.get("out_of_scope", []))
    questions = "\n".join(f"- {one}" for one in brief.get("open_questions", []))

    prompt_text = (
        f"Design {title} and write its plan. You are on branch `{branch}`; "
        f"commit the plan file on it.\n\n"
        f"The plan file must be `docs/plans/{title}-<slug>.md` — the "
        f"implementer resolves it by that prefix.\n\n## The request\n\n"
        f"{description}"
    )
    if out_of_scope:
        prompt_text += f"\n\n## Out of scope\n{out_of_scope}"
    if questions:
        prompt_text += (
            f"\n\n## Open questions from the brief\n{questions}\n\n"
            "Settle these by reading the specs and the code. Where the "
            "documents are silent, make the boring choice and say in the "
            "plan that you made it."
        )

    tree = _tree(payload)
    result = await PlannerAgent(cwd=str(tree)).run(prompt_text)
    if not result.ok:
        raise RuntimeError(
            f"the architect did not finish: {result.error or result.stop_reason}"
        )
    plan: PlanDoc = result.output

    found = plan_docs(tree, title)
    if not found:
        raise RuntimeError(
            f"{title}: the architect reported `{plan.plan}`, but no file "
            f"matches `docs/plans/{title}*.md`. The implementer resolves the "
            "plan by that prefix and would find nothing."
        )
    uncommitted = await git("status", "--porcelain", "--", "docs/plans", cwd=tree)
    if uncommitted:
        raise RuntimeError(
            f"{title}: the plan is not committed on `{branch}`:\n{uncommitted}"
        )

    plan_base = await git("rev-parse", "HEAD", cwd=tree)
    await _log(f"planner: {', '.join(found)}\n{plan.summary}")
    return implement({**payload, "plan": plan.model_dump(), "plan_base": plan_base})


@wf.node(retries=1, timeout=None)
async def implement(gate, *, payload):
    """The agent takes the feature, in the worktree.

    `timeout=None` because the node's own budget is the agent's
    (`AGENT_TIMEOUT`), and two caps on one wait means the tighter one
    fires and the other is decoration.
    """

    return gate(await steps.implement(payload, ImplementerAgent))


@wf.node(retries=0, timeout=None)
async def gate(review, implement, *, payload):
    """Deterministic: git, then the gate in the worktree.

    The agent's account of either is not consulted. `retries=0`: a red
    gate is not a transient failure, it is an answer, and the answer
    goes back to `implement` with the tail that explains it.
    """

    passed, out = await steps.gate(payload)
    return review(out) if passed else implement(out)


@wf.node(retries=1, timeout=None)
async def review(qa, implement, *, payload):
    """A second model reads the whole branch diff, and the gate's output.

    It is told what the suite did so it knows what the suite did *not*
    prove: green is agreement, not correctness.
    """

    title, branch, base = _title(payload), payload["branch"], payload["base"]
    tree = _tree(payload)
    log = await git("log", "--format=%h %s", f"{base}..HEAD", cwd=tree)
    stat = await git("diff", "--stat", f"{base}..HEAD", cwd=tree)

    result = await ReviewerAgent(cwd=str(tree)).run(
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

    result = await QAAgent(cwd=str(_tree(payload))).run(
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
async def approve(publish, halted, *, payload):
    """The human gate, and the only node that is optional.

    With `FEATURE_ATTENDED=0` the pipeline merges its own passing work
    and review and QA are the last word before `main`. Waiting here does
    not hold the pool: a `human_input` gives its worker slot back for the
    duration (04 §Waiting).
    """

    title = _title(payload)
    if not ATTENDED:
        return publish(payload)

    answer = await human_input(
        f"{title}: gate green, review passed, QA passed on "
        f"`{payload['branch']}` — merge to main?",
        options=["merge", "stop"],
    )
    await _log(f"approve: operator said {answer!r}")
    return publish(payload) if answer == "merge" else halted(payload)


@wf.node(retries=0, timeout=None)
async def publish(merge, implement, *, payload):
    """Push, open the pull request, wait for CI — after every verdict.

    `retries=0` for the reason `gate` has it: a red CI is an answer,
    and it goes back to `implement` with the failed jobs' log.
    """

    passed, out = await steps.publish(payload)
    return merge(out) if passed else implement(out)


@wf.node(retries=0, timeout=900)
async def merge(*, payload):
    """Merge the pull request; the worktree and the branch are gone.

    `retries=0`: a merge that half happened is not improved by doing it
    again.
    """

    return await steps.merge(payload)


@wf.node(retries=0, timeout=60)
async def halted(*, payload):
    """Terminal: the operator said stop. The worktree and branch stay;
    nothing was pushed."""

    return steps.halt(payload)
