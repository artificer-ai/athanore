"""The pi seat: what a workflow gets by subclassing it (T040a).

`docs/porting-ledger.md`: the vendor-shaped rest of the MVP's
``test_agents.py``. v0 asserted things about its own workflow's agent
classes — that every seat carried its prompt inline and ran on the local
model — and the v1 shape of that is this: the one example agent that
exists so far declares the three facts about pi that the package must not
hold, and each of them is checkable rather than assumed.

The class-attribute machinery itself is
``tests/agents/test_agent_classes.py``'s. What is here is pi: the pinned
adapter, the tier that cannot be negotiated, the provider that reads pi's
session files, and the sandbox line that installs the extension the tier
depends on.
"""

from __future__ import annotations

import re
from pathlib import Path

from athanore.agents.acp import ACPAgent
from pi import ATHANORE_EXTENSION, PI_ACP_VERSION, PiAgent, PiSessionStats

ROOT = Path(__file__).resolve().parents[2]


def test_the_seat_is_an_acp_agent_and_nothing_more() -> None:
    """A vendor adapter is configuration, not a second façade (05)."""

    assert issubclass(PiAgent, ACPAgent)
    declared = {name for name in vars(PiAgent) if not name.startswith("__")}
    assert declared == {"command", "tooling", "stats_provider"}


def test_the_adapter_is_pinned() -> None:
    """12 §Supply chain: an example pins, it does not float.

    ``npx -y pi-acp`` would run whatever was published this morning, in
    a process that has the task token in its environment.
    """

    assert PiAgent.command == ["npx", "-y", f"pi-acp@{PI_ACP_VERSION}"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", PI_ACP_VERSION), PI_ACP_VERSION


def test_the_pinned_adapter_is_the_sandboxs() -> None:
    """The dev stack and the example run the same pi-acp, or one is stale."""

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    found = re.search(r"PI_ACP_VERSION:\s*\$\{PI_ACP_VERSION:-([\d.]+)\}", compose)
    assert found is not None, "compose.yaml no longer pins PI_ACP_VERSION"
    assert found.group(1) == PI_ACP_VERSION


def test_the_tier_is_declared_because_it_cannot_be_detected() -> None:
    """05 §Tooling tiers: pi has no MCP client, so ``auto`` would pick http.

    Which would put the task token back in the prompt — the tier is the
    whole reason it is not there (12 §Task tokens).
    """

    assert PiAgent.tooling == "native"
    assert ACPAgent.tooling == "auto"


def test_the_seat_can_report_cost_and_truncation() -> None:
    """D27: the two fields no protocol carries arrive through a provider."""

    assert isinstance(PiAgent.stats_provider, PiSessionStats)
    assert ACPAgent.stats_provider is None


def test_the_extension_the_tier_needs_is_where_the_class_says() -> None:
    assert ATHANORE_EXTENSION.is_file()
    assert ATHANORE_EXTENSION.name == "athanore.ts"
    assert "registerTool" in ATHANORE_EXTENSION.read_text(encoding="utf-8")


def test_the_sandbox_installs_the_extension() -> None:
    """`native` is only true where pi can find the extension.

    pi auto-discovers ``~/.pi/agent/extensions/*.ts``, and `compose.yaml`
    puts this directory there for every service of the dev stack — which
    is what makes an agent dispatched by `./scripts/agent.sh pi` a
    ``native``-tier agent rather than one told about tools it has not got
    (D126).
    """

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    mount = "${WORKSPACE}/examples/pi/extensions:/home/agent/.pi/agent/extensions:ro"
    assert compose.count(mount) == 2, "the shared anchor and the dev service"
    assert ATHANORE_EXTENSION.parent == ROOT / "examples" / "pi" / "extensions"


def test_a_subclass_is_a_prompt_and_a_model() -> None:
    """What a workflow actually writes on top of the seat."""

    class Reviewer(PiAgent):
        system_prompt = "You review one branch."
        model = "openrouter/qwen/qwen3.8-max"

    assert Reviewer.tooling == "native"
    assert Reviewer.command == PiAgent.command
    assert Reviewer.stats_provider is PiAgent.stats_provider
    assert Reviewer.model == "openrouter/qwen/qwen3.8-max"
