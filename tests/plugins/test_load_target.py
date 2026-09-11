"""The loader, and loading a target a second time (T085, 22 §Reloading a
module), plus the `athanore.toml` tables it reads (22 §Persistence).

`load_target` moved here from the CLI so the API can reach it; what is
new is `reload=True`. A file target executes afresh into a new module
object; a module target's whole subtree is purged from `sys.modules`
and imported again, and nothing outside it — a sibling package, a helper
imported from elsewhere — is touched. Every failure is a `LoadError`
naming its stage, and a failed load leaves `sys.modules` as the failure
found it.

Everything is written under `tmp_path` and imported from there, because
the subject is what happens to *real* `sys.modules` entries and real
files; the `restore_imports` fixture puts both back afterwards.
"""

from __future__ import annotations

import importlib
import inspect
import os
import stat
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from athanore.plugins.discovery import (
    WORKFLOW_KEYS,
    LayoutError,
    LoadError,
    load_target,
    read_layout,
)
from athanore.workflow import Workflow


def flow_source(name: str, node: str, marker: str = "one") -> str:
    """A workflow file: one node called ``node``, with ``marker`` in its body.

    The marker is what `inspect.getsource` is asserted on after a reload,
    and the two versions of a file differ in length so `linecache`'s
    size-and-mtime check is exact whatever the file system's timestamp
    granularity.
    """

    return (
        "from athanore.workflow import Workflow\n"
        "\n"
        f'wf = Workflow("{name}")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        f"async def {node}():\n"
        f'    """The {marker} version."""\n'
        f'    return "{marker}"\n'
        "\n"
        "\n"
        "def factory():\n"
        "    return wf\n"
        "\n"
        "\n"
        "def explodes():\n"
        '    raise RuntimeError("the factory could not build it")\n'
        "\n"
        "\n"
        "def wrong():\n"
        '    return "not a workflow"\n'
        "\n"
        "\n"
        'text = "not a workflow either"\n'
    )


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """Leave `sys.path` and `sys.modules` as they were."""

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]
    importlib.invalidate_caches()


