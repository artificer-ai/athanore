"""The pi adapter, live: one run, one turn, real token counts (T077, A6.2).

Off unless ``ATHANORE_SMOKE=1``. See `tests/smoke/conftest.py` for the
switch and 13 §Live smoke for how to run it.

The seat under test is `docker_acp`'s :class:`docker_acp.DockerAgent` —
pi over ACP, spawned through `scripts/agent.sh`, which is the dev stack's
one way in and therefore the same command on either side of the container
boundary (D64, D67). It is the smallest pi workflow the examples have:
one node, one agent, whatever the operator submitted, and no second stage
to spend a turn on.

**What this asserts is the stats entry, not the answer.** `AGENTS.md`
§Real data only is a claim about numbers nothing here can fake: pi's
token counts reach a `[stats]` line either as the ACP response's
``usage`` or through :class:`pi.stats.PiSessionStats`, which reads the
session JSONL the agent wrote — the file `compose.yaml` mounts from the
host for exactly this (05 §Stats, D27). A fake agent produces those
numbers only when a scenario invents them; a live one spends them. So
the assertions are: the run completed, the agent node wrote a line, its
token pair is two real numbers, and the three destinations 05 records
one entry to agree with each other.

``cost`` is asserted as well, and only here: it is the one field no
protocol carries, so a line that has it is a line whose session file was
found, parsed, and matched to the session this run opened. The Claude
seat has no provider and therefore no cost, which is the other half of
the same fact and what `test_claude.py` asserts instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import docker_acp

#: What the agent is asked to do. Deliberately the cheapest turn that is
#: still a whole athanore session — a task read, a work-log entry
#: written, a turn ended — because a smoke test that wrote a program
#: would be measuring the model rather than the wire, and would cost what
#: measuring the model costs.
ASSIGNMENT = """\
This is a connectivity check, not a coding task.

Do exactly this and nothing else: append one line to the run's work log
saying `pi live smoke: ok`, then finish your turn with the same words as
your reply. Create no files, edit no files, and run no commands.
"""


async def test_pi_completes_a_live_run_and_records_real_token_counts(
    live: Callable[..., Any],
    require: Callable[..., None],
    installed: Callable[..., None],
) -> None:
    """A real pi turn, and the `[stats]` line it is worth running for."""

    require(
        "OPENROUTER_API_KEY",
        adapter="pi (the OpenRouter provider of docker/dev/pi/models.json)",
    )
    installed(docker_acp.DockerAgent)

    result = await live(
        docker_acp.wf,
        title="live smoke: pi over ACP",
        description=ASSIGNMENT,
    )

    assert result.run["status"] == "completed", (
        f"the run is {result.run['status']}, not completed:\n{result.transcript()}"
    )

    node = "implement"
    input_tokens, output_tokens = result.real_tokens(node)
    line = result.stats_line(node)
    assert "model=" in line, f"the stats line names no model: {line!r}"
    assert "cost=" in line, (
        "the stats line carries no cost, so pi's session file was not read — "
        f"the ~/.pi/agent/sessions mount or its layout has changed (D27): {line!r}"
    )

    entries = [entry for entry in result.stats_events if entry["node"] == node]
    assert len(entries) == 1, f"expected one agent.stats event, got {entries}"
    assert entries[0]["input_tokens"] == input_tokens
    assert entries[0]["output_tokens"] == output_tokens
    assert entries[0]["session_id"], "the entry names no ACP session"

    totals = result.run["stats"]
    assert totals["input_tokens"] == input_tokens
    assert totals["output_tokens"] == output_tokens
