"""docker_acp — a pi agent doing the work inside the dev stack's container.

Same façade as every other example; the only difference is ``command``.
Instead of spawning ``npx pi-acp`` on the host, this seat spawns
``./scripts/agent.sh pi``, which is the dev stack's one way in: on the
host it is ``docker compose run --rm -T agent-pi``, and inside the
container it is ``exec pi-acp``. ACP is JSON-RPC over stdin/stdout and
both of those proxy exactly that, so the script *is* the agent as far as
athanore is concerned — there is no container-aware code here, and none
in the package (02 §Small core, D64, D67).

    implement          (one node: the agent does the task, its files stay
                        in the sandbox, the run's output is its work log)

**There is no image of its own.** 17 §T076 lists an ``examples/docker/``;
``docker/dev`` already is that image and `compose.yaml` already is that
definition of the sandbox, so a second one would be a second thing to
keep in step (D64). This module builds nothing, and `scripts/agent.sh` is
the only door.

What crosses the container boundary, and how:

- **ACP itself**: stdio, through the script. Never a TTY — a TTY would
  corrupt the line-delimited JSON — which is what ``-T`` is for.
- **The workspace**: `compose.yaml` mounts the checkout at *its own host
  path*, so :func:`sandbox` is a directory inside the checkout and
  ``cwd`` means the same thing on both sides. ``cwd`` does double duty —
  the subprocess's working directory on the host and the session
  directory sent to the agent — so a scratch directory anywhere else
  would exist for only one of them.
- **The task API**: the container is on the host network, so the
  ``public_url`` the façade hands the agent (12 §S6) resolves from
  inside as it does outside. That is a property of the deployment rather
  than of this file, and it is the one this workflow cannot do without:
  :func:`reachable` refuses a wildcard bind before an agent is spawned
  rather than after it has failed to reach anything, and names
  ``ATHANORE_PUBLIC_URL`` as the fix.
- **The model**: `docker/dev/pi/` bakes the pi configuration into the
  image — OpenRouter by default, with the key forwarded from the shell
  that started compose, and a LAN llama-server as the alternative.
- **The session file**: `compose.yaml` mounts the host's
  ``~/.pi/agent/sessions`` into the container, so :class:`pi.PiAgent`'s
  stats provider reads what this agent wrote and a run reports what it
  cost (05 §Stats, D27).

**The tier is ``http``, and it is a declaration.** :class:`pi.PiAgent`
sets ``native`` because pi has no MCP client and the extension in
``~/.pi/agent/extensions`` gives it athanore's tools instead. That
extension reads ``ATHANORE_TASK_URL`` and ``ATHANORE_TASK_TOKEN`` out of
its environment (D63), and those are exported to the *script*, not into
the container: ``docker compose run`` forwards only the names a service's
``environment:`` lists, and `compose.yaml` lists neither. So the seat
that dispatches into a sibling container is the one seat where ``native``
would be an agent told about tools that cannot answer, and the ``http``
tier — curl lines with the task token, which the image has curl for — is
what works on both sides of the boundary.

**The container is the guardrail**, which is why
``permission_policy="auto_allow"``: an agent already confined to a
sandbox that gains nothing from a round trip per tool call (05 §User-land
adapters, D75).

Run it with ``athanore serve`` (it is an entry point of the
``athanore-examples`` distribution) or with ``python -m examples``::

    athanore submit docker_acp "ga" "write a genetic algorithm script"

The task is the operator's: whatever is submitted is what the agent
reads out of its own work log and does, in the sandbox.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from athanore import NonRetryable, Workflow, current_task
from athanore.engine.context import TaskContext
from athanore.settings import AthanoreSettings
from pi import PiAgent

__all__ = [
    "AGENT_KIND",
    "AGENT_SH",
    "CHECKOUT",
    "MODEL",
    "SANDBOX_FILES",
    "SUMMARY_TAIL",
    "WILDCARD_HOSTS",
    "DockerAgent",
    "dispatchable",
    "prepare",
    "reachable",
    "sandbox",
    "wf",
]

#: The checkout this example lives in — the directory `compose.yaml`
#: mounts into every service at this same absolute path. Everything below
#: is anchored here rather than on ``settings.root_path``, because a
#: sandbox the container cannot see is a ``cwd`` that only exists on one
#: side of the wire.
CHECKOUT = Path(__file__).resolve().parents[2]

#: The dev stack's way in, absolute. `AGENTS.md` writes the same line
#: relative — ``command = ["./scripts/agent.sh", "pi"]`` — for a workflow
#: whose agents run in the checkout; ``command`` is spawned in the
#: agent's ``cwd``, and this agent's cwd is its sandbox, so the script is
#: named by its path rather than found by one.
AGENT_SH = CHECKOUT / "scripts" / "agent.sh"

#: Which agent the script starts. ``claude`` and ``claude-fable`` are the
#: others; this example is pi, because pi is what the image's baked
#: configuration gives a model with no credentials of its own.
AGENT_KIND = "pi"

#: The model, as ``<provider>/<model>`` — the id form pi resolves against
#: `docker/dev/pi/models.json`, whose default provider is OpenRouter. The
#: same model `feature_build` runs on, which is why
#: `examples/__main__.py` puts this workflow on the same capacity-1 pool.
MODEL = "openrouter/qwen/qwen3.8-27b"

#: An empty uv project, so the agent can ``uv run`` whatever it writes:
#: the image carries uv and a managed Python, with the environment and
#: the cache on named volumes outside the workspace. Written only when
#: missing — nothing the agent leaves behind is ever removed, so the
#: sandbox accumulates across runs and a run can be read afterwards.
SANDBOX_FILES = {
    "pyproject.toml": (
        "[project]\n"
        'name = "docker-acp-sandbox"\n'
        'version = "0"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n\n"
        "[dependency-groups]\n"
        'dev = ["pytest>=8"]\n'
    ),
}

#: How much of the agent's own text the run's output carries. The work
#: log is the record; this is the tail somebody reads in a list.
SUMMARY_TAIL = 2000

#: Bind addresses that mean "every interface" and therefore address
#: nothing from another network namespace (12 §S6).
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})


def sandbox() -> Path:
    """Where the agent works.

    Inside the checkout, for the reason :data:`CHECKOUT` gives, and under
    ``output/`` — git-ignored, and where the examples already put what
    they make.
    """

    return CHECKOUT / "output" / "docker-acp-sandbox"


def prepare() -> Path:
    """Make the scratch project if it is not there, and say where it is.

    Each file is written only when missing: nothing the agent leaves
    behind is ever removed, so the sandbox accumulates across runs and a
    run can be read afterwards.
    """

    where = sandbox()
    where.mkdir(parents=True, exist_ok=True)
    for name, body in SANDBOX_FILES.items():
        path = where / name
        if not path.exists():
            path.write_text(body, encoding="utf-8")
    return where


def dispatchable(settings: AthanoreSettings) -> None:
    """Refuse before spawning when the dev stack is not there to spawn into.

    ``settings.agent_command`` replaces the command on every ``ACPAgent``
    — it is how the examples run on ``FakeACPAgent`` with no model in the
    loop (13 §Running examples on the fake) — so when one is configured
    the script is not what runs and its absence means nothing. Otherwise
    a missing or unexecutable `scripts/agent.sh` is a ``FileNotFoundError``
    from a subprocess spawn, reported as a transport failure; this says
    what is actually wrong instead.
    """

    if settings.agent_command:
        return
    if not os.access(AGENT_SH, os.X_OK):
        raise NonRetryable(
            f"{AGENT_SH} is not there or is not executable, so there is no "
            "container to dispatch into; run this example from a checkout of "
            "athanore with the dev stack in it (AGENTS.md §Commands)"
        )


def reachable(ctx: TaskContext) -> str:
    """The task API URL, checked against the one bind an agent cannot use.

    ``settings.public_url`` is what every agent is told to call (12 §S6),
    and the dev stack's services are on the host network so its loopback
    default resolves from inside a container exactly as it does outside.
    A *wildcard* bind does not: ``http://0.0.0.0:4002`` is an instruction
    to listen on every interface, not an address to call one on, and an
    agent handed it would spend its whole turn failing to read its task.
    """

    host = urlsplit(ctx.api_base).hostname or ""
    if host in WILDCARD_HOSTS:
        raise NonRetryable(
            f"the agents of this run would be told to call {ctx.api_base}, "
            "which addresses no host from inside a container; set "
            "ATHANORE_PUBLIC_URL to a URL that resolves there (12 §S6)"
        )
    return ctx.api_base


class DockerAgent(PiAgent):
    """pi, in the dev stack's container, on the ``http`` tier.

    Everything else is :class:`pi.PiAgent`'s — including
    :class:`pi.PiSessionStats`, which reads the session file the mount
    puts back on the host. Three lines change, and the module docstring
    is why each one does.
    """

    command = [str(AGENT_SH), AGENT_KIND]
    model = MODEL
    tooling = "http"
    permission_policy = "auto_allow"


wf = Workflow("docker_acp")


@wf.node(start=True, retries=1, timeout=3600)
async def implement():
    """The whole workflow: pi does the submitted task inside the container.

    Terminal — no edges — so what this returns is the run's output (04
    §Routing interpretation). Whatever the agent wrote stays in the
    sandbox; its deliverable is in the work log, where it put it.
    """

    ctx = current_task()
    dispatchable(AthanoreSettings())
    reachable(ctx)

    where = prepare()
    result = await DockerAgent(cwd=str(where)).run()
    if not result.ok:
        raise NonRetryable(
            result.error
            or f"the agent stopped: {result.stop_reason or 'no reason given'}"
        )
    summary = result.text.strip()[-SUMMARY_TAIL:]
    await ctx.services.log.append(
        f"docker_acp: the agent worked in {where} and said:\n{summary}"
        if summary
        else f"docker_acp: the agent worked in {where} and said nothing",
        author="engine",
        kind="note",
    )
    return {"sandbox": str(where), "summary": summary}