@pytest.fixture(autouse=True)
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in `tmp_path`, so a module target resolves against it."""

    monkeypatch.chdir(tmp_path)
    return tmp_path


def node_names(wf: Workflow) -> set[str]:
    return set(wf.finalize().nodes)


def body_of(wf: Workflow, node: str) -> Callable[..., Any]:
    """The function a node wraps, for `inspect.getsource`."""

    return wf.finalize().nodes[node].fn


# --------------------------------------------------------------------------
# A file target
# --------------------------------------------------------------------------


def test_a_file_target_loads_and_reloads_the_edited_file(tmp_path: Path) -> None:
    """The second load is a new module, a new workflow, and the new text."""

    file = tmp_path / "flows.py"
    file.write_text(flow_source("demo", "first"))
    first = load_target("flows.py:wf")
    first_module = sys.modules["flows"]
    assert node_names(first) == {"first"}
    assert "The one version." in inspect.getsource(body_of(first, "first"))

    file.write_text(flow_source("demo", "second", marker="rewritten"))
    second = load_target("flows.py:wf", reload=True)
    assert second is not first
    assert node_names(second) == {"second"}
    assert sys.modules["flows"] is not first_module
    assert "The rewritten version." in inspect.getsource(body_of(second, "second"))
    # The old object is what an attempt in flight holds, and it is
    # unchanged: its body is still the first one.
    assert node_names(first) == {"first"}


def test_a_file_targets_directory_is_importable(tmp_path: Path) -> None:
    """`path/to/file.py:wf` runs the file as running it directly would."""

    (tmp_path / "helper.py").write_text("NAME = 'demo'\n")
    (tmp_path / "flows.py").write_text(
        "from athanore.workflow import Workflow\n"
        "from helper import NAME\n"
        "\n"
        "demo = Workflow(NAME)\n"
        "\n"
        "@demo.node(start=True)\n"
        "async def only():\n"
        "    return None\n"
    )
    workflow = load_target("flows.py:demo")
    assert isinstance(workflow, Workflow)
    assert workflow.name == "demo"


def test_a_factory_attribute_is_called(tmp_path: Path) -> None:
    """A callable returning a workflow is a target, as an entry point may be."""

    (tmp_path / "flows.py").write_text(flow_source("demo", "only"))
    assert load_target("flows.py:factory").name == "demo"


# --------------------------------------------------------------------------
# A module target
# --------------------------------------------------------------------------


def write_package(tmp_path: Path, marker: str = "one") -> None:
    """`workflows/` with a `feature` subpackage, a `rps` sibling, a helper.

    `feature/__init__.py` imports its own `agents` submodule and a helper
    from *outside* the package (`shared`), which is the shape 22
    §Reloading a module draws the line through: the subtree reloads, the
    sibling and the helper do not.
    """

    root = tmp_path / "workflows"
    (root / "feature").mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text("")
    (root / "feature" / "agents.py").write_text(f'MARKER = "{marker}"\n')
    (root / "feature" / "__init__.py").write_text(
        "from athanore.workflow import Workflow\n"
        "from shared import HELPER\n"
        "from workflows.feature.agents import MARKER\n"
        "\n"
        'wf = Workflow("feature")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        f"async def {marker}():\n"
        f'    """The {marker} version."""\n'
        "    return MARKER + HELPER\n"
    )
    (root / "rps.py").write_text(
        "from athanore.workflow import Workflow\n"
        "\n"
        'wf = Workflow("rps")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        "async def throw():\n"
        "    return None\n"
    )
    (tmp_path / "shared.py").write_text(f'HELPER = "{marker}"\n')


def test_a_module_target_reload_purges_its_subtree_and_nothing_else(
    tmp_path: Path,
) -> None:
    """Editing a submodule and reloading the package picks the change up."""

    write_package(tmp_path)
    first = load_target("workflows.feature:wf")
    sibling = load_target("workflows.rps:wf")
    package = sys.modules["workflows.feature"]
    submodule = sys.modules["workflows.feature.agents"]
    sibling_module = sys.modules["workflows.rps"]
    helper = sys.modules["shared"]
    assert node_names(first) == {"one"}

    # A different length, not just different text: the bytecode cache
    # is keyed on the source's size and mtime, and a rewrite inside the
    # same second with the same length is the interpreter's blind spot,
    # not the loader's.
    write_package(tmp_path, marker="rewritten")
    second = load_target("workflows.feature:wf", reload=True)

    # The package and its submodule are new objects carrying the change.
    assert sys.modules["workflows.feature"] is not package
    assert sys.modules["workflows.feature.agents"] is not submodule
    assert sys.modules["workflows.feature.agents"].MARKER == "rewritten"
    assert node_names(second) == {"rewritten"}
    assert "The rewritten version." in inspect.getsource(body_of(second, "rewritten"))
    # The sibling and the helper from outside the subtree are untouched
    # (22 §Scope): same objects, old text.
    assert sys.modules["workflows.rps"] is sibling_module
    assert sys.modules["shared"] is helper
    assert sys.modules["shared"].HELPER == "one"
    assert load_target("workflows.rps:wf") is sibling
    # The parent package was not purged either.
    assert "workflows" in sys.modules


def test_a_module_target_without_reload_is_the_cached_import(
    tmp_path: Path,
) -> None:
    """The first-load behaviour: `import_module`, which caches."""

    write_package(tmp_path)
    first = load_target("workflows.feature:wf")
    write_package(tmp_path, marker="rewritten")
    assert load_target("workflows.feature:wf") is first


def test_a_new_submodule_is_visible_after_a_reload(tmp_path: Path) -> None:
    """A file written since the first import is found by the second.

    The finder caches directory listings; a reload invalidates them, or
    the new submodule would be an `ImportError` until the process
    restarted.
    """

    write_package(tmp_path)
    load_target("workflows.feature:wf")
    (tmp_path / "workflows" / "feature" / "extra.py").write_text('EXTRA = "yes"\n')
    (tmp_path / "workflows" / "feature" / "__init__.py").write_text(
        "from athanore.workflow import Workflow\n"
        "from workflows.feature.extra import EXTRA\n"
        "\n"
        'wf = Workflow("feature")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        "async def uses_extra():\n"
        "    return EXTRA\n"
    )
    assert node_names(load_target("workflows.feature:wf", reload=True)) == {
        "uses_extra"
    }


# --------------------------------------------------------------------------
# Failures, by stage
# --------------------------------------------------------------------------


def test_a_string_that_is_not_a_target_is_stage_target(tmp_path: Path) -> None:
    for target in ["flows.py", ":wf", "flows.py:"]:
        with pytest.raises(LoadError) as raised:
            load_target(target)
        error = raised.value
        assert error.stage == "target"
        assert error.target == target
        assert error.detail == str(error)
        assert error.conflict is False
        assert "is not a workflow target" in str(error)


@pytest.mark.parametrize(
    ("write", "target", "says"),
    [
        (
            lambda p: (p / "broken.py").write_text("def (\n"),
            "broken.py:wf",
            "could not be imported",
        ),
        (
            lambda p: (p / "raises.py").write_text('raise ImportError("no pi here")'),
            "raises.py:wf",
            "no pi here",
        ),
        (lambda p: None, "no_such_module:wf", "could not be imported"),
        (lambda p: None, "nowhere.py:wf", "which is not a file"),
        (
            lambda p: (p / "syntax_mod.py").write_text("def (\n"),
            "syntax_mod:wf",
            "could not be imported",
        ),
    ],
)
def test_a_module_or_file_that_will_not_load_is_stage_import(
    tmp_path: Path, write, target: str, says: str
) -> None:
    """A `SyntaxError`, an `ImportError` from user code, a missing module."""

    write(tmp_path)
    with pytest.raises(LoadError) as raised:
        load_target(target)
    error = raised.value
    assert error.stage == "import"
    assert error.target == target
    assert says in str(error) or says in error.detail
    assert error.conflict is False


@pytest.mark.parametrize(
    ("attribute", "says", "detail"),
    [
        ("missing", "has no attribute 'missing'", "missing"),
        ("text", "is a str, not a Workflow", "is a str"),
        ("explodes", "raised when called", "the factory could not build it"),
        ("wrong", "returned a str, not a Workflow", "returned a str"),
    ],
)
def test_an_attribute_that_is_not_a_workflow_is_stage_attribute(
    tmp_path: Path, attribute: str, says: str, detail: str
) -> None:
    """Missing, not a `Workflow`, a factory that raises or returns junk."""

    (tmp_path / "flows.py").write_text(flow_source("demo", "only"))
    target = f"flows.py:{attribute}"
    with pytest.raises(LoadError) as raised:
        load_target(target)
    error = raised.value
    assert error.stage == "attribute"
    assert error.target == target
    assert says in str(error)
    # `detail` is the underlying text, untouched: for a factory that
    # raised, the exception's own message.
    assert detail in error.detail
    assert error.conflict is False


def test_a_failing_file_reload_leaves_no_half_built_module(
    tmp_path: Path,
) -> None:
    """The stem is gone from `sys.modules`; the old workflow is unaffected."""

    file = tmp_path / "flows.py"
    file.write_text(flow_source("demo", "first"))
    first = load_target("flows.py:wf")
    file.write_text("def (\n")
    with pytest.raises(LoadError) as raised:
        load_target("flows.py:wf", reload=True)
    assert raised.value.stage == "import"
    assert "flows" not in sys.modules
    assert node_names(first) == {"first"}


def test_a_failing_module_reload_leaves_the_purge_in_place(
    tmp_path: Path,
) -> None:
    """22: a module target's purge is not undone; the next load fixes it."""

    write_package(tmp_path)
    first = load_target("workflows.feature:wf")
    (tmp_path / "workflows" / "feature" / "agents.py").write_text("def (\n")
    with pytest.raises(LoadError) as raised:
        load_target("workflows.feature:wf", reload=True)
    assert raised.value.stage == "import"
    assert "workflows.feature" not in sys.modules
    assert "workflows.feature.agents" not in sys.modules
    assert node_names(first) == {"one"}
    # And the next successful load repairs the cache.
    write_package(tmp_path, marker="fixed")
    assert node_names(load_target("workflows.feature:wf", reload=True)) == {"fixed"}


