"""The Claude Code adapter, live: one run, real token counts (T077, A6.2).

Off unless ``ATHANORE_SMOKE=1``. See `tests/smoke/conftest.py` for the
switch and 13 §Live smoke for how to run it.

The seat under test is `claude_acp`'s
:class:`claude_acp.ImplementerAgent` — `@agentclientprotocol/
claude-agent-acp`, a model id, and nothing else, which is the whole of
what "a vendor seat" means in v1 (05 §User-land adapters). The workflow
is that example's own ``implement → wrap``: one small unambiguous edit
in a scratch repository, then deterministic code that reads the file
back. It is the portability check of 20 §Findings 1-4 with a real
adapter behind it rather than a fake.

**What this asserts is the stats entry, not the answer.** Whether the
edit landed is `wrap`'s verdict and it is in the work log either way;
what a live run proves and `FakeACPAgent` cannot is a `[stats]` line
carrying tokens a vendor reported (05 §Stats entry). So the assertions
are: the run completed, the agent node wrote a line, its token pair is
two real numbers, and 05's three destinations agree.

``cost`` is asserted **absent**, and only here: ``ClaudeAgent`` declares
``stats_provider = None`` because this adapter keeps no session file
this package knows how to read, and 01 §Real data only says an unknown
measurement is omitted rather than estimated. A cost on this line would
mean something had started guessing.

**The credential.** ``ANTHROPIC_API_KEY``, or the credentials the
adapter keeps under ``~/.claude`` (``claude setup-token``, or
``/login``; ``CLAUDE_CONFIG_DIR`` moves the directory).
``CLAUDE_CODE_OAUTH_TOKEN`` is deliberately **not** one of them: the
façade scrubs ``CLAUDE_*`` from every agent's environment (20 §Finding
4, 12 §Agents), so a token exported into this process never reaches the
child and a skip that named it would be a lie.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import claude_acp


def credentials_file() -> Path:
    """Where the adapter keeps the credentials `claude setup-token` writes.

    ``CLAUDE_CONFIG_DIR`` is the adapter's own override and is honoured
    here for the same reason the file is looked at at all: an agent whose
    credentials are on disk needs no variable exported, and a smoke test
    that only looked at the environment would skip on a machine that is
    logged in.
    """

    home = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(home) / ".credentials.json"


async def test_claude_completes_a_live_run_and_records_real_token_counts(
    live: Callable[..., Any],
    require: Callable[..., None],
    installed: Callable[..., None],
) -> None:
    """A real Claude turn, and the `[stats]` line it is worth running for."""

    require(
        "ANTHROPIC_API_KEY",
        files=[credentials_file()],
        adapter="Claude Code",
    )
    installed(claude_acp.ImplementerAgent)

    result = await live(
        claude_acp.wf,
        title="live smoke: Claude Code over ACP",
        description="The assignment is the workflow's; this title is not read.",
    )

    assert result.run["status"] == "completed", (
        f"the run is {result.run['status']}, not completed:\n{result.transcript()}"
    )

    node = "implement"
    input_tokens, output_tokens = result.real_tokens(node)
    line = result.stats_line(node)
    assert "model=" in line, f"the stats line names no model: {line!r}"
    assert "cost=" not in line, (
        "the stats line carries a cost, but this seat declares no stats "
        f"provider and no protocol reports one (D27): {line!r}"
    )

    entries = [entry for entry in result.stats_events if entry["node"] == node]
    assert len(entries) == 1, f"expected one agent.stats event, got {entries}"
    assert entries[0]["input_tokens"] == input_tokens
    assert entries[0]["output_tokens"] == output_tokens
    assert entries[0]["session_id"], "the entry names no ACP session"

    totals = result.run["stats"]
    assert totals["input_tokens"] == input_tokens
    assert totals["output_tokens"] == output_tokens
