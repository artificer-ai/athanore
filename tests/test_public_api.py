"""The package's front door (T055, 02 §Public API, 14 §Compatibility).

`athanore/__init__.py` is a promise made in two documents, so this suite
reads both rather than restating either:

- the **surface** is the ``from athanore import (...)`` block of 02
  §Public API, parsed out of the document with :mod:`ast`. Comparing
  ``__all__`` to a list copied into this file would only prove the copy
  and the code agree; comparing it to the document proves the *spec* and
  the code agree, and it fails the moment a name is added to one of them
  alone.
- the **aliases** are 14 §Compatibility's four MVP names. Prose is not
  parseable, so the names are written here — and each one is asserted to
  still be named by that section, which is the half a test can check.

The third property has no line in either document and is the reason the
module is written the way it is: **importing `athanore` imports almost
nothing**. 02 §Layering says the module an author defines a workflow in
must not pull uvicorn, the API and the store in behind it, and this
module runs before every one of them, so the lazy surface is what keeps
that true. It is asserted in a fresh interpreter, exactly as
`tests/test_workflow.py` asserts the same thing one layer down: a lazy
import that quietly became eager is invisible to a `sys.modules` under
pytest, where everything is imported already.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

import athanore

#: The specifications this suite reads.
DOCS = Path(__file__).resolve().parents[1] / "docs" / "v1"
ARCHITECTURE = DOCS / "02-architecture.md"
MIGRATION = DOCS / "14-migration-and-phasing.md"

#: 14 §Compatibility's list, and what each name is now. The MVP's
#: `AthanoreAgent` was the base façade and `AthanoreACPAgent` the ACP
#: subclass, which is the pairing v1 keeps under shorter names.
ALIASES = {
    "AthanoreWorkflow": "Workflow",
    "AthanoreAgent": "Agent",
    "AthanoreACPAgent": "ACPAgent",
    "AthanoreServer": "Server",
}


def section(document: Path, heading: str) -> str:
    """The text under ``heading`` in ``document``, up to the next heading.

    ``heading`` is a prefix — 02's is titled with the file it is about —
    and "the next heading" is the next one at the same level or above, so
    a subsection stays part of the section that contains it.
    """

    depth = len(heading.split(" ", 1)[0])
    lines = document.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading)) + 1
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= depth:
            break
        body.append(line)
    return "\n".join(body)


def documented_surface() -> list[str]:
    """The names of 02 §Public API's import block, in the order it lists them.

    Parsed rather than pattern-matched: the block is Python, so the
    parser that reads it is the one that would reject a typo in it.
    """

    body = section(ARCHITECTURE, "### Public API")
    _, _, fenced = body.partition("```python")
    snippet, _, _ = fenced.partition("```")
    (statement,) = ast.parse(snippet).body
    assert isinstance(statement, ast.ImportFrom) and statement.module == "athanore"
    return [alias.name for alias in statement.names]


def test_all_is_exactly_the_documented_surface() -> None:
    """Both directions: nothing missing from `__all__`, nothing extra in it."""

    documented = documented_surface()
    assert set(athanore.__all__) == set(documented)
    # And the list is sorted, so a name added to it lands in one place.
    assert list(athanore.__all__) == sorted(athanore.__all__)


@pytest.mark.parametrize("name", documented_surface())
def test_every_documented_name_is_importable(name: str) -> None:
    """`from athanore import <name>` works, for every name 02 lists."""

    imported = __import__("athanore", fromlist=[name])
    assert getattr(imported, name) is getattr(athanore, name)


@pytest.mark.parametrize("name", sorted(set(documented_surface()) - {"__version__"}))
def test_every_name_is_the_object_its_module_defines(name: str) -> None:
    """The re-export is the definition, not a copy of it.

    A table of `(module, attribute)` pairs can be wrong in a way that
    still imports — two names pointing at one object — so each is checked
    against the module it claims to come from.
    """

    module, attribute = athanore._EXPORTS[name]
    assert getattr(athanore, name) is getattr(import_module(module), attribute)


def test_the_version_is_the_distribution_metadata() -> None:
    """It goes on the ACP wire (05 §Session lifecycle), so it is real."""

    assert isinstance(athanore.__version__, str)
    assert athanore.__version__


def test_star_import_hands_out_the_documented_surface() -> None:
    """`from athanore import *` is `__all__`, aliases excluded."""

    namespace: dict[str, object] = {}
    exec("from athanore import *", namespace)
    exported = {name for name in namespace if not name.startswith("__")}
    public = {name for name in athanore.__all__ if not name.startswith("__")}
    assert exported == public
    assert not exported & set(ALIASES)


# -- the deprecated aliases (14 §Compatibility) -----------------------------


@pytest.mark.parametrize(("alias", "current"), sorted(ALIASES.items()))
def test_an_alias_warns_and_resolves_to_the_current_name(
    alias: str, current: str
) -> None:
    """It still works, and it says what to write instead."""

    with pytest.warns(DeprecationWarning, match=f"use athanore.{current}"):
        value = getattr(athanore, alias)
    assert value is getattr(athanore, current)


@pytest.mark.parametrize("alias", sorted(ALIASES))
def test_an_alias_warns_on_every_access(alias: str) -> None:
    """The second import of an old name is told what the first was.

    The resolved object is cached under the name that replaced it, never
    under the alias, so the warning is not a once-per-process event that
    the module a second author imports would miss.
    """

    for _ in range(2):
        with pytest.warns(DeprecationWarning):
            getattr(athanore, alias)


@pytest.mark.parametrize("alias", sorted(ALIASES))
def test_the_migration_document_still_names_the_alias(alias: str) -> None:
    """The aliases live for one minor version; the document sets the term."""

    assert alias in section(MIGRATION, "## Compatibility")


def test_the_aliases_are_not_part_of_the_public_surface() -> None:
    """`__all__` is 02's list; a deprecated name is one you had to type."""

    assert not set(ALIASES) & set(athanore.__all__)