# --------------------------------------------------------------------------
# read_layout
# --------------------------------------------------------------------------


def test_read_layout_reads_pools_bindings_and_targets(tmp_path: Path) -> None:
    toml = tmp_path / "athanore.toml"
    assert read_layout(toml).pools == {}
    assert read_layout(toml).targets == {}
    toml.write_text(
        "host = '127.0.0.1'\n\n"
        "[pools]\nlocal = 1\ncloud = 8\n\n"
        "[workflows]\n"
        'feature_build = { pool = "local" }\n'
        "msgtest = { }\n"
        'chat = { target = "workflows/chat.py:wf", pool = "cloud" }\n'
        'hello = { target = "workflows/hello.py:wf" }\n'
    )
    layout = read_layout(toml)
    assert layout.pools == {"local": 1, "cloud": 8}
    # `msgtest` and `hello` named no pool, so they are absent rather than
    # bound to a name nobody wrote; `feature_build` has no target and is
    # a binding only.
    assert layout.bindings == {"feature_build": "local", "chat": "cloud"}
    assert list(layout.targets.items()) == [
        ("chat", "workflows/chat.py:wf"),
        ("hello", "workflows/hello.py:wf"),
    ]


@pytest.mark.parametrize(
    ("toml", "says"),
    [
        ("[pools]\nlocal = true\n", "integer capacity"),
        ('[pools]\nlocal = 1\n[workflows]\ndemo = { poll = "local" }\n', "`poll`"),
        ("[workflows]\ndemo = 1\n", "must be a table"),
        ("[workflows]\ndemo = { pool = 2 }\n", "must be a pool name"),
        ("[workflows]\ndemo = { target = 2 }\n", "must name a workflow"),
        ('[workflows]\ndemo = { target = "flows.py" }\n', "must name a workflow"),
        ("pools = 1\n", "must be a table"),
        ("[workflows\n", "could not be read"),
    ],
)
def test_read_layout_refuses_what_it_cannot_use(
    tmp_path: Path, toml: str, says: str
) -> None:
    """02: a typo must not silently fall back to a default."""

    path = tmp_path / "athanore.toml"
    path.write_text(toml)
    with pytest.raises(LayoutError) as raised:
        read_layout(path)
    assert says in str(raised.value)
    assert raised.value.path == path


def test_an_unknown_key_names_both_known_ones(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text('[workflows]\ndemo = { targt = "x.py:wf" }\n')
    with pytest.raises(LayoutError, match="`pool` and `target`"):
        read_layout(path)
    assert WORKFLOW_KEYS == {"pool", "target"}


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads unreadable files")
def test_an_unreadable_file_is_a_layout_error(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text("[pools]\nlocal = 1\n")
    path.chmod(0)
    try:
        with pytest.raises(LayoutError, match="could not be read"):
            read_layout(path)
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
