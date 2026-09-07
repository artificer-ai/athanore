"""An agent class is configuration, and only configuration (T040).

`docs/porting-ledger.md`: the remainder of the MVP's ``test_agents.py``.
Its prompt-rendering half is ``test_prompt.py``'s and its session half is
``test_acp_lifecycle.py``'s; what is left is the shape of the class
itself, which is what a workflow author actually writes:

.. code-block:: python

    class Reviewer(ACPAgent):
        command = ["npx", "-y", "pi-acp@0.0.33"]
        system_prompt = "You review one branch."
        model = "anthropic/claude-sonnet-4"

Two of the MVP's assertions carry over unchanged — ``model`` is a class
attribute, and a subclass that does not set one has ``None`` rather than
a default someone guessed — and one is inverted. v0 rendered its prompts
from a ``template=`` file and tested that an inline ``system_prompt`` beat
one; v1 has no templates at all (`AGENTS.md`: "agent prompts are inlined
text on agent classes"), so what is pinned here is the *absence*: no
façade carries a ``template``.

The MVP's remaining three tests were assertions over its own workflow's
agent classes — every seat carries its prompt inline, every seat runs on
the local model, the gamedev seats run with thinking off. Those belong to
the example that declares the seats, and the first of them lands with the
first example agent in ``examples/tests/test_pi_agent.py`` (T040a); the
rest arrive with their workflows in T074-T076.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import BaseModel

from athanore.agents.acp import ACPAgent
from athanore.agents.base import Agent, AgentError
from athanore.agents.stats import SessionStats
from athanore.testing import FakeStatsProvider


class Verdict(BaseModel):
    ok: bool


class Configured(ACPAgent):
    """One seat, written the way a workflow writes one."""

    command = ["npx", "-y", "pi-acp@0.0.33"]
    system_prompt = "You review one branch."
    output_model = Verdict
    model = "anthropic/claude-sonnet-4"
    thinking = "high"
    tooling = "native"
    permission_policy = "auto_allow"
    max_repair_turns = 4
    ask_policy = "http"


# --------------------------------------------------------------------------
# What the class says
# --------------------------------------------------------------------------


def test_the_defaults_are_the_ones_an_unwritten_line_leaves() -> None:
    """A seat that states nothing gets the documented default, not a guess."""

    plain = ACPAgent()
    assert plain.model is None
    assert plain.thinking is None
    assert plain.system_prompt is None
    assert plain.output_model is None
    assert plain.ask_policy == "off"
    assert plain.tooling == "auto"
    assert plain.permission_policy == "ask"
    assert plain.elicitation_policy == "ask"
    assert plain.max_repair_turns == 2
    assert plain.env_allowlist is None


def test_every_setting_is_a_class_attribute() -> None:
    """Read off the class, not off an instance built to ask (05).

    The engine never constructs a façade — a node body does — so the
    configuration has to be readable from the class a workflow declared,
    and an instance has to agree with it.
    """

    assert Configured.model == "anthropic/claude-sonnet-4"
    assert Configured.thinking == "high"
    assert Configured.tooling == "native"
    assert Configured.permission_policy == "auto_allow"
    assert Configured.max_repair_turns == 4
    assert Configured.output_model is Verdict
    assert Configured.ask_policy == "http"

    instance = Configured()
    for name in (
        "model",
        "thinking",
        "tooling",
        "permission_policy",
        "max_repair_turns",
        "output_model",
        "ask_policy",
    ):
        assert getattr(instance, name) == getattr(Configured, name), name


def test_a_subclass_narrows_without_touching_its_base() -> None:
    """Configuration on a subclass is the subclass's, not the tree's."""

    class Stricter(Configured):
        permission_policy = "auto_deny"

    assert Stricter.permission_policy == "auto_deny"
    assert Configured.permission_policy == "auto_allow"
    assert ACPAgent.permission_policy == "ask"


def test_only_the_four_run_time_arguments_are_constructor_arguments() -> None:
    """What differs per *run* is an argument; what differs per seat is not.

    ``command``, ``cwd``, ``timeout`` and ``env`` are the four a body may
    vary between two runs of the same class — a different worktree, a
    shorter budget — and everything else is the class, so a body cannot
    quietly hand an agent a different permission policy than the one its
    class was reviewed with (D10).
    """

    parameters = list(inspect.signature(ACPAgent.__init__).parameters)
    assert parameters == ["self", "command", "cwd", "timeout", "env"]

    agent = ACPAgent(command=["fake"], cwd="/tmp", timeout=5.0, env={"A": "1"})
    assert agent.command == ["fake"]
    assert agent.cwd == "/tmp"
    assert agent.timeout == 5.0
    assert agent.env == {"A": "1"}
    # ...and the class it was built from is untouched by any of it.
    assert ACPAgent.command == ["npx", "pi-acp"]


# --------------------------------------------------------------------------
# Prompts are inlined text
# --------------------------------------------------------------------------


AGENT_CLASSES = (Agent, ACPAgent, Configured)


@pytest.mark.parametrize("cls", AGENT_CLASSES, ids=lambda cls: cls.__name__)
def test_no_agent_class_carries_a_template(cls: type[Agent]) -> None:
    """v0's ``template=`` is not deferred; it does not exist (`AGENTS.md`)."""

    assert not hasattr(cls, "template")


async def test_an_inlined_prompt_is_sent_as_written() -> None:
    """Stripped, and otherwise byte for byte what the class holds (19)."""

    class Inlined(Agent):
        system_prompt = "\n# Role\n\nYou are the test stage.\n\n"

    assert await Inlined().render_prompt() == "# Role\n\nYou are the test stage."


async def test_the_base_class_has_no_run() -> None:
    """``Agent`` is the shape and the prompt; a façade is what runs."""

    with pytest.raises(NotImplementedError, match="subclass ACPAgent"):
        await Agent().run()


# --------------------------------------------------------------------------
# The provider seat: declared here, implemented outside the package (D27)
# --------------------------------------------------------------------------


def test_no_provider_is_the_default() -> None:
    """Without one there is no cost and no truncation detection (05)."""

    assert ACPAgent.stats_provider is None


async def test_a_provider_is_configuration_like_everything_else() -> None:
    """Set on the class, and it is what the façade will ask (T039a)."""

    provider = FakeStatsProvider(SessionStats(cost=0.25), stop_reason="length")

    class Measured(ACPAgent):
        stats_provider = provider

    assert Measured.stats_provider is provider
    assert Measured().stats_provider is provider

    reported = await provider.stats("01a0", "/work")
    assert reported is not None and reported.cost == 0.25
    assert await provider.final_stop_reason("01a0", "/work") == "length"
    assert provider.calls == [("01a0", "/work"), ("01a0", "/work")]


def test_an_agent_error_is_the_failure_a_body_cannot_route_on() -> None:
    """05 §AgentResult: the raised half of the outcome vocabulary."""

    error: Any = AgentError("transport went away")
    assert isinstance(error, Exception)
    assert str(error) == "transport went away"
