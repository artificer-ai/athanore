"""No path into the specification from the README, the package, or the SPA.

`docs/v1/` is the specification and `docs/plans/` the per-task plans.
Both are for whoever is *building* Athanore, and `AGENTS.md` is the
door to them. The README, every module under `athanore/` and every file
under `web/src/` are read by someone *using* it — `help(athanore)`
shows the package docstring, an editor shows the SPA's docblocks — so
none of them names either tree by path (D219). This is the boundary
D214 (6) draws for the site and D215 (1) for the skills, applied to
three more trees and, as there, checked rather than remembered.

The one exemption is code, not prose: the theme test *reads* the design
system's token sheet to compare it with the stylesheet generated from
it. That dependency is real and the sheet is not moving, so the line is
listed by its exact text and a test asserts it is still there.

A checker that passes everything is the one failure mode this design
cannot survive, so the two constants are exercised against deliberately
wrong text as well as against the trees.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from tests._prose import PLANS, SPEC

ROOT = Path(__file__).resolve().parent.parent

#: Code that reads the specification's design source on purpose, as an
#: exact line: the theme test compares the generated stylesheet with
#: the token sheet it was built from, and the sheet is not moving. A
#: comment is never exempt; a second line here needs a decision (D219).
EXEMPT: Mapping[str, frozenset[str]] = {
    "web/src/styles/theme.test.ts": frozenset(
        {"const SOURCE = resolve(WEB, '../docs/v1/design/nocturne.css')"}
    ),
}


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def package_modules() -> list[Path]:
    return sorted((ROOT / "athanore").rglob("*.py"))


def spa_sources() -> list[Path]:
    return sorted(p for p in (ROOT / "web" / "src").rglob("*") if p.is_file())


def offending_lines(path: Path) -> list[str]:
    """Every line of ``path`` that names either tree and is not exempt."""

    exempt = EXEMPT.get(relative(path), frozenset())
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if (SPEC in line or PLANS in line) and line.strip() not in exempt
    ]


def test_the_readme_names_no_design_document() -> None:
    """The README reaches the specification through `AGENTS.md`, not directly."""

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert SPEC not in text
    assert PLANS not in text


@pytest.mark.parametrize("path", package_modules(), ids=relative)
def test_no_package_module_names_a_design_document(path: Path) -> None:
    """A docstring is what `help()` shows; it stands without a citation."""

    assert not offending_lines(path), relative(path)


@pytest.mark.parametrize("path", spa_sources(), ids=relative)
def test_no_spa_source_names_a_design_document(path: Path) -> None:
    """A docblock stands without a citation; generated files carry none."""

    assert not offending_lines(path), relative(path)


def test_every_exemption_is_still_needed() -> None:
    """An exemption cannot outlive the line it excuses."""

    for name, lines in EXEMPT.items():
        present = {
            line.strip()
            for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        }
        missing = lines - present
        assert not missing, f"{name}: {sorted(missing)}"


# --------------------------------------------------------------------------
# The constants, against text that is deliberately wrong
# --------------------------------------------------------------------------


def test_a_path_into_the_specification_is_caught() -> None:
    assert SPEC in "see `docs/v1/04-engine.md` §Routing"


def test_a_path_into_the_plans_is_caught() -> None:
    assert PLANS in "the plan is `docs/plans/T012-foo.md`"
