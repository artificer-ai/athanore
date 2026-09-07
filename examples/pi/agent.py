"""The pi seat: the adapter, the tier and the provider, in one class.

05 §User-land adapters: ``examples/`` keeps pi's default command and its
stats provider, and the package keeps neither (D14). A workflow that
wants pi subclasses :class:`PiAgent` and writes its prompt::

    class Reviewer(PiAgent):
        system_prompt = "You review one branch."
        output_model = Review
        model = "openrouter/qwen/qwen3.8-max"

**The tier is a declaration.** ``tooling = "native"`` because it cannot
be negotiated: pi-acp 0.0.33 advertises ``mcpCapabilities: {http: false,
sse: false}`` and pi 0.84 has no MCP client (05 §Tooling tiers, verified
2026-09-05), so ``auto`` would fall back to the ``http`` tier and put the
task token in the prompt. What makes ``native`` true is
``extensions/athanore.ts``: pi discovers it in
``~/.pi/agent/extensions``, and it reads ``ATHANORE_TASK_URL`` /
``ATHANORE_TASK_TOKEN`` out of the environment the façade exports rather
than out of anything the model can see.

**An agent without the extension installed would be told about tools it
does not have**, which is why the tier is on this class rather than on
every subclass: one place says "pi, with the extension", and
:data:`ATHANORE_EXTENSION` is where the file is, for a sandbox that has
to install it.
"""

from __future__ import annotations

from pathlib import Path

from athanore.agents.acp import ACPAgent
from pi.stats import PiSessionStats

__all__ = ["ATHANORE_EXTENSION", "PI_ACP_VERSION", "PiAgent"]

#: The ACP adapter this seat spawns, pinned rather than floating: an
#: example that runs `npx -y pi-acp` picks up whatever was published this
#: morning (12 §Supply chain). It matches ``PI_ACP_VERSION`` in
#: `compose.yaml`, which is the same adapter inside the dev sandbox.
PI_ACP_VERSION = "0.0.33"

#: The extension that makes the ``native`` tier real. A sandbox puts this
#: file in ``~/.pi/agent/extensions/`` — `compose.yaml` mounts the
#: directory it is in.
ATHANORE_EXTENSION = Path(__file__).parent / "extensions" / "athanore.ts"


class PiAgent(ACPAgent):
    """pi over ACP, in the ``native`` tooling tier, with its own stats.

    The three lines below are the whole of what "this seat is pi" means,
    and each is a fact about pi that the package must not hold: what to
    spawn, how it reaches its task, and where its cost and its truncation
    can be read from (D14, D27, D63).

    ``settings.agent_command`` still overrides the command on every
    subclass, which is how the example suite runs on ``FakeACPAgent`` in
    CI with no model in the loop (05, 13 §Running examples on the fake).
    """

    command = ["npx", "-y", f"pi-acp@{PI_ACP_VERSION}"]
    tooling = "native"
    stats_provider = PiSessionStats()
