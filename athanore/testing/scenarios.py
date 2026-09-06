"""`scenario(**kwargs)`: a scripted `FakeACPAgent`, as a command line.

13 §Fakes gives the fake a JSON scenario and an argv; this turns the
first into the second, so a test that wants an agent writes what the
agent should do and not where the file went:

.. code-block:: python

    class Builder(ACPAgent):
        command = scenario(text=["done"], submit={"ok": True})

The keys are validated **here**, before a subprocess exists. An unknown
key is an error in the fake (13), but a scenario that only fails once the
child has spawned fails as a transport error three layers away from the
typo; failing at the call site names the key.

The file is a temporary one, and it outlives the call because the command
is used later — possibly many times, since a façade spawns a process per
run. They are removed together when the interpreter exits, which is the
lifetime an ``ACPAgent.command`` attribute set at import time actually
has.
"""

from __future__ import annotations

import atexit
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from athanore.testing.fake_acp import ScenarioError, validate_scenario

__all__ = ["FAKE_ACP", "ScenarioError", "scenario", "scenario_file"]

#: The fake, as a command line. Run by path rather than by ``-m`` so the
#: child never imports the package: the fake is stdlib-only, and starting
#: it must cost nothing an agent run would notice.
FAKE_ACP = [sys.executable, str(Path(__file__).with_name("fake_acp.py"))]

_scratch: Path | None = None


def scenario(**kwargs: Any) -> list[str]:
    """The ``command`` for an ``ACPAgent`` running this scenario.

    ``kwargs`` are the scenario keys of 13 §Fakes, exactly — an unknown
    one raises :exc:`~athanore.testing.fake_acp.ScenarioError` here.
    """

    return [*FAKE_ACP, "--scenario", str(scenario_file(**kwargs))]


def scenario_file(**kwargs: Any) -> Path:
    """Write one validated scenario to a temporary file and return its path.

    For the callers that need the file rather than the command line: a
    ``ATHANORE_FAKE_SCENARIOS`` directory built node by node, a test that
    passes ``--scenario`` itself.
    """

    validate_scenario(kwargs, where="scenario()")
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="scenario-",
        dir=_directory(),
        delete=False,
    )
    with handle:
        json.dump(kwargs, handle)
    return Path(handle.name)


def _directory() -> Path:
    """The one scratch directory, made on first use and removed at exit."""

    global _scratch
    if _scratch is None:
        _scratch = Path(tempfile.mkdtemp(prefix="athanore-scenarios-"))
        atexit.register(shutil.rmtree, _scratch, True)
    return _scratch
