"""`v1_feature` — one seat that takes one feature from a branch to main.

    prepare ─▶ implement ─▶ gate ─▶ review ─▶ qa ─▶ approve ─▶ merge
                  ▲           │        │       │        │
                  └───────────┴────────┴───────┘        └─▶ halted

Rule 1: the signature is the graph. Rule 2: the return value is the
routing. Rule 3: the exception is the failure policy — blowing a loop cap
raises, so v0's retry/dead-letter path ends the run as `failed` where the
TUI shows it, with the branch left behind for you to read.

`prepare`, `gate`, `approve`, `merge` and `halted` are pure Python: git
and an exit code decide, never an agent. Only `implement`, `review` and
`qa` spend tokens, and they run cheapest-check-first — the free gate
before a paid review, the review before the expensive QA.

Adding another seat is one module, one `wf`, one `register`.
"""

from athanore import AthanoreWorkflow, current_task, human_input

from .models import QAVerdict, ReviewVerdict, TaskReport
from .sandbox import (
    BUILDER_ATTENDED,
    BUILDER_MAX_ATTEMPTS,
    BUILDER_MAX_LOOPS,
    IMPLEMENT_MODEL,
    QA_MODEL,
    REVIEW_MODEL,
    SandboxAgent,
    branch_name,
    git,
    git_try,
    plan_docs,
    run_gate,
    unique_branch,
)

wf = AthanoreWorkflow("v1_feature")

GATE_COMMAND = "./scripts/test.sh"


class ImplementerAgent(SandboxAgent):
    model = IMPLEMENT_MODEL
    output_model = TaskReport
    system_prompt = (
        "You implement one feature in the checkout at cwd, on a branch that "
        "is already checked out for you.\n"
        "\n"
        "The description you are given is the specification. It usually "
        "points at a plan document — most often one task of "
        "`docs/v1/17-serial-task-plan.md`. When it does, read that section "
        "and every spec section it cites, and do exactly that task: nothing "
        "from the task before it, nothing from the task after it. Read "
        "`AGENTS.md` and `docs/v1/README.md` first; `AGENTS.md` §Quality bar "
        "is part of every task. No stubs, no `TODO` left behind, no narrowed "
        "scope, errors handled rather than swallowed.\n"
        "\n"
        "Working rules:\n"
        "- Stay on the branch you were given. Never switch branches, never "
        "merge, never commit on `main`: the workflow merges for you once the "
        "gate, the review and QA have all passed.\n"
        "- Commit everything on that branch. A clean `git status` is part of "
        "being done — anything left uncommitted is invisible to the gate and "
        "to the reviewer, and the workflow will bounce the task back to you "
        "for it.\n"
        f"- Run the gate (`{GATE_COMMAND}`) until it is green before you "
        "submit. The workflow runs it again itself; you do not get to decide "
        "whether your own work passed.\n"
        "- Append your deliverable to the work log, then submit a TaskReport."
    )


class ReviewerAgent(SandboxAgent):
    model = REVIEW_MODEL
    output_model = ReviewVerdict
    system_prompt = (
        "You are reviewing one branch against one task. Be harsh: you are "
        "the last reader before this lands on `main`, and a second model "
        "wrote it.\n"
        "\n"
        "Read the diff (`git diff <base>..HEAD`, `git log`), the task, and "
        "every spec section the task cites. Reject:\n"
        "- anything the task did not ask for, and anything the task asked "
        "for that is missing;\n"
        "- a stub, a `TODO`, a `pass` where behaviour belongs, hard-coded "
        "sample data standing in for a real code path, mocked behaviour "
        "outside tests;\n"
        "- a swallowed error, an unimplemented edge case the spec names, a "
        "test that asserts nothing or only asserts what the implementation "
        "happens to do;\n"
        "- anything that contradicts `AGENTS.md` §Architecture rules — the "
        "three rules, the layering, the small core, the one wire contract.\n"
        "\n"
        "A green gate is not a passing review: the gate only proves the "
        "suite ran. Put every defect in `blocking`, one per entry, naming "
        "the file. Give a verdict only — do not fix anything, do not commit, "
        "do not switch branches."
    )


