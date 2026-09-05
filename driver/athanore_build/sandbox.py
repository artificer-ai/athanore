"""The sandbox: the dev image, run as an ACP agent and as a gate runner.

ACP is JSON-RPC over stdin/stdout and `docker run -i` proxies exactly
that, so from v0's point of view the docker CLI *is* the agent. Nothing
in v0 is container-aware.

The image is `athanore/dev` — the same one `./scripts/dev.sh` uses. That
is the point: the gate the agent runs is the gate a human runs.
"""

import asyncio
import os

from athanore.agents import AthanoreACPAgent

IMAGE = os.environ.get("SANDBOX_IMAGE", "athanore/dev:latest")

# Host paths. Every mount is at its own host path so a `cwd` means the
# same thing in v0, in the sandbox, and to the docker daemon.
WORKSPACE = os.environ["WORKSPACE"]
MAIN_CHECKOUT = os.environ.get("MAIN_CHECKOUT", "")
HOST_HOME = os.environ.get("HOST_HOME", os.path.expanduser("~"))

BUILDER_MODEL = os.environ.get("BUILDER_MODEL", "openrouter/qwen/qwen3.8-max")
BUILDER_MAX_LOOPS = int(os.environ.get("BUILDER_MAX_LOOPS", "3"))
BUILDER_ATTENDED = os.environ.get("BUILDER_ATTENDED", "") == "1"

GATE_TIMEOUT = 30 * 60
GATE_TAIL_LINES = 80

# Shared with compose.yaml by name, so the sandbox and `./scripts/dev.sh`
# hit one warm venv, one uv cache, one pnpm store.
_VOLUMES = [
    ("athanore-venv", "/home/agent/venv"),
    ("athanore-uv-cache", "/home/agent/.cache/uv"),
    ("athanore-pnpm-store", "/home/agent/.local/share/pnpm/store"),
    ("athanore-ms-playwright", "/home/agent/ms-playwright"),
    ("athanore-claude", "/home/agent/.claude"),
]


def docker_command(
    *, entrypoint: str | None = None, args: tuple[str, ...] = ()
) -> list[str]:
    """`docker run` for the dev image. With no `entrypoint` the container
    speaks ACP on stdio (`pi-acp`); with one, it runs that instead — same
    mounts, same volumes, same warm environment."""
    cmd = [
        "docker", "run",
        "-i",              # the ACP wire; never -t, a TTY corrupts the JSON
        "--rm",
        "--init",          # so terminate/kill actually reaches the agent
        "--network", "host",
        "-w", WORKSPACE,
        "-v", f"{WORKSPACE}:{WORKSPACE}",
    ]
    if MAIN_CHECKOUT:
        # The MVP checkout: the reference the plan calls "the MVP", and
        # where the porting ledger's source files live.
        cmd += ["-v", f"{MAIN_CHECKOUT}:{MAIN_CHECKOUT}", "-e", f"MVP_CHECKOUT={MAIN_CHECKOUT}"]
    for name, path in _VOLUMES:
        cmd += ["-v", f"{name}:{path}"]
    # pi's session JSONL, so `[stats]` lines carry real token counts.
    cmd += ["-v", f"{HOST_HOME}/.pi/agent/sessions:/home/agent/.pi/agent/sessions"]
    # Pass-through (no value = take it from this process's environment).
    for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        cmd += ["-e", var]
    # A fixed identity, so a commit an agent makes is recognisable as one.
    for var, value in (
        ("GIT_AUTHOR_NAME", "athanore-builder"),
        ("GIT_AUTHOR_EMAIL", "builder@athanore.local"),
        ("GIT_COMMITTER_NAME", "athanore-builder"),
        ("GIT_COMMITTER_EMAIL", "builder@athanore.local"),
    ):
        cmd += ["-e", f"{var}={value}"]
    if entrypoint is not None:
        cmd += ["--entrypoint", entrypoint]
    cmd.append(IMAGE)
    cmd += list(args)
    return cmd


class SandboxAgent(AthanoreACPAgent):
    """pi-acp inside the dev image. The container is the guardrail, so
    permissions are auto-allowed and elicitations declined: an unattended
    build must never block on a dialog."""

    model = BUILDER_MODEL
    permission_policy = "auto_allow"
    elicitation_policy = "decline"

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("timeout", 3600)
        super().__init__(
            command=docker_command(args=("pi-acp",)), cwd=WORKSPACE, **kwargs
        )


async def run_gate(command: str = "./scripts/test.sh") -> tuple[int, str]:
    """Run the gate in the sandbox. Returns the exit code and the tail of
    the output — deterministic, no agent involved."""
    proc = await asyncio.create_subprocess_exec(
        *docker_command(entrypoint="bash", args=("-lc", command)),
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
