"""What both live smoke scripts need, and the switch that keeps them off.

`tests/smoke/` is the one place in this suite where a **model is
actually called** (13 §Live smoke). Everything else in the tree runs on
`FakeACPAgent`, which is the only agent CI runs (`AGENTS.md` §Stack), so
the two files beside this one are gated on ``ATHANORE_SMOKE=1`` and skip
whenever it is absent — which is every run of the gate and every run in
CI.

What a live run proves and a fake cannot is a **stats line with real
token counts**: numbers a vendor reported for tokens it actually spent
(05 §Stats entry). That is the assertion, and it is the only one about
what a model produced. Nothing here reads the words that came back.

Four things this file decides, because an unattended live run has to
decide them:

- **The environment is cleared and then stated.** Every ``ATHANORE_*``
  the dev stack exports would otherwise reach the server under test —
  and ``ATHANORE_AGENT_COMMAND`` in particular would replace the real
  adapter with the fake, which is the one substitution that would make
  this suite lie about what it ran (05, 13 §Running examples on the
  fake). The names the *stack* owns rather than the settings
  (:data:`KEEP`) survive, because `scripts/agent.sh` reads one of them
  to know which side of the container boundary it is on.
- **The settings are stated in the environment**, not passed as
  arguments: `claude_acp` and `docker_acp` build their own
  ``AthanoreSettings()`` inside a node body, and a body that disagreed
  with the server about ``root_path`` would put its scratch repository
  somewhere the run was not.
- **The permission policy is forced to ``auto_allow``.** `claude_acp`'s
  seat is ``ask`` on purpose, and ``ACPAgent.permission_timeout``
  defaults to ``None``: a request nobody answers blocks the turn for
  ever, and there is nobody here to answer one.
  ``settings.permission_policy`` is the documented global override.
- **The port is ephemeral and the agent's URL follows it.** ``port=0``,
  and `Server` adopts the bound port into ``settings.public_url``, which
  is what an agent is told to call (12 §S6) — so a smoke run never
  collides with an ``athanore serve`` already on 4002.

A missing credential is a **skip that names it**, never a transport
failure a minute in; so is an adapter that is not installed. That is
what makes "run the smoke tests" a safe thing to type on a machine that
has one of the two set up and not the other.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from athanore.agents.acp import ACPAgent
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

#: The switch. Anything but ``1`` and every test in this directory skips.
SMOKE = "ATHANORE_SMOKE"

#: How long a whole live run may take before the test gives up, in
#: seconds, and the variable that moves it. The default is generous
#: because a hosted model queues and a local one is slower still; it is
#: finite because a wedged adapter must cost one test rather than an
#: afternoon.
DEADLINE = "ATHANORE_SMOKE_TIMEOUT"
DEFAULT_DEADLINE = 900.0

#: ``ATHANORE_*`` names that are **not** settings and must survive the
#: clearing: `scripts/agent.sh` execs the adapter in this container or
#: dispatches into a sibling one depending on ``ATHANORE_IN_CONTAINER``,
#: and the other two are this suite's own switches.
KEEP = frozenset({"ATHANORE_IN_CONTAINER", SMOKE, DEADLINE})

#: The token pair in a ``[stats]`` line, as `format_stats_line` writes
#: it: ``tokens=12,406 in / 1,204 out / 13,610 total``. A side that was
#: never measured is written as the ``n`` marker rather than as a zero
#: (05 §Stats entry), so a line that says ``n in`` does not match here —
#: which is exactly the difference a live run is run to find.
TOKENS = re.compile(r"tokens=([\d,]+) in / ([\d,]+) out")


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip every test in this directory unless the switch is on.

    A hook rather than a marker per module: the rule belongs to the
    directory, and a file that forgot the marker would be a live model
    call in the middle of the gate.
    """

    if os.environ.get(SMOKE) != "1":
        pytest.skip(f"live smoke: set {SMOKE}=1 to call a real model (13 §Live smoke)")


@dataclass(frozen=True)
class Live:
    """One finished live run, as the API reports it.

    Everything a smoke test asserts is read back over the wire, for 02
    §One wire contract's reason: what a client can see is the whole of
    what the run did.
    """

    #: ``GET /api/runs/{id}``, including the summed ``stats`` of D46.
    run: dict[str, Any]
    #: ``GET /api/runs/{id}/log``, oldest first.
    log: list[dict[str, Any]]
    #: ``GET /api/runs/{id}/events``, the history the stream replays.
    events: list[dict[str, Any]]

    @property
    def stats_lines(self) -> list[str]:
        """The ``[stats]`` work-log entries, in order (05 §Stats entry)."""

        return [str(e["text"]) for e in self.log if e.get("kind") == "stats"]

    @property
    def stats_events(self) -> list[dict[str, Any]]:
        """The ``agent.stats`` payloads, in order (18 §agent.stats)."""

        return [dict(e["data"]) for e in self.events if e["name"] == "agent.stats"]

    def stats_line(self, node: str) -> str:
        """The one ``[stats]`` line ``node`` wrote, or fail saying so."""

        lines = [line for line in self.stats_lines if f"node={node} " in line]
        assert lines, (
            f"{node} recorded no [stats] line; the run is {self.run['status']} "
            f"and its log is:\n{self.transcript()}"
        )
        return lines[-1]

    def real_tokens(self, node: str) -> tuple[int, int]:
        """``node``'s reported ``in`` / ``out`` counts, both non-zero.

        The assertion T077 exists for, in one place. A real turn spends
        tokens on both sides; a measurement that was never made is the
        ``n`` marker and never a zero, so neither a missing pair nor a
        zeroed one passes here.
        """

        line = self.stats_line(node)
        found = TOKENS.search(line)
        assert found, f"no token counts in {node}'s stats line: {line!r}"
        given = (int(found[1].replace(",", "")), int(found[2].replace(",", "")))
        assert given[0] > 0 and given[1] > 0, (
            f"{node} reports {given[0]} in / {given[1]} out, which is not what a "
            f"live turn spends: {line!r}"
        )
        return given

    def transcript(self) -> str:
        """The whole work log, for a failure message worth reading."""

        return "\n".join(f"  {e['node']}/{e['author']}: {e['text']}" for e in self.log)