class QAAgent(SandboxAgent):
    model = QA_MODEL
    output_model = QAVerdict
    system_prompt = (
        "You are QA. The suite is green and the review passed; your job is "
        "to find out whether the feature actually works when a person uses "
        "it, in whatever way this change can be exercised:\n"
        "\n"
        "- import it and call it (`uv run python -c ...`);\n"
        "- run the CLI (`uv run athanore --help`, and the subcommand the "
        "change touches);\n"
        "- start the app in the background (`./scripts/run.sh`), wait for "
        "`GET /api/health`, then call the endpoints the change touches with "
        "curl and read the responses — status codes, shapes, error paths;\n"
        "- drive the SPA with Playwright and chromium when there is a page "
        "to open;\n"
        "- run the example workflows on `FakeACPAgent`.\n"
        "\n"
        "Read the implementer's `how_to_exercise` and start there, but do "
        "not stop there: try the failure paths too. Paste the commands you "
        "ran and their real output as evidence — a check you did not "
        "actually run is a check that did not happen.\n"
        "\n"
        "A change with no runnable surface yet is not a failure: verify what "
        "can be verified, list it, and pass it. Fix nothing, commit nothing, "
        "switch no branches, and leave the working tree as you found it — "
        "stop anything you started."
    )


# -- helpers -----------------------------------------------------------------


def _log(node: str, text: str) -> None:
    ctx = current_task()
    ctx.store.add_log(ctx.run_id, node, "engine", text)


def _task_id(payload: dict) -> str:
    return str(payload.get("title", "")).strip()


def _halt_queue(reason: str) -> list[str]:
    """Stop the rest of the plan. Capacity 1 makes the queue serial, but a
    run that fails still frees the slot, and the next task would branch
    from a `main` that is missing the work it builds on. Pausing is
    reversible from the TUI; cancelling is not."""
    ctx = current_task()
    store = ctx.store
    paused = []
    for run in store.list_runs():
        if run["id"] == ctx.run_id or run.get("workflow") != ctx.workflow:
            continue
        if run.get("status") != "running":
            continue
        if store.pause_run(run["id"]):
            store.event(run["id"], None, "run_paused", {"note": reason})
            paused.append(run["id"])
    if paused:
        _log("engine", f"paused {len(paused)} queued run(s): {reason}")
    return paused


def _bounce(payload: dict, lane: str, feedback: str) -> dict:
    """The payload for a loop back to `implement`, or a raise when this
    task has had its rounds. Each lane counts separately — a gate failure
    and a review rejection are different problems — with a total cap so a
    task cannot ping-pong between lanes forever."""
    task_id = _task_id(payload)
    loops = dict(payload.get("loops") or {})
    loops[lane] = loops.get(lane, 0) + 1
    attempts = int(payload.get("attempts", 1)) + 1
    branch = payload.get("branch")

    if loops[lane] >= BUILDER_MAX_LOOPS:
        _halt_queue(f"{task_id} failed in {lane}")
        raise RuntimeError(
            f"{task_id}: {lane} still rejecting after {loops[lane]} rounds; "
            f"branch {branch} left for inspection"
        )
    if attempts > BUILDER_MAX_ATTEMPTS:
        _halt_queue(f"{task_id} exhausted its attempts")
        raise RuntimeError(
            f"{task_id}: {attempts - 1} implementation rounds without "
            f"passing; branch {branch} left for inspection"
        )

    history = list(payload.get("history") or [])
    history.append(f"[{lane}] {feedback}")
    return {
        **payload,
        "loops": loops,
        "attempts": attempts,
        "feedback": feedback,
        "history": history[-BUILDER_MAX_ATTEMPTS:],
    }


# -- the graph ---------------------------------------------------------------


