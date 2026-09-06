"""Pure graph DSL: signature parsing, validation, and the builder.

Four modules: ``model`` (the frozen ``Graph`` and ``Node``), ``builder``
(the ``@node`` decorator and signature parsing), ``validate``
(``finalize``), and ``json`` (``jsonable``). Nothing here imports the
rest of ``athanore`` — import-linter enforces it.
"""

from athanore.graph.builder import (
    EdgeRef,
    GraphBuilder,
    GraphError,
    Transition,
    parse_signature,
)
from athanore.graph.json import jsonable
from athanore.graph.model import Graph, Node
from athanore.graph.validate import finalize

#: Deprecated alias for :class:`GraphBuilder`, kept for the MVP's name.
#: ``athanore.Workflow`` (T020) is the object authors actually use.
AthanoreWorkflow = GraphBuilder

__all__ = [
    "AthanoreWorkflow",
    "EdgeRef",
    "Graph",
    "GraphBuilder",
    "GraphError",
    "Node",
    "Transition",
    "finalize",
    "jsonable",
    "parse_signature",
]
