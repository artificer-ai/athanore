"""Entry-point discovery and the pools it lands on (T072, 09 §Discovery).

The unit under test is "what an installed package advertises", so the
fixture is an **installed package**: :func:`install` writes a module and a
`.dist-info` with an `entry_points.txt` into a directory, and that
directory goes on `sys.path`. Nothing patches `importlib.metadata` —
`entry_points(group="athanore.workflows")` reads real metadata off a real
path entry, which is the only way this file can prove the group name, the
`module:attr` form and the `dist.name` in a failure message are right
rather than agreeing with a stub about them.

`serve` is exercised in-process with `Server.serve` captured. Everything
this task decides — which workflows are registered, which one wins when
two carry the same name, which pool each lands on, and what a broken
entry point costs — is settled before the socket is bound, and
`tests/cli/test_serve.py` already spawns the real thing to prove a bound
port answers. Capturing the server the command built is what lets each
of those be one assertion instead of an HTTP round trip.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from athanore.cli import main
from athanore.cli.output import EXIT_API_ERROR, EXIT_OK, EXIT_USAGE
from athanore.plugins.discovery import GROUP, DiscoveryError, discover
from athanore.server import Server

#: The distribution every test installs, and the version its failure
#: messages have to carry: the useful half of "this entry point is
#: broken" is the package to uninstall.
DIST = "acme-flows"
VERSION = "1.2.3"

#: A module with one of everything an entry point can point at: the
#: workflow itself, a factory that returns one, a factory that raises, a
#: factory that returns something else, and a plain value.
MODULE = """\
from athanore.workflow import Workflow


def _one(name, node):
    wf = Workflow(name)
    builder = wf.node(start=True)

    async def body():
        return None

    body.__name__ = node
    body.__doc__ = "Do nothing, successfully."
    builder(body)
    return wf


demo = _one("demo", "installed")


def build():
    return _one("built", "made_at_serve_time")


def build_demo():
    return _one("demo", "made_at_serve_time")


def verb_named():
    return _one("ls", "shadowed")


def explodes():
    raise RuntimeError("the factory could not build it")


def wrong_type():
    return "not a workflow"


