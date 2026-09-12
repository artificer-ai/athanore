"""git and the gate: everything in this pipeline that is not a model.

The division this module exists to keep is the one the whole workflow is
built on — **an agent never decides whether its own work passed**. Where
the branch went, whether anything was committed, whether the suite is
green and what lands on `main` are all answered here, by git, by `gh`
and by an exit code, and the nodes that call these functions have no
agent in them.

Two facts about where this runs shape the rest:

- **Athanore is on the host, in this checkout's own environment.** There
  is no container around the workflow, so `git` and `./scripts/test.sh`
  are ordinary subprocesses in :data:`CHECKOUT`.
- **The agents are not.** They are dispatched into the dev stack through
  `scripts/agent.sh`, which is the one definition of that sandbox
  (`compose.yaml`, D64). The checkout is mounted at its own host path, so
  a `cwd` means the same thing on both sides of the boundary and an agent
  edits the same files this module then reads with git.

**Every run builds in a git worktree of its own** (D263):
``.worktrees/<branch>`` under the checkout, cut from ``origin/main``.
The operator's checkout is never checked out, dirtied or merged into by
a run, so it is free to be worked in while runs are in flight, and two
runs can be in flight at once. A worktree is under the checkout so the
bind mount carries it — the same path on both sides of the boundary,
as above — and `scripts/_lib.sh` gives it a uv environment of its own
in the container, so two trees never rewrite each other's venv. Every
function here that touches a tree takes it as ``cwd``; :data:`CHECKOUT`
is for the things that belong to the repository rather than to a tree —
the worktree list, the branches, `.athanore/`.

A change lands the way AGENTS.md §Landing a change says every change
does (D260): the branch is pushed, a pull request is opened, CI on it is
the gate that counts, and `gh pr merge` makes the merge commit. `gh` is
the host's, logged in as the operator, so the PR and the merge carry the
operator's account like the commits carry their identity (5f6610e).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

__all__ = [
    "AGENT_SH",
    "CHECKOUT",
    "GATE_COMMAND",
    "GATE_TAIL",
    "WORKTREES",
    "add_worktree",
    "branch_name",
    "gh",
    "gh_try",
    "git",
    "git_try",
    "plan_docs",
    "remove_worktree",
    "run_gate",
    "unique_branch",
    "watch_checks",
]

#: The checkout this workflow maintains: the repository root, three
#: parents up from this file. Derived rather than read from `WORKSPACE`
#: so it is correct when athanore is run from anywhere in the tree — the
#: workflow is on the host, and a host has a shell that may be anywhere.
CHECKOUT = Path(__file__).resolve().parents[2]

#: Where a run's worktree goes: `.worktrees/<branch>`, git-ignored. Under
#: the checkout, not beside it, because the container mounts the checkout
#: and nothing else.
WORKTREES = CHECKOUT / ".worktrees"

#: The one way into the sandbox, absolute. `command` is spawned in the
#: agent's `cwd`, and it works from either side of the container boundary
#: (AGENTS.md §Dispatching agents into the container).
AGENT_SH = CHECKOUT / "scripts" / "agent.sh"

#: The gate, which is the definition of green (D74), as a tree-relative
#: command: :func:`run_gate` runs the tree's own copy. Not `pytest`: the
#: gate is ruff, pyright, import-linter, both test suites, the SPA build,
#: Playwright and the packaging check, and a workflow that ran less than
#: a human runs would be merging on a weaker promise.
GATE_COMMAND = "./scripts/test.sh"

#: How long the gate may take, and how much of its tail is quoted back to
#: the implementer on a failure. The gate builds the SPA and runs
#: Playwright, so it is minutes rather than seconds.
GATE_TIMEOUT = 60 * 60.0
GATE_TAIL = 4000

#: How long the pull request's CI may take before the gate calls it red
#: with a code of its own, and how often `gh pr checks --watch` polls.
#: CI runs the same gate on a runner, in parallel jobs, so it is usually
#: quicker than the local run; the cap is for a runner that never starts.
CHECKS_TIMEOUT = GATE_TIMEOUT
CHECKS_INTERVAL = 30

#: Commits and merges carry the operator's own identity and nothing
#: else: git reads the mounted `~/.gitconfig` and `gh` the operator's
#: login, and neither is overridden here (AGENTS.md §Working a task,
#: step 5).


async def _run(program: str, *args: str, cwd: Path = CHECKOUT) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"},
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def git_try(*args: str, cwd: Path = CHECKOUT) -> tuple[int, str]:
    """One git command in ``cwd``: its exit code and its output.

    For the callers that have something to do with a failure. Everything
    else wants :func:`git`. ``cwd`` is the run's worktree for anything
    about its files or its HEAD, and the checkout for the repository's
    own things — the worktree list, the branches.
    """

    return await _run("git", *args, cwd=cwd)


async def git(*args: str, cwd: Path = CHECKOUT) -> str:
    """Same, but a non-zero exit ends the attempt (rule 3).

    A git command that fails here is not something a node body can route
    around: the tree is not in the state the next step assumes, so the
    exception is the honest answer.
    """

    code, out = await git_try(*args, cwd=cwd)
    if code:
        raise RuntimeError(f"git {' '.join(args)} failed ({code}):\n{out}")
    return out


async def gh_try(*args: str, cwd: Path = CHECKOUT) -> tuple[int, str]:
    """One `gh` command in ``cwd``, the same shape as :func:`git_try`.

    Run in a tree of the repository so `gh` resolves it from `origin`
    and never needs `--repo`; a worktree shares the checkout's remotes.
    """

    return await _run("gh", *args, cwd=cwd)


async def gh(*args: str, cwd: Path = CHECKOUT) -> str:
    """Same, failing the attempt on a non-zero exit, like :func:`git`."""

    code, out = await gh_try(*args, cwd=cwd)
    if code:
        raise RuntimeError(f"gh {' '.join(args)} failed ({code}):\n{out}")
    return out


def branch_name(title: str) -> str:
    """`feat/T003`, `feat/sse-replay-cap` — a git-safe slug of the title.

    Case is kept: a task id in the plan is `T003`, not `t003`.
    """

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.")
    return f"feat/{slug or 'feature'}"


async def branch_exists(name: str) -> bool:
    """Whether ``name`` is a local branch, a branch on `origin`, or a
    worktree directory — any of which a new run must not reuse."""

    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        code, _ = await git_try("rev-parse", "--verify", "--quiet", ref)
        if code == 0:
            return True
    return worktree_path(name).exists()


async def unique_branch(name: str) -> str:
    """`name`, or the next free `name-N`.

    A failed run leaves its branch and worktree behind to be read; a
    second run of the same feature takes the next number rather than
    clobbering the evidence. Checked against `origin` too, after the
    fetch `prepare` does, so a branch pushed by a run that died before
    its worktree was cleaned up is not pushed over.
    """

    if not await branch_exists(name):
        return name
    n = 2
    while await branch_exists(f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


def worktree_path(branch: str) -> Path:
    """`.worktrees/<branch>`, with the branch's slashes folded.

    `feat/T003` becomes `.worktrees/feat-T003`: git allows a slash in a
    branch and a worktree is a directory, and one level is easier to
    list, remove and reason about than a tree of them.
    """

    return WORKTREES / branch.replace("/", "-")


async def add_worktree(branch: str, start: str = "origin/main") -> Path:
    """Cut ``branch`` from ``start`` in a worktree of its own; return it.

    The checkout's own HEAD is not touched: the branch is created by
    `worktree add -b`, straight from the ref, so what the operator has
    checked out and whatever they have uncommitted is neither read nor
    disturbed. The tree starts empty of everything git ignores — no
    `.env`, no `web/node_modules` — and the wrappers in `scripts/` know
    to reach the main checkout's stack and to install what a gate needs
    (`scripts/_lib.sh`).
    """

    path = worktree_path(branch)
    WORKTREES.mkdir(exist_ok=True)
    await git("worktree", "add", "--quiet", str(path), "-b", branch, start)
    return path


async def remove_worktree(path: Path) -> None:
    """Drop the worktree at ``path``, whatever state it is in.

    `--force` because a merged run's tree may hold ignored files the
    gate produced (`web/dist`, `node_modules`) and git otherwise refuses
    to remove a tree with anything in it that is not in the index. The
    directory is gone afterwards; the branch is the caller's to delete.
    """

    await git("worktree", "remove", "--force", str(path))


def plan_docs(tree: Path, title: str) -> list[str]:
    """`docs/plans/<title>*.md` in ``tree``, tree-relative.

    Looked up when the node runs rather than when the run was submitted,
    which is what lets `planner` write the plan for this very run and
    `implement`, the node after it, find it.
    """

    plans = sorted((tree / "docs" / "plans").glob(f"{title}*.md"))
    return [str(p.relative_to(tree)) for p in plans]


async def run_gate(tree: Path) -> tuple[int, str]:
    """Run the gate on ``tree``. Returns its exit code and an output tail.

    The tree's own copy of the script, so the tree under test and the
    scripts testing it are the same commit; `scripts/_lib.sh` finds the
    checkout's stack from there. A timeout is a failure with a code of
    its own rather than an exception: a gate that hung is something the
    implementer can be told about and can act on, and the node routes on
    it like any other red.
    """

    proc = await asyncio.create_subprocess_exec(
        str(tree / "scripts" / "test.sh"),
        cwd=tree,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=GATE_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"`{GATE_COMMAND}` did not finish within {GATE_TIMEOUT:.0f}s."
    tail = out.decode(errors="replace").rstrip()[-GATE_TAIL:]
    return proc.returncode or 0, tail


async def watch_checks(branch: str, cwd: Path = CHECKOUT) -> tuple[int, str]:
    """Wait for the pull request's CI. Returns its exit code and a tail.

    `gh pr checks --watch` blocks until every check has finished and
    exits non-zero if any failed. On a failure the tail is the failed
    jobs' log rather than the check table, because the check table says
    only *which* job went red and the implementer needs to know *why* —
    the same thing :func:`run_gate` quotes back from a local run. A
    timeout is a code of its own, as it is for the gate.

    For a few seconds after a push GitHub has not registered the run's
    jobs yet, and `gh` reports "no checks" and exits 1 rather than
    waiting for them. That is not red; it is early, and is waited out
    inside the same timeout.
    """

    deadline = asyncio.get_running_loop().time() + CHECKS_TIMEOUT
    while True:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "pr",
            "checks",
            branch,
            "--watch",
            "--interval",
            str(CHECKS_INTERVAL),
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"},
        )
        left = deadline - asyncio.get_running_loop().time()
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=max(left, 0))
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, f"CI on `{branch}` did not finish within {CHECKS_TIMEOUT:.0f}s."
        code = proc.returncode or 0
        table = out.decode(errors="replace").rstrip()
        if code and "no checks reported" in table:
            if deadline - asyncio.get_running_loop().time() < CHECKS_INTERVAL:
                return 124, f"CI on `{branch}` never reported a check:\n{table}"
            await asyncio.sleep(CHECKS_INTERVAL)
            continue
        break
    if code == 0:
        return 0, table[-GATE_TAIL:]

    # The run's failed-step logs, when there is a run to read them from.
    # `gh run list` is the run for this branch's latest push; a check that
    # failed before a run existed (a cancelled workflow, say) has only the
    # table to show, which is still an answer.
    _, run_id = await gh_try(
        "run",
        "list",
        "--branch",
        branch,
        "--limit",
        "1",
        "--json",
        "databaseId",
        "--jq",
        ".[0].databaseId",
        cwd=cwd,
    )
    log = ""
    if run_id.strip().isdigit():
        _, log = await gh_try("run", "view", run_id.strip(), "--log-failed", cwd=cwd)
    tail = (f"{table}\n\n{log}" if log else table).rstrip()[-GATE_TAIL:]
    return code, tail
