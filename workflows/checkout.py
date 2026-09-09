"""git and the paths of *this* checkout: what both seats share.

`feature` and `planner` are two workflows over one working tree, and the
half of each that is not a model is the same half: where the repository
is, how the sandbox is reached, and what git says. That is here so there
is one answer rather than two that drift.

The division this module exists to keep is the one both pipelines are
built on — **an agent never decides whether its own work passed**. Where
a branch went, whether anything was committed, what a commit touched and
what lands on `main` are answered here, by git, and the nodes that call
these functions have no agent in them.

Two facts about where this runs shape the rest:

- **Athanore is on the host, in this checkout's own environment.** There
  is no container around the workflows, so `git` is an ordinary
  subprocess in :data:`CHECKOUT`.
- **The agents are not.** They are dispatched into the dev stack through
  `scripts/agent.sh`, which is the one definition of that sandbox
  (`compose.yaml`, D64). The checkout is mounted at its own host path, so
  a `cwd` means the same thing on both sides of the boundary and an agent
  edits the same files this module then reads with git.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

__all__ = [
    "AGENT_SH",
    "CHECKOUT",
    "branch_exists",
    "branch_name",
    "changed_paths",
    "git",
    "git_try",
    "plan_docs",
    "unique_branch",
]

#: The checkout these workflows maintain: the repository root, two
#: parents up from this file. Derived rather than read from `WORKSPACE`
#: so it is correct when athanore is run from anywhere in the tree — the
#: workflows are on the host, and a host has a shell that may be
#: anywhere.
CHECKOUT = Path(__file__).resolve().parents[1]

#: The one way into the sandbox, absolute. `command` is spawned in the
#: agent's `cwd`, and it works from either side of the container boundary
#: (AGENTS.md §Dispatching agents into the container).
AGENT_SH = CHECKOUT / "scripts" / "agent.sh"

#: Commits these workflows make are recognisable as theirs. The same
#: identity the agent services carry in `compose.yaml`, so a merge commit
#: made here and a commit made in the sandbox agree about who did it.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "athanore-builder",
    "GIT_AUTHOR_EMAIL": "builder@athanore.local",
    "GIT_COMMITTER_NAME": "athanore-builder",
    "GIT_COMMITTER_EMAIL": "builder@athanore.local",
}


async def git_try(*args: str) -> tuple[int, str]:
    """One git command in the checkout: its exit code and its output.

    For the callers that have something to do with a failure. Everything
    else wants :func:`git`.
    """

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=CHECKOUT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **GIT_ENV},
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


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


def branch_name(title: str, prefix: str = "feat") -> str:
    """`feat/T003`, `plan/sse-replay-cap` — a git-safe slug of the title.

    Case is kept: a task id in the plan is `T003`, not `t003`. The prefix
    is the seat: `feat/` is one task being built, `plan/` is the design
    that will produce several of them.
    """

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.")
    return f"{prefix}/{slug or 'feature'}"


async def branch_exists(name: str) -> bool:
    """Whether `refs/heads/<name>` resolves."""

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


async def changed_paths(base: str, *, added_only: bool = False) -> list[str]:
    """Checkout-relative paths `base..HEAD` touched, sorted.

    ``added_only`` narrows it to the files the range *created*, which is
    what distinguishes a document this branch wrote from one it edited a
    line of. `--diff-filter=A` is git's own answer to that question, so
    nothing here has to reconstruct it from a status letter.
    """

    args = ["diff", "--name-only", f"{base}..HEAD"]
    if added_only:
        args.insert(1, "--diff-filter=A")
    out = await git(*args)
    return sorted(line for line in out.splitlines() if line.strip())


def plan_docs(task_id: str) -> list[str]:
    """`docs/plans/<task_id>*.md`, checkout-relative.

    Looked up when the node runs rather than when the run was submitted,
    so a plan written after a batch was queued still reaches the agent
    that builds it — which is exactly what `planner` relies on: it writes
    these files and then queues the `feature` runs that read them.
    """

    plans = sorted((CHECKOUT / "docs" / "plans").glob(f"{task_id}*.md"))
    return [str(p.relative_to(CHECKOUT)) for p in plans]