text = "not a workflow either"
"""

#: A workflow file next to the project, as an operator writing one has.
#: Its workflow is called `demo` too, which is the collision the
#: precedence rule is about.
TYPED = '''\
from athanore.workflow import Workflow

demo = Workflow("demo")


@demo.node(start=True)
async def typed():
    """Do nothing, successfully."""
    return None
'''


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A working directory, a config home and an environment of our own.

    The same scrubbing `tests/cli/test_serve.py` does, and for the same
    reason: `serve` resolves its settings and its `athanore.toml` from
    the environment and the current directory, so a suite that read the
    developer's own would be reading the machine.
    """

    for name in [key for key in os.environ if key.startswith("ATHANORE_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """Leave `sys.path` and `sys.modules` as they were.

    Installing a distribution puts a directory on the path and loading an
    entry point imports out of it. In a test process both are global
    state, so both are undone — otherwise the second test in the file
    would import the first one's module out of `sys.modules` and never
    look at its own.
    """

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]
    importlib.invalidate_caches()


@pytest.fixture
def install(tmp_path: Path) -> Callable[..., Path]:
    """Install a distribution advertising the given entry points.

    Writes `acme_flows.py` and an `acme_flows-1.2.3.dist-info/` — the
    metadata a wheel installs and nothing more — into a directory of its
    own, and puts that directory first on `sys.path`. `entry_points()`
    finds it there the way it finds anything else on the path.
    """

    def installer(entries: dict[str, str], group: str = GROUP) -> Path:
        site = tmp_path / "site"
        (site / f"acme_flows-{VERSION}.dist-info").mkdir(parents=True, exist_ok=True)
        (site / "acme_flows.py").write_text(MODULE)
        (site / f"acme_flows-{VERSION}.dist-info" / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {DIST}\nVersion: {VERSION}\n"
        )
        (site / f"acme_flows-{VERSION}.dist-info" / "entry_points.txt").write_text(
            f"[{group}]\n"
            + "".join(f"{name} = {value}\n" for name, value in entries.items())
        )
        if str(site) not in sys.path:
            sys.path.insert(0, str(site))
        # The path entry is new in this process, and the directory it
        # names has just been written: both caches have to be dropped
        # before the finder will see it.
        importlib.invalidate_caches()
        return site

    return installer


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[Server]:
    """Capture the server `serve` built instead of running it.

    `Server.serve()` owns an event loop and blocks for as long as the
    operator leaves it running, so the command cannot be called in a test
    process without either hanging it or taking the loop apart. What this
    file is about happens before that call — the registrations, their
    pools, and the refusals — so the server is caught at the point it
    would have started serving, whole.
    """

    captured: list[Server] = []

    def capture(self: Server, on_start: object = None) -> None:
        captured.append(self)

    monkeypatch.setattr(Server, "serve", capture)
    return captured


def write_typed(tmp_path: Path) -> None:
    """A `flows.py` next to the project, with its own `demo` in it."""

    (tmp_path / "flows.py").write_text(TYPED)


def nodes(server: Server, name: str) -> set[str]:
    """The node names of a registered workflow's graph.

    Two workflows in this file are called `demo` and only their nodes
    tell them apart, which is exactly what "an explicit target wins" has
    to be asserted on: the *name* is equal either way.
    """

    return set(server.workflows[name].finalize().nodes)


# --------------------------------------------------------------------------
# discover()
# --------------------------------------------------------------------------


def test_discover_finds_an_installed_workflow(install: Callable[..., Path]) -> None:
    """An entry pointing at a `Workflow` is that workflow."""

    install({"demo": "acme_flows:demo"})
    found = discover()
    assert [wf.name for wf in found] == ["demo"]
    assert set(found[0].finalize().nodes) == {"installed"}


def test_an_entry_may_point_at_a_callable(install: Callable[..., Path]) -> None:
    """`module:factory` is called, so a package can build at serve time."""

    install({"built": "acme_flows:build"})
    found = discover()
    assert [wf.name for wf in found] == ["built"]
    assert set(found[0].finalize().nodes) == {"made_at_serve_time"}


def test_discover_finds_nothing_when_nothing_advertises(
    install: Callable[..., Path],
) -> None:
    """A distribution with no entry in the group contributes none.

    The group is the whole of what is imported: a package that declares
    workflows under some other name is not an installation Athanore reads.
    """

    install({"demo": "acme_flows:demo"}, group="acme.something_else")
    assert discover() == []


def test_entries_are_loaded_in_a_fixed_order(install: Callable[..., Path]) -> None:
    """By entry-point name, whatever order the metadata happened to list."""

    install({"zeta": "acme_flows:build", "alpha": "acme_flows:demo"})
    assert [wf.name for wf in discover()] == ["demo", "built"]


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ("acme_flows:missing", "could not be loaded"),
        ("no_such_module:demo", "could not be loaded"),
        ("acme_flows:text", "is a str, not a Workflow"),
        ("acme_flows:explodes", "raised when called"),
        ("acme_flows:wrong_type", "returned a str, not a Workflow"),
    ],
)
def test_an_entry_point_that_is_not_a_workflow_is_refused(
    install: Callable[..., Path], value: str, says: str
) -> None:
    """Every way an advertised entry can be broken, named rather than skipped."""

    install({"demo": value})
    with pytest.raises(DiscoveryError) as raised:
        discover()
    message = str(raised.value)
    assert says in message
    # The entry as it was written, and the package to uninstall.
    assert f"demo = {value}" in message
    assert f"{DIST} {VERSION}" in message


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------


def test_serve_registers_what_was_discovered(
    install: Callable[..., Path], served: list[Server]
) -> None:
    """`athanore serve` with no target at all serves the installed workflow."""

    install({"demo": "acme_flows:demo"})
    assert main(["serve", "--port", "0"]) == EXIT_OK
    assert nodes(served[0], "demo") == {"installed"}


def test_no_discover_registers_nothing(
    install: Callable[..., Path], served: list[Server]
) -> None:
    """The flag is the whole of it: the targets given are what is served."""

    install({"demo": "acme_flows:demo"})
    assert main(["serve", "--no-discover", "--port", "0"]) == EXIT_OK
    assert served[0].workflows == {}


def test_an_explicit_target_of_the_same_name_wins(
    tmp_path: Path, install: Callable[..., Path], served: list[Server]
) -> None:
    """Naming a target means that target, not the installed one beside it."""

    install({"demo": "acme_flows:demo"})
    write_typed(tmp_path)
    assert main(["serve", "flows.py:demo", "--port", "0"]) == EXIT_OK
    # One `demo`, and it is the file's: registering both would have been
    # refused by the server, and registering the installed one would have
    # made a working copy impossible to serve.
    assert list(served[0].workflows) == ["demo"]
    assert nodes(served[0], "demo") == {"typed"}


def test_a_target_does_not_suppress_the_other_discovered_workflows(
    tmp_path: Path, install: Callable[..., Path], served: list[Server]
) -> None:
    """Precedence is per name: only the collision is dropped."""

    install({"demo": "acme_flows:build_demo", "built": "acme_flows:build"})
    write_typed(tmp_path)
    assert main(["serve", "flows.py:demo", "--port", "0"]) == EXIT_OK
    assert sorted(served[0].workflows) == ["built", "demo"]
    assert nodes(served[0], "demo") == {"typed"}


def test_a_discovered_workflow_is_bound_by_athanore_toml(
    tmp_path: Path, install: Callable[..., Path], served: list[Server]
) -> None:
    """`[workflows]` binds by workflow name, however the workflow was found."""

    install({"anything": "acme_flows:demo"})
    (tmp_path / "athanore.toml").write_text(
        '[pools]\nlocal = 3\n\n[workflows]\ndemo = { pool = "local" }\n'
    )
    assert main(["serve", "--port", "0"]) == EXIT_OK
    assert served[0].engine.pools.snapshot() == {
        "local": {"capacity": 3, "in_flight": 0}
    }


def test_an_unbound_discovered_workflow_runs_on_the_default_pool(
    install: Callable[..., Path], served: list[Server]
) -> None:
    """Sized by `--workers`, exactly as a target that nothing bound is."""

    install({"demo": "acme_flows:demo"})
    assert main(["serve", "--port", "0", "--workers", "4"]) == EXIT_OK
    assert served[0].engine.pools.snapshot() == {
        "default": {"capacity": 4, "in_flight": 0}
    }


def test_a_discovered_workflow_bound_to_an_undeclared_pool_is_a_usage_error(
    tmp_path: Path,
    install: Callable[..., Path],
    served: list[Server],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo in `[workflows]` costs 2 and names the pool it could not find."""

    install({"demo": "acme_flows:demo"})
    (tmp_path / "athanore.toml").write_text(
        '[pools]\nlocal = 1\n\n[workflows]\ndemo = { pool = "sandbox" }\n'
    )
    assert main(["serve", "--port", "0"]) == EXIT_USAGE
    assert "sandbox" in capsys.readouterr().err
    # Nothing was served: a typo must not silently fall back to the
    # default pool (02 §`athanore.toml` layout).
    assert served == []


def test_a_broken_entry_point_stops_the_server(
    install: Callable[..., Path],
    served: list[Server],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """It is said as a sentence, priced as an error, and it is not skipped."""

    install({"demo": "acme_flows:explodes"})
    assert main(["serve", "--port", "0"]) == EXIT_API_ERROR
    said = capsys.readouterr().err
    assert "demo = acme_flows:explodes" in said
    assert DIST in said
    assert served == []


def test_no_discover_is_the_way_past_a_broken_package(
    tmp_path: Path, install: Callable[..., Path], served: list[Server]
) -> None:
    """The operator's own workflow is servable while a package is broken."""

    install({"demo": "acme_flows:explodes"})
    write_typed(tmp_path)
    assert main(["serve", "flows.py:demo", "--no-discover", "--port", "0"]) == EXIT_OK
    assert nodes(served[0], "demo") == {"typed"}


def test_two_distributions_advertising_one_name_are_refused(
    install: Callable[..., Path],
    served: list[Server],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A collision between two entries is the registration refusing it.

    Both are discovered — neither is an explicit target, so neither wins
    — and `Server.register` says the name is already taken. Better than
    picking one: rebinding a name would leave whichever lost invisible.
    """

    install({"first": "acme_flows:demo", "second": "acme_flows:build_demo"})
    assert main(["serve", "--port", "0"]) == EXIT_API_ERROR
    assert "already registered" in capsys.readouterr().err
    assert served == []


def test_the_discovered_workflow_is_a_real_workflow(
    install: Callable[..., Path],
    served: list[Server],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """It is registered through the same door, so the same refusals apply.

    A workflow whose name shadows a CLI verb is refused whether it was
    typed or advertised: discovery is where a workflow comes from, not a
    second set of rules about what one may be.
    """

    install({"anything": "acme_flows:verb_named"})
    assert main(["serve", "--port", "0"]) == EXIT_API_ERROR
    assert "verb" in capsys.readouterr().err
    assert served == []