@wf.node(start=True)
async def prepare(implement, *, payload):
    """Branch from `main`. Pure Python: no agent decides where work goes.

    A dirty checkout is a hard stop rather than something to clean up —
    the uncommitted work is somebody's, and it is not this run's to
    throw away."""
    task_id = _task_id(payload)
    if not task_id:
        raise RuntimeError("a run needs a title: the feature or task id")

    dirty = await git("status", "--porcelain")
    if dirty:
        raise RuntimeError(
            "the checkout has uncommitted changes; refusing to branch over "
            f"them:\n{dirty}"
        )

    await git("checkout", "main")
    base = await git("rev-parse", "HEAD")
    branch = await unique_branch(branch_name(task_id))
    await git("switch", "-c", branch)
    _log("prepare", f"{branch} from main at {base[:12]}")

    return implement(
        {
            **payload,
            "branch": branch,
            "base": base,
            "attempts": 1,
            "loops": {},
        }
    )


@wf.node()
async def implement(gate, *, payload):
    """The agent takes the feature. `title` is the id, `description` is the
    specification — usually a pointer at a task of the plan."""
    task_id = _task_id(payload)
    description = str(payload.get("description", "")).strip()
    feedback = str(payload.get("feedback", "")).strip()
    branch = payload["branch"]

    prompt = f"Implement {task_id} on branch `{branch}`."
    if description:
        prompt += f"\n\n{description}"
    plans = plan_docs(task_id)
    if plans:
        prompt += (
            "\n\nThe implementation plan is "
            + ", ".join(f"`{p}`" for p in plans)
            + ". Follow it: it fences the scope against the tasks either side "
            "and says what done means."
        )
    if feedback:
        prompt += (
            "\n\nA previous attempt did not pass. Fix this, and only this:\n"
            f"{feedback}"
        )

    result = await ImplementerAgent().run(prompt)
    report = result.output.model_dump()
    _log("implement", f"{task_id}: {report['headline']}")
    # The first attempt names the task; later attempts name the fix. The
    # merge commit wants the former.
    headline = str(payload.get("headline") or report["headline"])
    return gate({**payload, "report": report, "headline": headline})


@wf.node()
async def gate(review, implement, *, payload):
    """Deterministic, in two halves: git says whether there is something to
    review, then `./scripts/test.sh` says whether it passes. The agent's
    own account of either is not consulted."""
    branch, base = payload["branch"], payload["base"]

    on = await git("rev-parse", "--abbrev-ref", "HEAD")
    if on != branch:
        _halt_queue(f"{_task_id(payload)} left the checkout on {on!r}")
        raise RuntimeError(
            f"the checkout is on {on!r}, not {branch!r}: the agent moved off "
            "its branch, so `main` may have been written to. Stopping."
        )

    dirty = await git("status", "--porcelain", "--untracked-files=no")
    commits = (await git("rev-list", f"{base}..HEAD")).split()
    if dirty or not commits:
        problem = (
            "You left tracked changes uncommitted; everything the task needs "
            f"must be committed on `{branch}`:\n{dirty}"
            if dirty
            else f"You made no commit on `{branch}`. There is nothing to review."
        )
        _log("gate", f"gate REJECTED before running\n{problem}")
        return implement(_bounce(payload, "gate", problem))

    code, tail = await run_gate()
    _log("gate", f"gate {'PASS' if code == 0 else f'FAIL ({code})'}\n{tail}")
    if code == 0:
        return review({**payload, "head": commits[0], "commits": commits, "gate": tail})

    return implement(
        _bounce(
            payload,
            "gate",
            f"`{GATE_COMMAND}` failed with exit code {code}. Its last lines:\n{tail}",
        )
    )


@wf.node()
async def review(qa, implement, *, payload):
    """A second model, on a different family from the implementer, reads
    the whole branch diff — and the gate output, so it knows what the
    suite did and did not prove."""
    task_id, branch, base = _task_id(payload), payload["branch"], payload["base"]
    log = await git("log", "--format=%h %s", f"{base}..HEAD")
    stat = await git("diff", "--stat", f"{base}..HEAD")

    result = await ReviewerAgent().run(
        f"Review branch `{branch}` against {task_id}.\n\n"
        f"{str(payload.get('description', '')).strip()}\n\n"
        f"The diff is `git diff {base}..HEAD` — read all of it.\n\n"
        f"Commits:\n{log}\n\nFiles:\n{stat}\n\n"
        f"The gate ({GATE_COMMAND}) passed. Its last lines:\n"
        f"{payload.get('gate', '')}"
    )
    verdict: ReviewVerdict = result.output
    _log(
        "review",
        f"review {'ok' if verdict.ok else 'REJECTED'}\n"
        + "\n".join(f"- {b}" for b in verdict.blocking)
        + f"\n{verdict.notes}",
    )
    if verdict.ok:
        return qa({**payload, "review": verdict.model_dump()})

    blocking = "\n".join(f"- {b}" for b in verdict.blocking) or verdict.notes
    return implement(
        _bounce(payload, "review", f"The reviewer rejected the branch:\n{blocking}")
    )


