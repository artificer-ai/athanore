"""Queueing the `feature` runs a plan produced, over the wire.

Not `dispatch.py`, which is the node that calls it: a submodule and a
node body of the same name are one name, and the package's is whichever
was bound last.

**One wire contract.** A node body reaches the store through
:class:`~athanore.engine.context.TaskContext`, and `services` deliberately
carries no `ops`: bodies do not reach across into other runs. Submitting
a run is an operator action, and the operator's way in is the HTTP API —
the same `POST /api/workflows/{name}/runs` the CLI and the SPA use (08).
So this is an ordinary client of the server the workflow is running
inside, and a run it queues is indistinguishable from one a person typed.

**The bind decides the credential.** On a loopback bind there is no
operator auth at all (12 §Local first), which is what `python -m
workflows` gives you; behind anything else the token is in
`.athanore/token`, which is where the server itself reads it from. Read
from the file rather than from `athanore.settings`, because these
workflows are dev machinery that already reads this checkout with git and
have no business importing the package's internals.

**Retries belong to the engine.** The client gets httpx's connection-level
retries and nothing else: a submission that was refused is refused, and
rule 3 makes the node body decide what that means.
"""

from __future__ import annotations

import httpx

from workflows.checkout import CHECKOUT

from .models import PlannedTask

__all__ = ["FEATURE_WORKFLOW", "submit_feature"]

#: The workflow a planned task becomes a run of. Named once: it is the
#: registered name in :mod:`workflows.__main__`, and a typo here would
#: queue nothing and say so only at the far end.
FEATURE_WORKFLOW = "feature"

#: The operator token file (12 §Tokens). Git-ignored, and absent on the
#: loopback bind that needs no operator auth.
TOKEN_FILE = CHECKOUT / ".athanore" / "token"

#: How long a submission may take. It is one insert and a `notify()`, so
#: a wait longer than this is a server that is not answering rather than
#: a slow queue.
SUBMIT_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    """`Authorization: Bearer …` when there is a token, otherwise nothing."""

    if not TOKEN_FILE.is_file():
        return {}
    token = TOKEN_FILE.read_text().strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


async def submit_feature(api_base: str, task: PlannedTask, *, document: str) -> str:
    """Queue a `feature` run for ``task`` and return its run id.

    The title is the task id and nothing else: it becomes the branch
    (`feat/T080`) and the prefix of the merge commit subject, which is
    how this repository's history is read. The description is the brief,
    with the design document named — `feature` finds the plan file itself
    from the title, at the moment the implementer needs it.
    """

    description = (
        f"{task.title}\n\n{task.description.strip()}\n\n"
        f"The design this implements is `{document}`. Read it, and the "
        "sections of `docs/v1/` it cites, before you write a line."
    )
    async with httpx.AsyncClient(
        base_url=api_base, timeout=SUBMIT_TIMEOUT, headers=_headers()
    ) as client:
        response = await client.post(
            f"/api/workflows/{FEATURE_WORKFLOW}/runs",
            json={"title": task.id, "description": description},
        )
        response.raise_for_status()
        return str(response.json()["run_id"])
