"""The user-facing ``Workflow`` object.

This alias is a placeholder: the real ``Workflow`` class (which composes
the pure graph builder with the plugin declarations) arrives in T020.
Until then ``Workflow`` is the graph builder itself, and this module is
the one place allowed to import both ``athanore.graph`` and
``athanore.plugins.decl`` once the latter exists.
"""

from athanore.graph import AthanoreWorkflow

Workflow = AthanoreWorkflow
