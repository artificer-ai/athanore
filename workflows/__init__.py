"""Workflows that operate on *this* checkout.

`feature` is the one seat: it takes a request, rewrites it, plans it,
builds it, judges it and lands it on `main`.

`examples/` is what a user copies; this is what maintains the repository.
The two are kept apart because they answer to different rules: an example
is shipped in the `athanore-examples` distribution and may only use the
public API, while these run with the checkout's own paths, its dev stack
and its gate baked in.

Like `compose.yaml`, `docker/` and `scripts/`, this is **dev machinery**:
nothing in `athanore/` may import it, it is outside the uv workspace, and
it is not in the wheel.
"""

from __future__ import annotations

__all__ = ["__doc__"]
