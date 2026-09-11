"""Writing a registration down: the ``[workflows.<name>]`` rows of
``athanore.toml`` (22 §Persistence).

A live registration survives a restart only if it is a row with a
``target`` in the operator's ``athanore.toml``, and the server writes
that row only when asked to (``persist=True``; D220). This is the one
module in ``athanore/`` that imports ``tomlkit`` (D228), and it does one
job with it: editing that file **in place** so that every other byte —
the operator's comments, the key order, the other rows' formatting, the
``[pools]`` table — survives. The standard library reads TOML and does
not write it, and a writer that dropped the comments would be editing a
file the operator no longer recognises.

Two functions and one exception, and nothing about *what* is written
is decided here: the server decides when a row is written (after every
validation, before anything is mutated) and what it says; this module
puts it on disk. It never opens a ``.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import InlineTable, Table

__all__ = ["PersistError", "remove_row", "write_row"]

#: The table the rows live in (02 §``athanore.toml`` layout).
TABLE = "workflows"


class PersistError(Exception):
    """``athanore.toml`` could not be read, parsed or written.

    ``path`` is the file and ``detail`` the underlying error's text; the
    API answers ``500 persist_failed {path, detail}`` with them (22
    §Wire). Raised before anything is mutated, so a write that fails
    leaves the server exactly as it was.
    """

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"{path} could not be updated: {detail}")
        self.path = path
        self.detail = detail


def write_row(path: Path, name: str, target: str, pool: str | None) -> None:
    """Write ``[workflows.<name>] = {target, pool?}`` to ``path``.

    The row is replaced whole when the name already has one, so a
    ``pool`` this call did not give is dropped from it: the row is the
    registration the caller asked for, and a default-pool workflow stays
    on the default pool if ``workers`` changes (22 §Persistence). A
    missing file is created holding the one table; a file with no
    ``[workflows]`` table gains one after its existing content.
    """

    document = _read(path)
    table = document.get(TABLE)
    if table is None:
        table = tomlkit.table()
        document[TABLE] = table
    elif not isinstance(table, Table):
        raise PersistError(path, f"`[{TABLE}]` is not a table")
    table[name] = _row(target, pool)
    _write(path, document)


def remove_row(path: Path, name: str) -> bool:
    """Delete ``[workflows.<name>]`` from ``path``; whether there was one.

    A no-op — no write at all — when the file or the row is absent: the
    state asked for is the state that results (22 §Persistence). An
    emptied ``[workflows]`` table is left in place; it is the operator's
    line, not this module's.
    """

    if not path.exists():
        return False
    document = _read(path)
    table = document.get(TABLE)
    if not isinstance(table, Table) or name not in table:
        return False
    del table[name]
    _write(path, document)
    return True


def _row(target: str, pool: str | None) -> InlineTable:
    """``{ target = "…", pool = "…" }``, spelled as 22's example spells it.

    Built by parsing rather than by assembling items, because tomlkit's
    ``inline_table()`` renders without the spaces the operator's own
    rows have, and the row should read like the ones beside it. The
    strings are escaped by tomlkit, so a path with a quote in it is a
    valid value rather than a broken file.
    """

    pairs = [f"target = {tomlkit.string(target).as_string()}"]
    if pool is not None:
        pairs.append(f"pool = {tomlkit.string(pool).as_string()}")
    return cast(InlineTable, tomlkit.value("{ " + ", ".join(pairs) + " }"))


def _read(path: Path) -> tomlkit.TOMLDocument:
    """The file as a document, or an empty one when it does not exist."""

    if not path.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, TOMLKitError) as exc:
        raise PersistError(path, str(exc)) from exc


def _write(path: Path, document: tomlkit.TOMLDocument) -> None:
    """Write ``document`` back in place.

    A plain ``write_text`` — an in-place edit of the operator's file, not
    a rename over it — so its mode and ownership are kept.
    """

    try:
        path.write_text(tomlkit.dumps(document), encoding="utf-8")
    except OSError as exc:
        raise PersistError(path, str(exc)) from exc