@wf.node()
async def qa(approve, implement, *, payload):
    """Exercise it for real: the suite passing is not the feature working."""
    task_id, branch = _task_id(payload), payload["branch"]
    report = payload.get("report") or {}

    result = await QAAgent().run(
        f"QA {task_id} on branch `{branch}`.\n\n"
        f"{str(payload.get('description', '')).strip()}\n\n"
        f"What was built: {report.get('summary', '')}\n\n"
        f"How the implementer says to exercise it: "
        f"{report.get('how_to_exercise') or '(not stated — work it out)'}"
    )
    verdict: QAVerdict = result.output
    _log(
        "qa",
        f"qa {'ok' if verdict.ok else 'FAILED'}\n"
        + "\n".join(f"- {c}" for c in verdict.checks)
        + f"\n{verdict.notes}",
    )
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


@wf.node()
async def approve(merge, halted, *, payload):
    """The human gate, and the only node that is optional: with
    `BUILDER_ATTENDED=0` the build merges its own passing work. Waiting
    here holds the pool's one slot, which is what keeps the plan serial
    while you read."""
    task_id = _task_id(payload)
    if not BUILDER_ATTENDED:
        return merge(payload)

    answer = await human_input(
        f"{task_id}: gate green, review passed, QA passed on "
        f"`{payload['branch']}` — merge to main?",
        options=["merge", "stop"],
    )
    _log("approve", f"{task_id}: operator said {answer!r}")
    if answer == "merge":
        return merge(payload)

    paused = _halt_queue(f"operator stopped the build at {task_id}")
    return halted({**payload, "paused": paused})


@wf.node()
async def merge(*, payload):
    """`--no-ff` onto main, then the branch is gone: one merge commit per
    feature, with its work underneath, so reverting a task is reverting
    one commit."""
    task_id, branch, base = _task_id(payload), payload["branch"], payload["base"]
    report = payload.get("report") or {}
    headline = str(payload.get("headline") or report.get("headline") or "").strip()

    # QA runs after the gate and may have scribbled on tracked files while
    # exercising the app. Everything real was committed before the gate, so
    # this is scratch — but say what is being dropped before dropping it.
    scratch = await git("diff", "--stat")
    if scratch:
        _log("merge", f"discarding post-gate scratch in the tree:\n{scratch}")
        await git("checkout", "--", ".")

    await git("checkout", "main")
    subject = f"{task_id}: {headline}" if headline else task_id
    code, out = await git_try(
        "merge", "--no-ff", "-m", subject, "-m", str(report.get("summary", "")), branch
    )
    if code:
        await git_try("merge", "--abort")
        await git_try("switch", branch)
        _halt_queue(f"{task_id} would not merge")
        raise RuntimeError(f"{task_id}: merge of {branch} into main failed:\n{out}")

    merge_commit = await git("rev-parse", "HEAD")
    await git("branch", "-d", branch)
    _log("merge", f"{subject}\n{merge_commit[:12]} on main; {branch} deleted")

    return {
        "task_id": task_id,
        "merged": True,
        "merge_commit": merge_commit,
        "base": base,
        "commits": payload.get("commits", []),
        "report": report,
        "review": payload.get("review"),
        "qa": payload.get("qa"),
    }


@wf.node()
async def halted(*, payload):
    """Terminal: the operator said stop. The branch stays, unmerged, and
    the rest of the queue is paused — resume it from the TUI."""
    return {
        "task_id": _task_id(payload),
        "merged": False,
        "branch": payload["branch"],
        "paused_runs": payload.get("paused", []),
        "report": payload.get("report"),
    }
