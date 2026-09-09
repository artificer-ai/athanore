"""Workflows that operate on *this* checkout.

Two seats over one working tree, and one hands to the other:

- **`planner`** turns a request into a design document under `docs/v1/`, a
  plan file per task under `docs/plans/`, and — once a person has
  approved it — a queue of `feature` runs.
- **`feature`** takes one of those tasks from a branch to `main`.

`examples/` is what a user copies; this is what maintains the repository.
The two are kept apart because they answer to different rules: an example
is shipped in the `athanore-examples` distribution and may only use the
public API, while these run with the checkout's own paths, its dev stack
and its gate baked in.

Like `compose.yaml`, `docker/` and `scripts/`, this is **dev machinery**:
nothing in `athanore/` may import it, it is outside the uv workspace, and
it is not in the wheel.

What both seats share — the checkout's paths, and the git that
answers for it — is :mod:`workflows.checkout`.
"""

from __future__ import annotations

__all__ = ["__doc__"]
