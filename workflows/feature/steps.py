"""The steps `feature` and `quick` share, as plain functions.

A node body is `@wf.node`-decorated per workflow, because its signature
is that workflow's graph (rule 1). What the deterministic nodes *do* —
cut the worktree, count the commits, run the gate, publish the branch,
merge the pull request — is the same in both, so it lives here and each
workflow's node is a few lines that call a step and route on what it
returns. A step never routes: it returns a payload, or a verdict and a
payload, and the node holding the edges decides where that goes.

Everything here runs in the run's own worktree (:mod:`.sandbox`, D263).
``payload["tree"]`` is that directory from `prepare` on; the checkout
itself is used only for the repository's own things — the worktree
list, the branches.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from athanore import current_task

from .agents import ImplementerAgent
from .models import TaskReport
from .sandbox import (
    GATE_COMMAND,
    add_worktree,
    branch_name,
    gh,
    gh_try,
    git,
    git_try,
    plan_docs,
    remove_worktree,
    run_gate,
    unique_branch,
    watch_checks,
)

__all__ = [
    "MAX_ATTEMPTS",
    "MAX_LOOPS",
    "bounce",
    "gate",
    "halt",
    "implement",
    "log",
    "merge",
    "prepare",
    "subject",
    "title_of",
    "tree_of",
]

#: Loop-backs to `implement` per lane, and in total, before rule 3 ends
#: the run. Three and six are v0's numbers, kept because they were tuned
#: on a real build: a lane that has bounced three times is not converging,
#: and the branch is more useful read than retried.
MAX_LOOPS = int(os.environ.get("FEATURE_MAX_LOOPS", "3"))
MAX_ATTEMPTS = int(os.environ.get("FEATURE_MAX_ATTEMPTS", "6"))


async def log(text: str) -> None:
    """Append to the run's work log, which is what the next stage reads."""

    await current_task().services.log.append(text)


def title_of(payload: dict[str, Any]) -> str:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise RuntimeError("a run needs a title: the feature or task id")
    return title


def tree_of(payload: dict[str, Any]) -> Path:
    """The run's worktree, which `prepare` put in the payload."""

    tree = str(payload.get("tree", "")).strip()
    if not tree:
        raise RuntimeError("no worktree in the payload: `prepare` has not run")
    return Path(tree)


def subject(payload: dict[str, Any]) -> str:
    """`T083: <headline>` — the PR title, and so the merge commit's.

    A headline that already opens with the title is not prefixed again:
    an implementer told the run is `T083` tends to write `T083: ...`,
    and `T083: T083: ...` on `main` says nothing twice.
    """

    report = payload.get("report") or {}
    headline = str(payload.get("headline") or report.get("headline") or "").strip()
    title = title_of(payload)
    if not headline:
        return title
    if headline.lower().startswith(f"{title.lower()}:"):
        return headline
    return f"{title}: {headline}"


def bounce(payload: dict[str, Any], lane: str, feedback: str) -> dict[str, Any]:
    """The payload for a loop-back to `implement`, with the caps applied.

    Counting lives here rather than in each lane because the cap is one
    policy, and a lane that counted for itself would drift from the
    others. Blowing either cap raises: rule 3 decides what a run that is
    not converging does, and what it does is stop with its worktree and
    branch intact.
    """

    loops = {**payload.get("loops", {})}
    loops[lane] = loops.get(lane, 0) + 1
    attempts = int(payload.get("attempts", 1)) + 1

    if loops[lane] > MAX_LOOPS:
        raise RuntimeError(
            f"{title_of(payload)}: {lane} has sent the work back {loops[lane]} "
            f"times (cap {MAX_LOOPS}). Stopping with the worktree intact.\n\n"
            f"{feedback}"
        )
    if attempts > MAX_ATTEMPTS:
        raise RuntimeError(
            f"{title_of(payload)}: {attempts} implement attempts (cap "
            f"{MAX_ATTEMPTS}). Stopping with the worktree intact.\n\n{feedback}"
        )
    return {**payload, "loops": loops, "attempts": attempts, "feedback": feedback}


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


async def prepare(payload: dict[str, Any]) -> dict[str, Any]:
    """Cut the run's branch and worktree from `origin/main`.

    `main` is what `origin` says it is — a PR merged from anywhere since
    the last run is on the remote — and the checkout's own `main` is
    neither read nor moved: the operator may be on it, mid-edit. The
    fetch is the one network round trip; everything else is local.
    """

    title = title_of(payload)
    await git("fetch", "--quiet", "origin", "main")
    base = await git("rev-parse", "origin/main")
    branch = await unique_branch(branch_name(title))
    tree = await add_worktree(branch)
    await log(f"prepare: {branch} from origin/main at {base[:12]} in {tree}")
    return {
        **payload,
        "branch": branch,
        "base": base,
        "tree": str(tree),
        "attempts": 1,
        "loops": {},
    }


