"""Load a generator from `scripts/`, by path, and run the real one.

`scripts/` is dev machinery rather than a package, so there is no import
to do. Loading the real file is the point: the renderer under test is the
one CI runs, not a copy of it.

`scripts/` goes on `sys.path` before the module is executed, because
`gen_skills.py` and `gen_docs.py` both `import _reference` — the one
place a fact about this package becomes markdown, with those two as its
front ends — and :func:`importlib.util.spec_from_file_location` does not
put a script's own directory on the path the way running it does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def load_script(name: str) -> ModuleType:
    """`scripts/<name>.py`, executed and returned."""

    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    on_path = str(SCRIPTS) in sys.path
    if not on_path:
        sys.path.insert(0, str(SCRIPTS))
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
        if not on_path:
            sys.path.remove(str(SCRIPTS))
    return module