def _deadline() -> float:
    """The wait budget, from the environment or :data:`DEFAULT_DEADLINE`."""

    raw = os.environ.get(DEADLINE, "").strip()
    if not raw:
        return DEFAULT_DEADLINE
    try:
        seconds = float(raw)
    except ValueError:
        raise ValueError(f"{DEADLINE}={raw!r} is not a number of seconds") from None
    if seconds <= 0:
        raise ValueError(f"{DEADLINE}={raw!r} must be a positive number of seconds")
    return seconds


@pytest.fixture
def require() -> Callable[..., None]:
    """Skip, naming what is missing, rather than fail on a transport error.

    A credential is there when one of ``names`` is exported or one of
    ``files`` exists — an adapter that keeps its own credentials on disk
    (Claude Code does) needs no variable at all. The message names every
    place that was looked in, because a skip that does not say which
    credential is missing is one nobody can act on.
    """

    def check(
        *names: str, files: Sequence[Path] = (), adapter: str = "the adapter"
    ) -> None:
        if any(os.environ.get(name) for name in names):
            return
        if any(path.is_file() for path in files):
            return
        where = " or ".join([*names, *(str(path) for path in files)])
        pytest.skip(f"{adapter} has no credentials here: set or create {where}")

    return check


@pytest.fixture
def installed() -> Callable[[type[ACPAgent]], None]:
    """Skip when the adapter a seat spawns is not on this machine.

    T077 passes "against installed adapters"; a machine with one of the
    two set up must name the one it is missing rather than report a
    ``FileNotFoundError`` from a subprocess spawn as a failed run.
    """

    def check(agent: type[ACPAgent]) -> None:
        argv = list(agent.command)
        if not argv or shutil.which(argv[0]) is None:
            pytest.skip(
                f"{agent.__name__} spawns {' '.join(argv) or '<nothing>'}, and "
                f"{argv[0] if argv else 'it'} is not on PATH here"
            )

    return check


@pytest.fixture
def settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[AthanoreSettings]:
    """The one configuration the server and the node bodies both read."""

    for name in [key for key in os.environ if key.startswith("ATHANORE_")]:
        if name not in KEEP:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    monkeypatch.setenv("ATHANORE_HOST", "127.0.0.1")
    monkeypatch.setenv("ATHANORE_PORT", "0")
    monkeypatch.setenv("ATHANORE_WORKERS", "1")
    monkeypatch.setenv("ATHANORE_PERMISSION_POLICY", "auto_allow")
    monkeypatch.setenv("ATHANORE_AGENT_TIMEOUT", str(_deadline()))
    yield AthanoreSettings()


@pytest.fixture
async def live(
    settings: AthanoreSettings,
) -> AsyncIterator[Callable[..., Any]]:
    """Serve one workflow, submit one run, and hand back what the API says.

    The shape 17 §T077 asks for — start a `Server`, submit, wait for
    completion — in one callable, because the two smoke scripts differ
    only in the seat they check and the credentials it needs.
    """

    servers: list[Server] = []

    async def run(wf: Workflow, *, title: str, description: str = "") -> Live:
        server = Server(settings)
        server.register(wf)
        servers.append(server)
        await server.start()
        async with httpx.AsyncClient(base_url=server.url, timeout=60.0) as http:
            created = await http.post(
                f"/api/workflows/{wf.name}/runs",
                json={"title": title, "description": description},
            )
            assert created.status_code == 201, created.text
            run_id = str(created.json()["run_id"])
            detail = await _finished(http, run_id, _deadline())
            log = await _read(http, f"/api/runs/{run_id}/log")
            events = await _read(
                http, f"/api/runs/{run_id}/events", params={"limit": 5000}
            )
        return Live(run=detail, log=log, events=events)

    try:
        yield run
    finally:
        for server in servers:
            await server.stop()
        # `Server.start` configures logging against whatever `sys.stderr`
        # was when it ran, and pytest swaps that stream between phases.
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()


async def _read(
    http: httpx.AsyncClient, path: str, **kwargs: Any
) -> list[dict[str, Any]]:
    """A collection endpoint, raising on anything but a 200."""

    response = await http.get(path, **kwargs)
    assert response.status_code == 200, response.text
    return [dict(item) for item in response.json()]


async def _finished(
    http: httpx.AsyncClient, run_id: str, deadline: float
) -> dict[str, Any]:
    """Poll the run until it stops, or fail saying how far it got."""

    ends_at = time.monotonic() + deadline
    while True:
        response = await http.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        detail = dict(response.json())
        if detail["status"] in ("completed", "failed", "cancelled"):
            return detail
        if time.monotonic() > ends_at:
            raise AssertionError(
                f"run {run_id} was still {detail['status']} after {deadline:.0f}s, "
                f"at {detail.get('current_nodes')}; raise {DEADLINE} for a slower "
                "model"
            )
        await asyncio.sleep(1.0)