# --------------------------------------------------------------------------
# implement
# --------------------------------------------------------------------------


async def implement(
    payload: dict[str, Any], agent: type[ImplementerAgent] = ImplementerAgent
) -> dict[str, Any]:
    """One attempt of the implementer in the worktree; the report in the
    payload.

    ``agent`` is the seat: `feature` sends its implementer, `quick` its
    cheaper one. The prompt is the same — the description, the plan if
    a planner wrote one, and the feedback if a previous attempt was sent
    back — so the two differ in who reads it and not in what they read.
    """

    title, branch, tree = title_of(payload), payload["branch"], tree_of(payload)
    description = str(payload.get("description", "")).strip()
    feedback = str(payload.get("feedback", "")).strip()

    prompt = f"Implement {title} on branch `{branch}`."
    if description:
        prompt += f"\n\n{description}"
    if plans := plan_docs(tree, title):
        prompt += (
            "\n\nThe implementation plan is "
            + ", ".join(f"`{p}`" for p in plans)
            + ". Follow it: it fences the scope and says what done means."
        )
    if feedback:
        prompt += (
            f"\n\nA previous attempt did not pass. Fix this, and only this:\n{feedback}"
        )

    result = await agent(cwd=str(tree)).run(prompt)
    if not result.ok:
        raise RuntimeError(
            f"the implementer did not finish: {result.error or result.stop_reason}"
        )
    report: TaskReport = result.output
    await log(f"implement: {report.headline}")
    # The first attempt names the feature; later attempts name the fix,
    # and the merge commit wants the former.
    headline = str(payload.get("headline") or report.headline)
    return {**payload, "report": report.model_dump(), "headline": headline}


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------


