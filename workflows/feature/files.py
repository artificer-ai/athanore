"""A drop box for the run: upload a file from the browser, hand it to an agent.

The gap this closes is the one T080 sat in for hours. Its plan said the
re-import is **blocked until the operator either runs `/design-login` or
places the refreshed files into `docs/v1/design/`** — and "places the
files" meant *be at the machine with a shell*. From a phone on the LAN,
looking at the run that was asking, there was no way to hand it anything.
Now there is: drop the file in the pane, and it is on disk in the
checkout before the next attempt starts.

**Four routes and a `custom` panel**, which is the whole of 09's escape
hatch (§Escape hatch, D183): `assets="./static"` is served at
`/plugins/feature/static/`, the panel names an element, and the element
reaches these routes through `window.athanore.fetch` — bound to
`/api/plugins/feature/`, carrying auth, and refused if it tries to leave
the prefix.

**They are operator routes, and that is not a choice this module makes.**
A plugin gets no auth model of its own (12 §Plugins): `mount` puts every
one of them behind `Depends(operator_auth)`, so on a network bind they
answer 401 like any other operator route, and an agent holding a *task*
token cannot reach them at all. Which is the point — an agent already has
a shell in the checkout; the operator is the one who could not write a
file from a phone.

Two limits worth knowing before wondering why something failed:

- **`.athanore/files/`, not `.athanore/`.** The directory above holds
  `token`, the operator token (12 §Tokens). A file browser rooted there
  would serve it, list it, and let it be overwritten. One subdirectory
  down there is nothing to leak, and containment becomes a single check
  rather than a denylist.
- **1 MiB per upload, by default.** `body_limit` is ASGI middleware that
  bounds *every* request body before routing (08 §Sizes), so a larger
  file is a 413 that never reaches this module. Raise
  `ATHANORE_BODY_LIMIT` if you need to hand over something bigger.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.responses import FileResponse

from athanore import PluginContext, PluginError, Workflow

from .sandbox import CHECKOUT

__all__ = ["FILES", "MAX_NAME", "declare", "safe_name", "safe_path"]

#: Where a dropped file lands. Inside `.athanore/`, which is git-ignored,
#: so nothing dropped here can be committed by accident or dirty the
#: checkout a run is about to branch from — `feature` refuses a dirty
#: tree, and an ignored path never appears in `git status --porcelain`.
FILES = CHECKOUT / ".athanore" / "files"

#: A filename this accepts: no separator, no leading dot, nothing exotic.
#: Traversal is refused by *shape* here and by containment in
#: :func:`safe_path`, because one check that is easy to read and one that
#: is hard to fool are worth more than either alone.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_NAME = 128

#: Everything :func:`safe_name` collapses to a dash on the way in.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_path(name: str) -> Path:
    """:data:`FILES` / ``name``, or raise.

    ``PluginError(400, ...)`` rather than a bare exception: it carries
    the status the refusal is reported with, and the API renders it as
    08 §Conventions' error shape with ``code: "plugin_error"``. Anything
    else a handler raises is a 500 with nothing a client can branch on,
    which for a rejected *file name* is a lie — the operator typed
    something this route will never accept, and that is a 400.
    """

    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_NAME or not NAME.match(cleaned):
        raise PluginError(
            400,
            f"{name!r} is not a usable file name: letters, digits, dot, dash "
            f"and underscore, starting with a letter or digit, at most "
            f"{MAX_NAME} characters",
        )
    resolved = (FILES / cleaned).resolve()
    # Belt and braces: the pattern above already forbids a separator, so
    # this can only fire if `FILES` itself is reached through a symlink.
    # It is the check that does not depend on having got the regex right.
    if resolved.parent != FILES.resolve():
        raise PluginError(400, f"{name!r} resolves outside the drop box")
    return resolved


def safe_name(raw: str) -> str:
    """``raw`` as a name :func:`safe_path` will accept.

    **Uploads are cleaned, not refused.** The names people actually drop
    are `Screenshot 2026-09-10 at 6.21.43 PM.png` and `nocturne (1).css`,
    and both fail :data:`NAME` — spaces, brackets, colons. Rejecting them
    would make the pane useless for the one thing it is for, and asking
    the operator to rename a file before dropping it is asking them to go
    and find a shell, which is what this exists to avoid.

    So the strictness moves: this cleans, and :func:`safe_path` still
    refuses. A name that reaches the listing has been through here, and a
    name that arrives on a *lookup* is one the listing gave out, so both
    ends stay strict without the drop box being precious.

    The extension survives the length cap, because it is the half that
    tells an agent what the file is.
    """

    base = Path(raw).name
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    stem = UNSAFE.sub("-", stem).strip("-._") or "file"
    suffix = UNSAFE.sub("-", suffix).strip("-._")
    room = MAX_NAME - (len(suffix) + 1 if suffix else 0)
    cleaned = stem[:room] + (f".{suffix}" if suffix else "")
    # `NAME` also requires the first character to be alphanumeric, which
    # the strip above does not guarantee for a name that was all dots.
    return cleaned if NAME.match(cleaned) else f"file-{cleaned}"[:MAX_NAME]


def _entry(path: Path) -> dict[str, Any]:
    """One file, as both the table and the element read it.

    ``path`` is checkout-relative and is the whole point of the copy
    button: it is the string an operator pastes into a run's description
    so the agent can open the file. Relative rather than absolute because
    an agent's ``cwd`` *is* the checkout — on both sides of the container
    boundary, which is why `compose.yaml` mounts it at its own host path
    — so the relative form is the one that reads the same everywhere.
    """

    stat = path.stat()
    # Relative when it can be, absolute when it cannot. `FILES` is derived
    # from `CHECKOUT`, so the fallback only fires when something has
    # pointed it elsewhere — and a crash there would be a worse answer
    # than a longer path.
    try:
        shown = str(path.relative_to(CHECKOUT))
    except ValueError:
        shown = str(path)
    return {
        "name": path.name,
        "path": shown,
        "bytes": stat.st_size,
        "modified": int(stat.st_mtime),
    }


def _listing() -> list[dict[str, Any]]:
    """Every file in the drop box, newest first.

    Directories are skipped rather than descended: this is a flat drop
    box, and a tree would need a path shape that :func:`safe_path` exists
    to refuse.
    """

    if not FILES.is_dir():
        return []
    files = [one for one in FILES.iterdir() if one.is_file()]
    return sorted(
        (_entry(one) for one in files), key=lambda e: e["modified"], reverse=True
    )


async def _upload(file: UploadFile) -> dict[str, Any]:
    """Write one uploaded file into the drop box and return its entry.

    An existing name is overwritten, deliberately: the operator is
    handing a file to a run that is waiting for *that name*, and a second
    attempt at the same file should replace the first rather than
    accumulate `nocturne-2.css` for an agent that will never look for it.
    """

    if file.filename is None:
        raise PluginError(400, "the upload carried no file name")
    target = safe_path(safe_name(file.filename))
    FILES.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    return _entry(target)


def _download(name: str) -> FileResponse:
    """Send one file back, as an attachment."""

    path = safe_path(name)
    if not path.is_file():
        raise PluginError(404, f"no file named {name!r} in the drop box")
    return FileResponse(path, filename=path.name)


def _remove(name: str) -> dict[str, Any]:
    """Delete one file. Missing is an error, not a quiet success."""

    path = safe_path(name)
    if not path.is_file():
        raise PluginError(404, f"no file named {name!r} in the drop box")
    path.unlink()
    return {"deleted": path.name}


def declare(wf: Workflow) -> None:
    """Attach the drop box to ``wf``: four routes and the pane.

    **Every handler names ``ctx`` first, and that is load-bearing rather
    than decorative.** `mount` looks for a parameter annotated
    :class:`~athanore.plugins.context.PluginContext`, and *failing that*
    treats the first parameter as the context unless it is called
    ``input`` (`plugins/mount.py`). A handler written as
    ``async def upload(file: UploadFile)`` would therefore have the
    resolved context injected into ``file`` and never see the upload.
    Declaring it is how you opt out of that fallback.

    The panel is `global`: a drop box belongs to the checkout, not to a
    run, and the global slot is "a pane shown when no run is selected"
    (09 §Slots). It refreshes on nothing — the element reloads its own
    listing after every write, and no event in the vocabulary describes a
    file appearing on disk.
    """

    @wf.route("/files")
    async def files_list(ctx: PluginContext) -> list[dict[str, Any]]:
        """Every file in the drop box, newest first."""

        return _listing()

    @wf.route("/files", methods="POST")
    async def files_upload(ctx: PluginContext, file: UploadFile) -> dict[str, Any]:
        """Take one uploaded file into the drop box."""

        return await _upload(file)

    @wf.route("/files/{name}")
    async def files_download(ctx: PluginContext, name: str) -> FileResponse:
        """Send one file back as an attachment."""

        return _download(name)

    @wf.route("/files/{name}", methods="DELETE")
    async def files_delete(ctx: PluginContext, name: str) -> dict[str, Any]:
        """Delete one file."""

        return _remove(name)

    wf.panel(
        "files",
        slot="global",
        kind="custom",
        element="athanore-files",
    )
