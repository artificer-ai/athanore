"""Athanore: code-defined AI agent workflows over the Agent Client Protocol.

Almost empty. The packages of `docs/v1/02-architecture.md` §Package
layout arrive in T003, and the public surface of §Public API surface is
assembled in T055.

The one name here is :data:`__version__`, and it is here because it goes
on the wire: an ACP client sends its implementation name and version in
`initialize`, and 20 §Checked and found sound requires that to be the
real one (05 §Session lifecycle). It is read from the installed
distribution's metadata rather than written twice, so `pyproject.toml`
stays the single place a release number is edited.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("athanore")
except PackageNotFoundError:  # pragma: no cover - a source tree, not installed
    # Running from a checkout that was never installed. An agent still
    # gets a truthful answer: "we do not know", not a number we made up.
    __version__ = "0+unknown"

__all__ = ["__version__"]