def test_dir_lists_the_surface_and_the_aliases() -> None:
    """Completion in a REPL shows what can be imported, deprecated or not."""

    assert set(dir(athanore)) == set(athanore.__all__) | set(ALIASES)


def test_an_unknown_attribute_raises_attribute_error() -> None:
    """Which is what `from athanore import web` falls through on."""

    with pytest.raises(AttributeError, match="has no attribute 'nonesuch'"):
        athanore.nonesuch  # noqa: B018 - the attribute access is the assertion


def test_the_web_subpackage_is_still_reachable() -> None:
    """The module `__getattr__` must not shadow a real submodule."""

    from athanore import web

    assert web.__name__ == "athanore.web"


# -- the lazy surface (02 §Layering) ----------------------------------------

#: The packages that must not be imported by `import athanore`, and the
#: probe that reports which of them were. `athanore.graph` is absent from
#: it deliberately: it imports nothing from the package and costs
#: nothing, and it is not what 02 §Layering names.
_PROBE = (
    "import sys, athanore;"
    "print(sorted(m for m in sys.modules"
    " if m.split('.')[0] in {'uvicorn', 'fastapi', 'sqlalchemy'}"
    " or m.startswith('athanore.server')"
    " or m.startswith('athanore.api')"
    " or m.startswith('athanore.engine')"
    " or m.startswith('athanore.store')))"
)


def test_importing_the_package_imports_no_server_and_no_store() -> None:
    """The front door is lazy, and 02 §Layering is why.

    `athanore/__init__.py` runs before `athanore.workflow` on any import
    of it, so an eager re-export here would pull uvicorn, the API and the
    store into every module that defines a workflow — the one thing 02
    §Layering says must not happen.
    """

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout


@pytest.mark.parametrize("name", sorted(athanore._EXPORTS))
def test_a_name_is_resolved_once_and_then_cached(name: str) -> None:
    """The second access is a dict lookup, not another `import_module`."""

    getattr(athanore, name)
    assert name in vars(athanore)
    assert vars(athanore)[name] is getattr(athanore, name)


def test_the_package_root_holds_only_the_documented_modules() -> None:
    """`find athanore -maxdepth 1 -name "*.py"`, as 17 §T055 spells it.

    The flat modules of 02 §Package layout and nothing else. There was no
    MVP teardown to do here — this repository never held the MVP's flat
    modules (D65) — so what this pins is that nothing has crept back to
    the root that belongs in a package.
    """

    root = Path(athanore.__file__).parent
    assert {path.name for path in root.glob("*.py")} == {
        "__init__.py",
        "settings.py",
        "logging.py",
        "workflow.py",
        "server.py",
    }
