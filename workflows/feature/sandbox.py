"""The gate, and the git this seat reads it beside.

Everything in `feature` that is not a model. The git primitives and the
checkout's paths are :mod:`workflows.checkout`, shared with `planner`
because they are facts about the working tree rather than about either
seat; what is left here is the one thing only this pipeline has — the
gate, and the exit code that is the whole of its verdict.

The names `feature` imports from here are unchanged: the module is still
the single place this seat looks for git and the gate, and re-exports the
shared half rather than making every caller know which of the two files
a function ended up in.
"""

from __future__ import annotations

import asyncio

from workflows.checkout import (
    AGENT_SH,
    CHECKOUT,
    branch_exists,
    branch_name,
    git,
    git_try,
    plan_docs,
    unique_branch,
)

__all__ = [
    "AGENT_SH",
    "CHECKOUT",
    "GATE_COMMAND",
    "GATE_TAIL",
    "branch_exists",
    "branch_name",
    "git",
    "git_try",
    "plan_docs",
    "run_gate",
    "unique_branch",
]

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
