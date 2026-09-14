"""The base class of every seat that runs in the dev container.

How an agent is reached, what it runs as and how long it may take are
facts about the sandbox rather than about any one stage (05 §Agent
classes), so they are set once here and every seat of every build
workflow extends this. A seat adds its prompt, its model and, where the
node routes on a verdict, the model that verdict must fit; those are the
workflow's own and live beside it.

**Why the container, when athanore is not in one.** The workflow runs on
the host in this checkout's own environment, which is the simple thing
now that it is athanore v1 maintaining athanore v1 — there is no second
distribution to keep out of this venv. The *agents* still go into the
dev stack, because that is what the container was ever for: it is the
guardrail around a model with a shell, not a packaging device. So these
run `permission_policy="auto_allow"` — an agent already confined to a
container that is asked to approve each tool call is a build that stops
on a dialog at 3am (05 §User-land adapters, D75).
"""

from __future__ import annotations

import os

from athanore import ACPAgent

from .sandbox import AGENT_SH, CHECKOUT

__all__ = ["AGENT_TIMEOUT", "SandboxAgent"]

#: How long one agent turn may take. Three hours: an implement turn on a
#: real feature routinely runs to the far side of an hour, and a cap that
#: fires on a healthy turn is worse than no cap. The variable keeps its
#: `FEATURE_` name from when only `feature` read it.
AGENT_TIMEOUT = float(os.environ.get("FEATURE_AGENT_TIMEOUT", 3 * 3600))


class SandboxAgent(ACPAgent):
    """Claude Code over ACP, in the dev container, on this checkout.

    ``command`` is `./scripts/agent.sh claude` as an absolute path: the
    script is the one way into the sandbox and works from either side of
    the boundary, but ``command`` is spawned in the agent's ``cwd``, so
    it is anchored rather than relative.

    ``cwd`` is the checkout at its own host path. That is the whole
    reason `compose.yaml` mounts it there: the agent edits the same files
    :mod:`workflows.shared.sandbox` then reads with git, and neither
    side has to translate a path.
    """

    command = [str(AGENT_SH), "claude"]
    cwd = str(CHECKOUT)
    permission_policy = "auto_allow"
    #: An unattended build must never block on a dialog it cannot answer.
    elicitation_policy = "decline"
    timeout = AGENT_TIMEOUT