async def gate(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Deterministic, in three parts; ``(passed, payload)``.

    git says whether there is anything to test; the gate, run in the
    worktree, says whether it passes; then the branch is pushed, its
    pull request opened or brought up to date, and CI on it — the same
    gate on a runner, and the run that counts (D260) — waited for. The
    agent's account of any of it is not consulted.

    On a pass the payload carries ``head``, ``commits``, ``gate`` (the
    local tail) and ``pr``. On a fail it is the :func:`bounce` payload
    for `implement`, feedback included, or :func:`bounce` has raised.
    """

    branch, base, tree = payload["branch"], payload["base"], tree_of(payload)
    # The plan, when a planner wrote one, is already a commit on this
    # branch, so "did the implementer commit anything" is counted from
    # there. From `base` it would always be yes, and the check would stop
    # working.
    since = str(payload.get("plan_base") or base)

    on = await git("rev-parse", "--abbrev-ref", "HEAD", cwd=tree)
    if on != branch:
        raise RuntimeError(
            f"the worktree is on {on!r}, not {branch!r}: the agent moved it "
            "off its branch. Stopping."
        )

    dirty = await git("status", "--porcelain", "--untracked-files=no", cwd=tree)
    commits = (await git("rev-list", f"{since}..HEAD", cwd=tree)).split()
    if dirty or not commits:
        problem = (
            "You left tracked changes uncommitted; everything the feature "
            f"needs must be committed on `{branch}`:\n{dirty}"
            if dirty
            else f"You made no commit on `{branch}`. There is nothing to review."
        )
        await log(f"gate: rejected before running\n{problem}")
        return False, bounce(payload, "gate", problem)

    code, tail = await run_gate(tree)
    await log(f"gate: {'PASS' if code == 0 else f'FAIL ({code})'}\n{tail}")
    if code:
        return False, bounce(
            payload,
            "gate",
            f"`{GATE_COMMAND}` failed with exit code {code}. Its last lines:\n{tail}",
        )

    # Green here: publish the branch and let CI say so on a runner. A
    # loop-back pushes the same branch again and the PR opened for it
    # follows the branch, so one PR carries every attempt.
    pr = await _publish(payload)
    code, ci = await watch_checks(branch, cwd=tree)
    await log(f"gate: CI {'PASS' if code == 0 else f'FAIL ({code})'} on {pr}\n{ci}")
    if code:
        return False, bounce(
            payload,
            "gate",
            f"`{GATE_COMMAND}` passed here but CI on the pull request ({pr}) "
            f"failed with exit code {code}. Its last lines:\n{ci}",
        )

    return True, {
        **payload,
        "head": commits[0],
        "commits": commits,
        "gate": tail,
        "pr": pr,
    }


async def _publish(payload: dict[str, Any]) -> str:
    """Push the branch; open its pull request, or bring the open one up
    to date. Returns the PR's URL.

    The title and body are the implementer's headline and summary, which
    can change between attempts, so an existing PR is edited rather
    than left with the first attempt's words: the merge commit is made
    from them (AGENTS.md §Landing a change).
    """

    branch, tree = payload["branch"], tree_of(payload)
    report = payload.get("report") or {}
    title = subject(payload)
    body = str(report.get("summary", "")).strip()

    await git("push", "--quiet", "-u", "origin", branch, cwd=tree)
    found = await gh(
        "pr",
        "list",
        "--head",
        branch,
        "--state",
        "open",
        "--json",
        "number,url",
        "--jq",
        '.[0] // empty | "\\(.number) \\(.url)"',
        cwd=tree,
    )
    if found.strip():
        number, url = found.split(None, 1)
        # Through the REST API, not `gh pr edit`: that verb still asks
        # GraphQL for the PR's classic project cards, which GitHub now
        # refuses, and the whole edit fails with it (gh 2.45).
        await gh(
            "api",
            "--method",
            "PATCH",
            f"repos/{{owner}}/{{repo}}/pulls/{number}",
            "-f",
            f"title={title}",
            "-f",
            f"body={body}",
            "--silent",
            cwd=tree,
        )
        await log(f"gate: pushed {branch}; updated {url.strip()}")
        return url.strip()
    url = await gh(
        "pr",
        "create",
        "--head",
        branch,
        "--base",
        "main",
        "--title",
        title,
        "--body",
        body,
        cwd=tree,
    )
    url = url.splitlines()[-1].strip()
    await log(f"gate: pushed {branch}; opened {url}")
    return url


# --------------------------------------------------------------------------
# merge, halt
# --------------------------------------------------------------------------


async def merge(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge the pull request; drop the worktree and the branch.

    One merge commit per feature with its work underneath, so reverting a
    feature is reverting one commit. GitHub makes it (`--merge`, never
    squash or rebase) with the PR's title and body as its message, which
    is why :func:`_publish` keeps those current. Nothing is checked out
    or pulled: the operator's checkout is theirs, and the next `prepare`
    fetches. The branch is deleted on `origin` here rather than by
    `gh --delete-branch`, which would also try to check `main` out in
    the worktree — and `main` is checked out in the checkout.
    """

    title, branch, base = title_of(payload), payload["branch"], payload["base"]
    tree = tree_of(payload)
    report = payload.get("report") or {}
    title_line = subject(payload)
    pr = str(payload.get("pr", "")).strip()

    # QA may have scribbled on tracked files while exercising the
    # feature. Everything real was committed before the gate, so this is
    # scratch — but say what is being dropped first.
    scratch = await git("diff", "--stat", cwd=tree)
    if scratch:
        await log(f"merge: discarding post-gate scratch in the tree:\n{scratch}")
        await git("checkout", "--", ".", cwd=tree)

    code, out = await gh_try(
        "pr",
        "merge",
        branch,
        "--merge",
        "--subject",
        title_line,
        "--body",
        str(report.get("summary", "")),
        cwd=tree,
    )
    if code:
        raise RuntimeError(f"{title}: merge of {pr or branch} failed:\n{out}")

    merge_commit = await gh(
        "pr",
        "view",
        pr or branch,
        "--json",
        "mergeCommit",
        "--jq",
        ".mergeCommit.oid",
        cwd=tree,
    )
    await remove_worktree(tree)
    await git_try("branch", "-D", branch)
    await git_try("push", "--quiet", "origin", "--delete", branch)
    await log(
        f"merge: {title_line}\n{merge_commit[:12]} on main via {pr}; "
        f"{branch} and {tree} removed"
    )

    return {
        "title": title,
        "merged": True,
        "merge_commit": merge_commit,
        "pr": pr,
        "base": base,
        "commits": payload.get("commits", []),
        "report": report,
        "review": payload.get("review"),
        "qa": payload.get("qa"),
    }


def halt(payload: dict[str, Any]) -> dict[str, Any]:
    """Terminal: the operator said stop. The worktree, branch and PR stay."""

    return {
        "title": title_of(payload),
        "merged": False,
        "branch": payload["branch"],
        "tree": payload.get("tree"),
        "pr": payload.get("pr"),
        "report": payload.get("report"),
    }
