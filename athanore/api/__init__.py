"""The HTTP + SSE API."""

from __future__ import annotations

from importlib.metadata import version as _distribution_version

#: The installed distribution version. `/api/health` and `/api/me` report
#: it, and it is the OpenAPI document's version too: the API is versioned
#: by the package version (08 §Versioning).
#:
#: It lives on the package rather than in :mod:`athanore.api.app` because
#: the routers report it and `app` imports the routers. A constant every
#: router reads has to sit where nothing imports back.
VERSION = _distribution_version("athanore")

__all__ = ["VERSION"]
