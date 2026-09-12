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
    "branch_name",
    "gh",
    "gh_try",
    "git",
    "git_try",
    "plan_docs",
    "run_gate",
    "unique_branch",
    "watch_checks",
]

#: The checkout this workflow maintains: the repository root, three
#: parents up from this file. Derived rather than read from `WORKSPACE`
#: so it is correct when athanore is run from anywhere in the tree — the
#: workflow is on the host, and a host has a shell that may be anywhere.
CHECKOUT = Path(__file__).resolve().parents[2]

#: The one way into the sandbox, absolute. `command` is spawned in the
#: agent's `cwd`, and it works from either side of the container boundary
#: (AGENTS.md §Dispatching agents into the container).
AGENT_SH = CHECKOUT / "scripts" / "agent.sh"

#: The gate, which is the definition of green (D74). Not `pytest`: the
#: gate is ruff, pyright, import-linter, both test suites, the SPA build,
#: Playwright and the packaging check, and a workflow that ran less than
#: a human runs would be merging on a weaker promise.
GATE_SCRIPT = CHECKOUT / "scripts" / "test.sh"
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


async def _run(program: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=CHECKOUT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"},
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def git_try(*args: str) -> tuple[int, str]:
    """One git command in the checkout: its exit code and its output.

    For the callers that have something to do with a failure. Everything
    else wants :func:`git`.
    """

    return await _run("git", *args)


async def git(*args: str) -> str:
    """Same, but a non-zero exit ends the attempt (rule 3).

    A git command that fails here is not something a node body can route
    around: the checkout is not in the state the next step assumes, so
    the exception is the honest answer.
    """

    code, out = await git_try(*args)
    if code:
        raise RuntimeError(f"git {' '.join(args)} failed ({code}):\n{out}")
    return out


async def gh_try(*args: str) -> tuple[int, str]:
    """One `gh` command in the checkout, the same shape as :func:`git_try`.

    Run in the checkout so `gh` resolves the repository from `origin`
    and never needs `--repo`.
    """

    return await _run("gh", *args)


async def gh(*args: str) -> str:
    """Same, failing the attempt on a non-zero exit, like :func:`git`."""

    code, out = await gh_try(*args)
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
    code, _ = await git_try("rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    return code == 0


async def unique_branch(name: str) -> str:
    """`name`, or the next free `name-N`.

    A failed run leaves its branch behind to be read; a second run of the
    same feature takes the next number rather than clobbering the
    evidence.
    """

    if not await branch_exists(name):
        return name
    n = 2
    while await branch_exists(f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


def plan_docs(title: str) -> list[str]:
    """`docs/plans/<title>*.md`, checkout-relative.

    Looked up when the node runs rather than when the run was submitted,
    which is what lets `planner` write the plan for this very run and
    `implement`, the node after it, find it.
    """

    plans = sorted((CHECKOUT / "docs" / "plans").glob(f"{title}*.md"))
    return [str(p.relative_to(CHECKOUT)) for p in plans]


async def run_gate() -> tuple[int, str]:
    """Run the gate. Returns its exit code and the tail of its output.

    A timeout is a failure with a code of its own rather than an
    exception: a gate that hung is something the implementer can be told
    about and can act on, and the node routes on it like any other red.
    """

    proc = await asyncio.create_subprocess_exec(
        str(GATE_SCRIPT),
        cwd=CHECKOUT,
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


async def watch_checks(branch: str) -> tuple[int, str]:
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
            cwd=CHECKOUT,
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
    )
    log = ""
    if run_id.strip().isdigit():
        _, log = await gh_try("run", "view", run_id.strip(), "--log-failed")
    tail = (f"{table}\n\n{log}" if log else table).rstrip()[-GATE_TAIL:]
    return code, tail
