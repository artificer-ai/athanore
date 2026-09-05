"""`v1_feature` — one seat that takes one task of the serial plan.

    implement ──▶ gate ──▶ review ──▶ done
        ▲          │         │
        └──────────┴─────────┘   (both verdicts loop back, capped)

Rule 1: the signature is the graph. Rule 2: the return value is the
routing. Rule 3: the exception is the failure policy — blowing the loop
cap raises, so v0's retry/dead-letter path ends the run as `failed` where
the TUI shows it.

Adding another seat is one module, one `wf`, one `register`.
"""

from athanore import AthanoreWorkflow, current_task, human_input

from .models import ReviewVerdict, TaskReport
from .sandbox import BUILDER_ATTENDED, BUILDER_MAX_LOOPS, SandboxAgent, run_gate

wf = AthanoreWorkflow("v1_feature")

GATE_COMMAND = "./scripts/test.sh"


class ImplementerAgent(SandboxAgent):
    output_model = TaskReport
    system_prompt = (
        "You are implementing exactly one task of "
        "`docs/v1/17-serial-task-plan.md` in the checkout at cwd.\n"
        "\n"
        "Read `AGENTS.md`, `docs/v1/README.md`, the task, and every spec "
        "section the task cites. Do only that task: nothing from the task "
        "before it, nothing from the task after it.\n"
        "\n"
        f"Run the gate (`{GATE_COMMAND}`) until it is green. Commit on "
        "`main` with the message prefixed by the task id (`T012: ...`). "
        "Append your deliverable to the work log, then submit a "
        "TaskReport."
    )


class ReviewerAgent(SandboxAgent):
    output_model = ReviewVerdict
    system_prompt = (
        "You are reviewing one commit against one task of "
        "`docs/v1/17-serial-task-plan.md`.\n"
        "\n"
        "Run `git show <commit>` and compare it against the task's **Do**, "
        "**Tests** and **Done** blocks and the spec sections it cites. "
        "Reject anything outside the task that moved. Reject a stub, a "
        "`TODO`, or a narrowed scope — `AGENTS.md` §Quality bar is part of "
        "the task.\n"
        "\n"
        "Give a verdict only. Do not fix anything yourself."
    )


def _log(node: str, text: str) -> None:
    ctx = current_task()
    ctx.store.add_log(ctx.run_id, node, "engine", text)


def _loop(payload: dict) -> int:
    return int(payload.get("loop", 0))


def _task_id(payload: dict) -> str:
    return str(payload.get("title", "")).strip()


@wf.node(start=True)
async def implement(gate, *, payload):
    """The agent takes the task. `title` is the task id; `description` is
    optional operator notes. On a loop-back the work log already carries
    the gate tail or the reviewer's notes, so no prompt threading needed."""
    task_id = _task_id(payload)
    notes = str(payload.get("description", "")).strip()
    feedback = str(payload.get("feedback", "")).strip()

    prompt = f"Implement {task_id}."
    if notes:
        prompt += f"\n\nOperator notes: {notes}"
    if feedback:
        prompt += (
            "\n\nA previous attempt did not pass. Fix this and only this:\n"
            f"{feedback}"
        )

    result = await ImplementerAgent().run(prompt)
    return gate({**payload, "report": result.output.model_dump()})


@wf.node()
async def gate(review, implement, *, payload):
    """Deterministic: the gate decides, not an agent."""
    code, tail = await run_gate()
    _log("gate", f"gate {'PASS' if code == 0 else f'FAIL ({code})'}\n{tail}")
    if code == 0:
        return review(payload)

    loop = _loop(payload) + 1
    if loop >= BUILDER_MAX_LOOPS:
        raise RuntimeError(
            f"{_task_id(payload)}: gate still red after {loop} rounds"
        )
    return implement({**payload, "feedback": tail, "loop": loop})


@wf.node()
async def review(implement, done, *, payload):
    """A second agent checks the commit against the task, and only that."""
    report = payload.get("report") or {}
    commit = str(report.get("commit", "HEAD")).strip() or "HEAD"
    result = await ReviewerAgent().run(
        f"Review commit {commit} against {_task_id(payload)}."
    )
    verdict: ReviewVerdict = result.output
    _log("review", f"review {'ok' if verdict.ok else 'rejected'}\n{verdict.notes}")
    if verdict.ok:
        return done(payload)

    loop = _loop(payload) + 1
    if loop >= BUILDER_MAX_LOOPS:
        raise RuntimeError(
            f"{_task_id(payload)}: review still rejecting after {loop} rounds"
        )
    return implement({**payload, "feedback": verdict.notes, "loop": loop})


@wf.node()
async def done(*, payload):
    """Terminal. Attended runs stop here so a human can read the commit in
    the TUI before the next task is dispatched."""
    task_id = _task_id(payload)
    if BUILDER_ATTENDED:
        answer = await human_input(
            f"{task_id} passed review — continue?",
            options=["continue", "stop"],
        )
        _log("done", f"{task_id}: operator said {answer!r}")
    return {"task_id": task_id, "report": payload.get("report")}
