"""The sandbox: `scripts/agent.sh`, `scripts/test.sh`, and git.

v0 does not know how to run a container. It runs the same two scripts a
human runs, which are the same two scripts a v1 workflow will run once
the port happens. One definition of "the sandbox" — `compose.yaml` — so
there is nothing to keep in step.

ACP is JSON-RPC over stdio and `docker compose run --rm -T` proxies
exactly that, so from v0's point of view `scripts/agent.sh` *is* the
agent. Nothing here is container-aware.

Git runs here, in the orchestrator, never in an agent: branching,
merging and the checks around a commit are deterministic and must not be
something an agent can talk its way through.
"""

import asyncio
import glob
import os
import re

from athanore.agents import AthanoreACPAgent

# Host paths: the checkout is mounted at its own path everywhere, so this
# is true in v0, in the sandbox, and to the docker daemon alike.
WORKSPACE = os.environ["WORKSPACE"]
AGENT_SCRIPT = os.path.join(WORKSPACE, "scripts", "agent.sh")
GATE_SCRIPT = os.path.join(WORKSPACE, "scripts", "test.sh")

# One model writes, a different model reviews and QAs it: a blind spot
# shared with the implementer cannot wave its own work through.
#
# A role names an adapter (`kind`) and a model id valid *for that
# adapter*. pi takes `<provider>/<model id>` from
# docker/dev/pi/models.json; the Claude adapter takes the values it
# advertises (`opus[1m]`, `sonnet`, `haiku`, `default`) plus whatever
# ANTHROPIC_MODEL names in its container — which is why Fable is its own
# kind (D75). Both adapters log and silently fall back to their own
# default for an unknown id, so `_role` refuses an obvious mismatch at
# import rather than letting a whole build run on the wrong model.


def _role(
    name: str, kind: str, model: str, effort: str = ""
) -> tuple[str, str, str | None]:
    prefix = f"BUILDER_{name}_"
    kind = os.environ.get(prefix + "KIND", kind)
    model = os.environ.get(prefix + "MODEL", model)
    effort = os.environ.get(prefix + "EFFORT", effort)
    pi_shaped = "/" in model
    if pi_shaped != (kind == "pi"):
        raise ValueError(
            f"{prefix}KIND={kind!r} does not match {prefix}MODEL={model!r}: "
            "pi ids are `<provider>/<model>`, the Claude adapter's are not"
        )
    return kind, model, effort or None


IMPLEMENT_KIND, IMPLEMENT_MODEL, IMPLEMENT_EFFORT = _role(
    "IMPLEMENT", "claude", "opus[1m]"
)
REVIEW_KIND, REVIEW_MODEL, REVIEW_EFFORT = _role(
    "REVIEW", "claude-fable", "claude-fable-5", "high"
)
QA_KIND, QA_MODEL, QA_EFFORT = _role("QA", "claude", "opus[1m]")

# Rounds back to `implement` allowed per lane (gate, review, QA), and
# across all of them, before the run fails.
BUILDER_MAX_LOOPS = int(os.environ.get("BUILDER_MAX_LOOPS", "3"))
BUILDER_MAX_ATTEMPTS = int(os.environ.get("BUILDER_MAX_ATTEMPTS", "6"))
BUILDER_ATTENDED = os.environ.get("BUILDER_ATTENDED", "") == "1"

AGENT_TIMEOUT = float(os.environ.get("BUILDER_AGENT_TIMEOUT", 3 * 3600))
GATE_TIMEOUT = 30 * 60
GATE_TAIL_LINES = 80

# The build's own identity, on the merge commits this module makes. The
# agents carry the same one (compose.yaml x-agent-environment), so every
# commit of a build is attributable to the build.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "athanore-builder",
    "GIT_AUTHOR_EMAIL": "builder@athanore.local",
    "GIT_COMMITTER_NAME": "athanore-builder",
    "GIT_COMMITTER_EMAIL": "builder@athanore.local",
}


class SandboxAgent(AthanoreACPAgent):
    """An ACP agent in the dev container. The container is the guardrail,
    so permissions are auto-allowed and elicitations declined: an
    unattended build must never block on a dialog. Claude agents also run
    with `permissions.defaultMode = bypassPermissions` in the settings on
    the `athanore-claude` volume, so they do not round-trip a permission
    request per tool call (D75)."""

    kind = "pi"
    permission_policy = "auto_allow"
    elicitation_policy = "decline"

    def __init__(self, kind: str | None = None, **kwargs) -> None:
        kwargs.setdefault("timeout", AGENT_TIMEOUT)
        super().__init__(
            command=[AGENT_SCRIPT, kind or type(self).kind],
            cwd=WORKSPACE,
            **kwargs,
        )


# -- git ---------------------------------------------------------------------


async def git_try(*args: str) -> tuple[int, str]:
    """Run one git command in the checkout. Returns exit code and output."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=WORKSPACE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **GIT_ENV},
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def git(*args: str) -> str:
    """Same, but a non-zero exit is a failed node (rule 3)."""
    code, out = await git_try(*args)
    if code:
        raise RuntimeError(f"git {' '.join(args)} failed ({code}):\n{out}")
    return out


def branch_name(task_id: str) -> str:
    """`feat/T003`, `feat/sse-replay-cap` — a git-safe slug of the title.
    Case is kept: the task ids in the plan are `T003`, not `t003`."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-.")
    return f"feat/{slug or 'task'}"


def plan_docs(task_id: str) -> list[str]:
    """`docs/plans/<task-id>*.md`, checkout-relative. Looked up when the
    node runs, not when the run was submitted: a plan written after a
    batch was queued still reaches the agent that builds the task."""
    pattern = os.path.join(WORKSPACE, "docs", "plans", f"{task_id}*.md")
    return sorted(os.path.relpath(p, WORKSPACE) for p in glob.glob(pattern))


async def branch_exists(name: str) -> bool:
    code, _ = await git_try("rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    return code == 0


async def unique_branch(name: str) -> str:
    """A failed run leaves its branch behind for inspection; the retry
    gets the next number rather than clobbering the evidence."""
    if not await branch_exists(name):
        return name
    n = 2
    while await branch_exists(f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


# -- the gate ----------------------------------------------------------------


async def run_gate() -> tuple[int, str]:
    """Run the gate in the dev container. Returns the exit code and the
    tail of the output — deterministic, no agent involved."""
    proc = await asyncio.create_subprocess_exec(
        GATE_SCRIPT,
        cwd=WORKSPACE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=GATE_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"gate exceeded {GATE_TIMEOUT}s and was killed"
    text = out.decode(errors="replace").rstrip()
    tail = "\n".join(text.splitlines()[-GATE_TAIL_LINES:])
    return proc.returncode or 0, tail
