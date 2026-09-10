"""Publish the committed OpenAPI document beside the reference that reads it.

`docs/site/src/reference/http-api.md` is generated from
`tests/snapshots/openapi.json` and ends by linking `../openapi.json`, so
the document itself has to be part of the built site: a client author
who wants to generate a client wants the JSON, not a page about it.

It is added here rather than committed a second time under `src/`. The
snapshot is two hundred kilobytes of generated JSON that changes with
every wire change; a copy in the tree would double that diff and add a
way for the two to disagree.

A missing snapshot raises. A site that quietly shipped no `openapi.json`
— with the reference page still linking to it — is worse than a build
that stops.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mkdocs.structure.files import File, Files

#: Where the document is published in the built site, and what
#: `reference/http-api.md` links to from one directory down.
URI = "openapi.json"


def _snapshot(config: Any) -> Path:
    """`tests/snapshots/openapi.json`, found from this config's own path.

    `docs/site/mkdocs.yml` → the checkout root is two directories up, so
    the hook works from any working directory and needs no setting.
    """

    root = Path(config.config_file_path).resolve().parents[2]
    return root / "tests" / "snapshots" / "openapi.json"


def on_files(files: Files, config: Any) -> Files:
    snapshot = _snapshot(config)
    if not snapshot.is_file():
        raise FileNotFoundError(
            f"{snapshot} is missing, so the site would ship no {URI} while "
            f"reference/http-api.md links to it. Run scripts/dump_openapi.py."
        )
    files.append(File.generated(config, URI, abs_src_path=str(snapshot)))
    return files
