"""The registrar port: how the API adds, reloads and removes a workflow
on the server that built it (22 §Wire).

``POST``, ``PUT`` and ``DELETE /api/workflows`` are the wire for the
three live verbs of 22 §Server surface, and those verbs are the
composition root's — :class:`athanore.server.Server` owns the engine,
the plugin host and the loader, and sequences what each does. The API
sits below the server (02 §Layering: nothing may import it back), so it
cannot name the class. It names this protocol instead, the server
implements it and hands itself to :func:`athanore.api.app.create_app`
beside the engine and the store, and the router calls what it was
given. An application built without one — the OpenAPI dump, a test that
wants none — answers the three routes ``503 registration_unavailable``.

The port is deliberately the router's vocabulary rather than the
server's: the wire carries a *target string* and a name, not a
``Workflow`` object, so the two ``*_target`` methods take the string,
load it and hand the result to the ordinary verb — which is where the
checks the router must not repeat (the loaded workflow's name against
the URL's, a pool that exists) belong. ``remove`` and ``targets`` have
the server's own shape already.

Every refusal a method raises is one of the loader's or the server's
own, untranslated: :class:`~athanore.plugins.discovery.LoadError`
naming its stage (``conflict`` set on the two that are the wire's
409), :class:`~athanore.plugins.discovery.UnknownPool`, ``ValueError``
for a pool move with attempts in flight, and
:class:`~athanore.plugins.persist.PersistError` for a row that could
not be written. The router maps them; the port does not know what an
HTTP status is.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from athanore.plugins.discovery import Registered, RemovedWorkflow

__all__ = ["WorkflowRegistrar"]


@runtime_checkable
class WorkflowRegistrar(Protocol):
    """What the workflows router needs of the host it serves (22 §Wire)."""

    async def add_target(
        self, target: str, pool: str | None, *, persist: bool
    ) -> Registered:
        """Load ``target`` and register it (``POST /api/workflows``).

        ``pool`` is a pool name the engine must already have, or ``None``
        for the default binding. With ``persist`` the row is written
        before anything is mutated (22 §Persistence).
        """
        ...

    async def reload_target(
        self, name: str, target: str | None, pool: str | None, *, persist: bool
    ) -> Registered:
        """Load ``target`` — or ``name``'s recorded one — and replace ``name``.

        ``PUT /api/workflows/{name}``. A ``target`` of ``None`` re-resolves
        the registration's recorded target, and is a ``LoadError`` of
        stage ``target`` when it has none. A target whose workflow is not
        ``name`` is a ``LoadError`` with ``conflict`` set (22 §Reloading a
        module). ``pool`` of ``None`` keeps the binding the name has.
        """
        ...

    async def remove(self, name: str, *, persist: bool = False) -> RemovedWorkflow:
        """Drop the workflow ``name`` (``DELETE /api/workflows/{name}``).

        ``task_ids`` on the result are the attempts that were interrupted
        (22 §Remove). With ``persist`` the row is removed first, and a
        name with no row is not an error.
        """
        ...

    @property
    def targets(self) -> Mapping[str, str | None]:
        """The target each registered workflow was loaded from.

        ``None`` for a programmatic registration (22 §Terms); what
        ``WorkflowOut.target`` reports.
        """
        ...
