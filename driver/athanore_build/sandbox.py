"""The sandbox: `scripts/agent.sh` and `scripts/test.sh`, and nothing else.

v0 does not know how to run a container. It runs the same two scripts a
human runs, which are the same two scripts a v1 workflow will run once
the port happens. One definition of "the sandbox" — `compose.yaml` — so
there is nothing to keep in step.

ACP is JSON-RPC over stdio and `docker compose run --rm -T` proxies
exactly that, so from v0's point of view `scripts/agent.sh` *is* the
agent. Nothing here is container-aware.
"""

import asyncio
import os

from athanore.agents import AthanoreACPAgent

# Host paths: the checkout is mounted at its own path everywhere, so this
# is true in v0, in the sandbox, and to the docker daemon alike.
WORKSPACE = os.environ["WORKSPACE"]
AGENT_SCRIPT = os.path.join(WORKSPACE, "scripts", "agent.sh")
GATE_SCRIPT = os.path.join(WORKSPACE, "scripts", "test.sh")

BUILDER_MODEL = os.environ.get("BUILDER_MODEL", "openrouter/qwen/qwen3.8-max")
BUILDER_MAX_LOOPS = int(os.environ.get("BUILDER_MAX_LOOPS", "3"))
BUILDER_ATTENDED = os.environ.get("BUILDER_ATTENDED", "") == "1"

GATE_TIMEOUT = 30 * 60
GATE_TAIL_LINES = 80


class SandboxAgent(AthanoreACPAgent):
    """An ACP agent in the dev container. The container is the guardrail,
    so permissions are auto-allowed and elicitations declined: an
    unattended build must never block on a dialog."""

    model = BUILDER_MODEL
    permission_policy = "auto_allow"
    elicitation_policy = "decline"

    def __init__(self, kind: str = "pi", **kwargs) -> None:
        kwargs.setdefault("timeout", 3600)
        super().__init__(command=[AGENT_SCRIPT, kind], cwd=WORKSPACE, **kwargs)


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
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"gate exceeded {GATE_TIMEOUT}s and was killed"
    text = out.decode(errors="replace").rstrip()
    tail = "\n".join(text.splitlines()[-GATE_TAIL_LINES:])
    return proc.returncode or 0, tail
