"""Test fixtures: the doubles, and the fake ACP agent (13 §Fakes).

Four things, and they divide by what a test is actually about.
:class:`MockAgent` and :class:`StatsMockAgent` are for the tests that are
not about the wire — the engine's fan-in, its retries, its pools — and
run with no subprocess at all. :func:`scenario` is for the tests that
*are* about the wire: it scripts ``fake_acp.py``, a real process speaking
ACP over stdio, and hands back the ``command`` an ``ACPAgent`` runs.
:class:`FakeStatsProvider` supplies the two numbers no protocol carries.

They ship with the package rather than living under ``tests/`` because
the examples run on them: ``ATHANORE_AGENT_COMMAND`` pointed at the fake
is how a workflow runs end to end in CI with no model in the loop (13
§Running examples on the fake), and that has to work from an installed
wheel.
"""

from athanore.testing.fake_acp import SCENARIO_KEYS, ScenarioError, validate_scenario
from athanore.testing.mock import FakeStatsProvider, MockAgent, StatsMockAgent
from athanore.testing.scenarios import FAKE_ACP, scenario, scenario_file

__all__ = [
    "FAKE_ACP",
    "SCENARIO_KEYS",
    "FakeStatsProvider",
    "MockAgent",
    "ScenarioError",
    "StatsMockAgent",
    "scenario",
    "scenario_file",
    "validate_scenario",
]
