#!/usr/bin/env python
"""Write the OpenAPI document of `create_app()` to the committed snapshot.

One wire contract (02): OpenAPI is generated from the code and the SPA's
TypeScript client from OpenAPI, both committed, so a change to either
shows up as a diff. `pnpm -C web gen` runs this script and then the
codegen; CI's `contract` job runs both and fails on a tree the two left
dirty.

The rendering is `sort_keys=True, indent=2` with a trailing newline.
Deterministic output is the whole point: a dict ordering that varied
between runs would make the freshness check flap.
"""

from __future__ import annotations

import json
from pathlib import Path

from athanore.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "snapshots" / "openapi.json"


def render() -> str:
    """The exact text of the snapshot for the app as it stands."""
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(render(), encoding="utf-8")
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
