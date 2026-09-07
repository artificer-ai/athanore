"""Athanore: code-defined AI agent workflows over the Agent Client Protocol.

The package's front door: the names of `docs/v1/02-architecture.md`
§Public API, and nothing else. An author writes

.. code-block:: python

    from athanore import Workflow, Pool, human_input, ACPAgent

and never has to know which module any of them lives in.

**Every name is resolved lazily**, through a module ``__getattr__`` (PEP
562), and that is a layering decision rather than a micro-optimisation.
02 §Layering requires that "the module an author defines a workflow in
never pulls uvicorn, the API and the store in behind it" — and this
module runs *before* :mod:`athanore.workflow` on any import of it, so an
eager ``from athanore.server import Server`` here would break that
promise for every workflow module in existence. ``Pool`` would do the
same to the store. Resolved on first attribute access instead, the
promise holds: importing ``athanore`` costs one dict and one
``importlib.metadata`` read, and each name costs its own module the
moment it is asked for and never again (:data:`_EXPORTS`, which caches
into the module globals).

:data:`_DEPRECATED` is 14 §Compatibility's other half. ``AthanoreWorkflow``,
``AthanoreAgent``, ``AthanoreACPAgent`` and ``AthanoreServer`` were the
MVP's names; they go on working here for one minor version, and every
access warns with the name that replaced it. They are deliberately *not*
in :data:`__all__`: a ``from athanore import *`` should hand out the v1
surface, and a deprecated name is one you have to have typed.

:data:`__version__` is the one eager name, and it is here because it goes
on the wire: an ACP client sends its implementation name and version in
`initialize`, and 20 §Checked and found sound requires that to be the
real one (05 §Session lifecycle). It is read from the installed
distribution's metadata rather than written twice, so `pyproject.toml`
stays the single place a release number is edited.
"""

from __future__ import annotations

import warnings
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # The same names :data:`_EXPORTS` resolves at runtime, declared for a
    # type checker and an editor — neither of which can follow a
    # ``__getattr__``. Kept beside the table below, because a name in one
    # and not the other is a name that either does not type or does not
    # import, and `tests/test_public_api.py` asserts both directions.
    from athanore.agents.acp import ACPAgent
    from athanore.agents.base import Agent, AgentError, AgentResult
    from athanore.engine import NonRetryable, Pool
    from athanore.engine.context import current_task, maybe_current_task
    from athanore.graph import GraphError
    from athanore.plugins.context import PluginContext
    from athanore.plugins.decl import PluginError
    from athanore.requests.human import human_input
    from athanore.server import Server
    from athanore.workflow import Workflow

try:
    __version__ = version("athanore")
except PackageNotFoundError:  # pragma: no cover - a source tree, not installed
    # Running from a checkout that was never installed. An agent still
    # gets a truthful answer: "we do not know", not a number we made up.
    __version__ = "0+unknown"

#: Every public name, and the module it is defined in. The whole of 02
#: §Public API in one table, which is what makes it checkable against the
#: document rather than against four scattered import lines.
_EXPORTS: dict[str, tuple[str, str]] = {
    # graph + capacity
    "Workflow": ("athanore.workflow", "Workflow"),
    "Pool": ("athanore.engine", "Pool"),
    # failure-policy exceptions (04)
    "GraphError": ("athanore.graph", "GraphError"),
    "NonRetryable": ("athanore.engine", "NonRetryable"),
    # what a node body reaches for
    "human_input": ("athanore.requests.human", "human_input"),
    "current_task": ("athanore.engine.context", "current_task"),
    "maybe_current_task": ("athanore.engine.context", "maybe_current_task"),
    # agents (05)
    "Agent": ("athanore.agents.base", "Agent"),
    "ACPAgent": ("athanore.agents.acp", "ACPAgent"),
    "AgentResult": ("athanore.agents.base", "AgentResult"),
    "AgentError": ("athanore.agents.base", "AgentError"),
    # plugin handlers (09)
    "PluginContext": ("athanore.plugins.context", "PluginContext"),
    "PluginError": ("athanore.plugins.decl", "PluginError"),
    # programmatic host (04)
    "Server": ("athanore.server", "Server"),
}

#: The MVP's names, and what each one is now (14 §Compatibility). Kept for
#: one minor version, warned on at every access — not once per process:
#: the alias is never cached into the globals, so the second import of it
#: is told the same thing as the first.
_DEPRECATED: dict[str, str] = {
    "AthanoreWorkflow": "Workflow",
    "AthanoreAgent": "Agent",
    "AthanoreACPAgent": "ACPAgent",
    "AthanoreServer": "Server",
}

__all__ = [
    "ACPAgent",
    "Agent",
    "AgentError",
    "AgentResult",
    "GraphError",
    "NonRetryable",
    "PluginContext",
    "PluginError",
    "Pool",
    "Server",
    "Workflow",
    "__version__",
    "current_task",
    "human_input",
    "maybe_current_task",
]


def __getattr__(name: str) -> Any:
    """Resolve one public name, importing the module it lives in.

    A deprecated alias warns and then resolves the name that replaced it;
    anything else raises :exc:`AttributeError`, which is what ``from
    athanore import web`` relies on to fall through to the submodule.
    """

    target = _DEPRECATED.get(name)
    if target is not None:
        warnings.warn(
            f"athanore.{name} is deprecated and will be removed in the next "
            f"minor version; use athanore.{target} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        name = target
    where = _EXPORTS.get(name)
    if where is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = where
    value = getattr(import_module(module), attribute)
    # Cached under the *canonical* name only: the next `Workflow` is a
    # dict lookup, and the next `AthanoreWorkflow` still warns.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """The public surface plus the deprecated aliases, for completion."""

    return sorted([*__all__, *_DEPRECATED])
