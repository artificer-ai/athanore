"""What the build workflows have in common, and nothing that only one has.

`feature`, `quick` and `chat` all reach the same sandbox — the checkout,
the worktrees under it, `scripts/agent.sh`, the gate — and `feature` and
`quick` run the same deterministic steps between their model seats. That
is what lives here: :mod:`.sandbox` (the paths and the git/gh helpers),
:mod:`.steps` (prepare, implement, gate, publish, merge, as functions a
node calls and routes on), :mod:`.agents` (the base class every seat in
the container extends) and :mod:`.models` (the implementer's report,
which the steps read). A seat's prompt, a verdict model, a pane on the
run page belong to the workflow that uses them, not here.

Imports point one way: a workflow package imports this, this imports
none of them, and no workflow imports another. That is what keeps
`quick` from being a dependency of `feature`'s internals, and what
keeps the panes `feature` declares out of `quick`.

One consequence for the live reload (22 §Reloading a module): reloading
`workflows.feature:wf` purges `workflows.feature.*` and re-imports it,
and this package is outside that subtree, so an edit here is picked up
by a restart of the server and not by a reload of one workflow.
"""

from __future__ import annotations

__all__ = ["__doc__"]
