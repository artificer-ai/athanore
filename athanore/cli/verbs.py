"""The CLI's verb names, in one place (11 §Verbs).

The set is here rather than in :mod:`athanore.cli` because two modules
need it and neither may wait for the other: the CLI resolves its
bare-workflow alias against it (a first positional that is not a verb and
names a registered workflow is a ``submit``), and
:meth:`athanore.server.Server.register` refuses a workflow whose name
would shadow one — the check has to happen at registration, where the
mistake is made, rather than at the moment somebody types the ambiguous
command.

This module imports nothing, so ``server`` can name it without the CLI's
own dependencies coming with it.
"""

from __future__ import annotations

#: Every verb ``athanore`` answers to (11 §Verbs), including the server
#: verbs of 11 §Server. A workflow may not take one of these names.
RESERVED = frozenset(
    {
        "answer",
        "cancel",
        "db",
        "deny",
        "edit",
        "logs",
        "login",
        "ls",
        "move",
        "open",
        "pause",
        "permit",
        "position",
        "requests",
        "rerun",
        "resume",
        "retry",
        "rm",
        "serve",
        "set-status",
        "show",
        "stream",
        "submit",
        "token",
        "workflows",
    }
)

__all__ = ["RESERVED"]
