"""git and the gate: everything in this pipeline that is not a model.

The division this module exists to keep is the one the whole workflow is
built on — **an agent never decides whether its own work passed**. Where
the branch went, whether anything was committed, whether the suite is
green and what lands on `main` are all answered here, by git and by an
exit code, and the nodes that call these functions have no agent in them.

Two facts about where this runs shape the rest:

- **Athanore is on the host, in this checkout's own environment.** There
  is no container around the workflow, so `git` and `./scripts/test.sh`
  are ordinary subprocesses in :data:`CHECKOUT`.
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
    "GATE_COMMAND",
    "GATE_TAIL",
    "branch_name",
    "git",
    "git_try",
    "plan_docs",
    "run_gate",
    "unique_branch",
]

#: The checkout these workflows maintain: the repository root, three
#: parents up from this file. Derived rather than read from `WORKSPACE`
#: so it is correct when athanore is run from anywhere in the tree — the
#: workflow is on the host now, and a host has a shell that may be
#: anywhere.
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
    so a plan written after a batch was queued still reaches the agent
    that builds it.
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
