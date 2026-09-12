# MIT license — the LICENSE file, the package metadata, and the README

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `AGENTS.md` §Quality bar (what lands is what runs in a
release — a license is release metadata, so it is declared where the
build reads it, not only dropped in a file), §Current state of the tree
and §Landing a change (branch, PR, CI green, merge commit), §Commands
(`./scripts/test.sh` is the gate, D74; `README.md` is built or tested by
it, so this change runs it), §Conventions (no attribution lines: the
copyright holder named in `LICENSE` is the operator, which is the same
fact stated once more); `docs/v1/13-testing.md` §CI (the `package` job
and `scripts/check_wheel.py`, which is where "the wheel carries X" is
already proved); D178 (a check only CI runs is a check that never runs —
which is why the wheel check below is added to the script the gate runs
and not left as a one-off `unzip -l`).

Nothing in `docs/v1/` specifies a license, and nothing in it changes.
The request is the whole spec, and this plan pins the few choices it
leaves open.

## What this change is

Athanore is released under the MIT license. Four things say so, and they
are the four things a reader, PyPI, `pip`, and GitHub each look at:

1. **`LICENSE`** at the repository root: the standard MIT text, copyright
   `(c) 2026 Scott Russell`.
2. **`pyproject.toml`** declares it the way hatchling and PyPI read it:
   `license = "MIT"` — the PEP 639 SPDX expression, a plain string, not
   the deprecated `{ file = ... }` table — and the classifier
   `License :: OSI Approved :: MIT License`.
3. **`README.md`** carries an MIT badge as the fifth badge under the
   title, and one line under *Documentation* that says the license and
   points at the file.
4. **`scripts/check_wheel.py`** proves the built wheel carries the file.
   The request says "hatchling then includes LICENSE in the sdist and
   wheel automatically — check that it does". It does (verified while
   planning, see *Facts checked* below), and the check is written into
   the gate's `package` step so it stays true, rather than performed
   once at a keyboard and forgotten.

Nothing else. No SPDX header comments in source files, no `docs/v1/`
change, no `NOTICE`, no `COPYING`, no per-package license for `web/` or
`examples/` (they are in this repository and the root file covers them).

## Facts checked while planning

Read these as settled; do not re-derive them.

- `uv build` resolves hatchling fresh from the build-system table (it is
  not pinned in `uv.lock`). Today that is **hatchling 1.32.0**. A scratch
  project with `license = "MIT"`, the classifier, and a root `LICENSE`
  built with it, without warnings, and produced:
  - the sdist with `<name>-<version>/LICENSE` at its root;
  - the wheel with **`<name>-<version>.dist-info/licenses/LICENSE`**;
  - `METADATA` at `Metadata-Version: 2.5` carrying
    `License-Expression: MIT`, `License-File: LICENSE`, and
    `Classifier: License :: OSI Approved :: MIT License`.

  This is hatchling's default `license-files` glob (`LICEN[CS]E*`,
  `COPYING*`, `NOTICE*`, `AUTHORS*`) at work; **no `license-files` key
  is to be added** — the default is the whole point of the request's
  "automatically", and an explicit list is one more thing to keep true.
- The wheel is built *from the sdist* (`pyproject.toml` comment above
  `[tool.hatch.build]`), and hatchling puts `LICENSE` in the sdist by the
  same default, so the file reaches the wheel with no `artifacts` or
  `include` change.
- `README.md` is read by `tests/test_skills.py` only for its fenced code
  blocks (`is_excerpt`, `python_fences`). A badge line and a prose bullet
  touch no fence and break no test. `scripts/gen_skills.py` and
  `scripts/gen_docs.py` do not read the README.
- The existing four badges (`README.md` lines 3–6) are one markdown
  image-link each, one per line, immediately under `# Athanore`, added
  in `7086404`. The Python badge is a shields.io *static* badge
  (`img.shields.io/badge/python-3.11%2B-blue`); the CI and Docs badges
  are GitHub workflow badges; PyPI is `img.shields.io/pypi/v/athanore`.
- `tests/test_ci_workflows.py` already pins facts read out of
  `pyproject.toml` with `tomllib` (`requires-python` at line 95,
  `[tool.hatch.build] artifacts` at line 495, `pip-audit` at line 545).
  That is the file and the shape for pinning the license declaration.
- `scripts/check_wheel.py` `main()` runs
  `require_built_spa → build_distribution → check_wheel_carries_spa →
  clean_install → serving → check_it_serves_the_spa`, each a function
  that `note()`s on success and raises `CheckFailed` with a sentence
  saying what to do about it. The license check is one more of those.
- `LICENSE` at the root is mounted into the container like everything
  else; nothing in `compose.yaml`, `docker/dev/`, `.dockerignore` or
  `.gitignore` excludes it. (Check `.dockerignore` if one exists before
  assuming; at planning time no exclusion matched.)

## Files

| File | Change |
| --- | --- |
| `LICENSE` | **New.** The MIT text below, byte-exact. |
| `pyproject.toml` | `license = "MIT"` and `classifiers = [...]` under `[project]`. |
| `README.md` | A fifth badge under the title; one bullet under *Documentation*. |
| `scripts/check_wheel.py` | One function: the wheel carries `*.dist-info/licenses/LICENSE`; called from `main()` after `check_wheel_carries_spa`. |
| `tests/test_ci_workflows.py` | One test: `LICENSE` exists and `pyproject.toml` declares the expression and the classifier. |

Nothing under `docs/v1/`, `docs/site/`, `skills/`, `web/`, `examples/`
or `athanore/` changes.

## Do

### 1. `LICENSE`

Create it at the repository root, named exactly `LICENSE` (no
extension — that is what GitHub's license detection, hatchling's
default glob and the README link all expect). Contents are the standard
MIT text from opensource.org, with the copyright line as the request
gives it, a single trailing newline, no BOM, LF line endings:

```
MIT License

Copyright (c) 2026 Scott Russell

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Do not reflow it, do not add a title, a header comment or an SPDX line.
The standard text is what GitHub's detector matches on.

### 2. `pyproject.toml`

Under `[project]`, after `requires-python` and before `dependencies`,
add:

```toml
license = "MIT"
classifiers = [
    "License :: OSI Approved :: MIT License",
]
```

- `license` is the SPDX expression **as a bare string** (PEP 639). Not
  `license = { text = "MIT" }` and not `license = { file = "LICENSE" }`:
  both are the deprecated PEP 621 table, and hatchling 1.32 emits
  `License-Expression` only for the string form.
- No `license-files` key: hatchling's default glob finds `LICENSE`, and
  the wheel check in step 4 is what proves it keeps finding it.
- `classifiers` is a new key: the project currently declares none. One
  entry, the OSI classifier the request names, exactly as spelled. PEP
  639 deprecates `License ::` classifiers in favour of the expression but
  does not forbid carrying both, hatchling 1.32 builds them together
  without a warning (checked), and the request asks for both — PyPI's
  sidebar still reads the classifier. Add no other classifiers; that is
  a different change.
- A one-line comment above the pair, in the file's existing voice, is
  fine (the file comments every table it has a reason for). Something
  like: `# MIT (PEP 639). The expression is what hatchling writes as
  License-Expression; the classifier is what PyPI's sidebar reads.
  LICENSE reaches the sdist and the wheel by hatchling's default
  license-files glob, and scripts/check_wheel.py holds it to that.`

`uv sync` will rewrite nothing in `uv.lock` for a metadata-only change
to the root package's `license`/`classifiers` — but run
`uv sync --all-packages --all-groups --all-extras` (or `uv lock
--check`) and commit `uv.lock` **only if** it actually changed. Do not
hand-edit the lock.

### 3. `README.md`

**The badge.** Add a fifth line directly after the Python badge (line 6),
in the same one-badge-per-line shape:

```markdown
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/artificer-ai/athanore/blob/main/LICENSE)
```

- A shields.io **static** badge, the same family as the Python badge
  beside it, and the same `blue`. Not `img.shields.io/github/license/…`:
  that one reads GitHub's license detection, which is empty until this
  change is merged and would render "not identified" on the PR's own
  render of the README. The static badge is right from the first
  commit and has nothing to go stale — the license is not going to
  change out from under it.
- The link is the file on GitHub at `main`, as the request says: an
  absolute URL, not a relative `LICENSE` link, because the badge row is
  read on PyPI too (the README is the package's `readme`) and relative
  links do not resolve there. The screenshot two paragraphs down uses
  `raw.githubusercontent.com/…/main/…` for the same reason.
- Alt text `License: MIT`, matching the `Python 3.11+` alt text's
  "what it says" style.

**The one-line reference.** *Documentation* is the section where the
README already talks about the repository's own files (`docs/site/`,
`skills/README.md`, `AGENTS.md`, `DESIGN.md`), so the line goes there,
as a last bullet in the list's shape — a linked file, a colon-free
sentence about it:

```markdown
- [`LICENSE`](LICENSE) is the MIT license. Athanore is copyright Scott
  Russell and free to use, copy, modify and redistribute under its terms.
```

That is one bullet, wrapped at the README's width. It is the only prose
change. Do not add a `## License` section, do not touch *Install*,
*Repository layout* or *Developing Athanore*, and do not change the
*Repository layout* tree (it lists directories, not files).

### 4. `scripts/check_wheel.py`

Add one step between step 3 (`check_wheel_carries_spa`) and step 4
(`clean_install`), in the file's own style — a module constant, a
function that `note()`s or raises `CheckFailed` with a sentence that
says what to do, and a line in `main()`:

- A constant beside `PACKAGE_DATA`/`INDEX`:

  ```python
  #: Where hatchling puts the root `LICENSE` in the wheel (PEP 639): the
  #: `licenses/` directory of the `.dist-info`, whose name carries the
  #: version, so it is matched by suffix rather than spelled out.
  LICENSE_IN_WHEEL: Final[str] = ".dist-info/licenses/LICENSE"
  ```

- A function `check_wheel_carries_license(wheel: Path) -> None` that
  opens the zip, finds exactly one name ending in `LICENSE_IN_WHEEL`,
  and compares its bytes to `(ROOT / "LICENSE").read_bytes()`. Byte
  equality is the check: a wheel carrying a *different* license text
  than the checkout is the failure a reader would least expect, and it
  is free to assert. Two failure messages, each saying what to do:
  - none found: `"{wheel.name} carries no …/licenses/LICENSE. hatchling
    ships the root LICENSE by its default license-files glob; check that
    the file is still named LICENSE and that pyproject.toml's [project]
    license is still the SPDX string."`
  - bytes differ: `"{name} in {wheel.name} is not the LICENSE in the
    checkout."`

  On success: `note("the wheel carries LICENSE")`. Return nothing —
  `main()` does not need it.

- Call it from `main()` right after `document = check_wheel_carries_spa(wheel)`.

- Update the module docstring's numbered list: step 3 gains a sentence
  ("…and the license file, byte for byte the checkout's `LICENSE`."), or
  becomes 3 and 3a — whichever reads better in the list as written. Also
  amend the closing `note(f"the wheel ships the SPA …")` only if you
  judge the summary line now misleading; leaving it is acceptable.

pyright runs at `standard` over `scripts/` (it is not in the strict
list); ruff runs over it. Keep annotations complete anyway, as the rest
of the file does.

### 5. `tests/test_ci_workflows.py`

Beside `test_the_wheel_is_configured_to_carry_the_spa` (line 486), add
one test in the same shape:

```python
def test_the_package_declares_its_license() -> None:
    """MIT, declared where each reader looks for it.

    `LICENSE` at the root is what GitHub and hatchling's default
    license-files glob read; `[project] license` is the PEP 639 SPDX
    expression hatchling writes as `License-Expression`; the classifier
    is what PyPI's sidebar reads. `scripts/check_wheel.py` proves the
    built wheel carries the file; this names the three lines that make
    it so.
    """
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License\n\nCopyright (c) 2026 Scott Russell\n")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["license"] == "MIT"
    assert "License :: OSI Approved :: MIT License" in pyproject["project"]["classifiers"]
```

The `startswith` on the first two lines is deliberate: it pins the name
and the copyright line without turning the test into a second copy of
the license text.

### 6. Gate, branch, PR

`README.md`, `scripts/` and `tests/` are all built or tested by the
gate, so this change runs it. Run `./scripts/test.sh` in full once
before pushing; the `package` step is the one that exercises step 4
end-to-end (it needs `pnpm -C web build` to have run, which the gate
does in order). While iterating, `./scripts/test.sh -k "license or
wheel or ci_workflows"` narrows pytest, but the package step is not
pytest and only runs in the full gate.

Land it as `AGENTS.md` §Landing a change says: one commit on
`feat/MIT-license`, subject in the style of the README badges commit
(`MIT license: LICENSE file, package metadata, README badge`), plain
body, no attribution lines; push; `gh pr create --fill`; wait for CI;
merge with a merge commit carrying the PR's title and body; delete the
branch.

## Tests

- `tests/test_ci_workflows.py::test_the_package_declares_its_license`
  (new, above).
- `scripts/check_wheel.py` `check_wheel_carries_license` (new), run by
  the gate's `package` step and by CI's `package` job — not a pytest
  test, but the check the request asks for.
- Every existing test and gate step stays green: in particular
  `tests/test_skills.py`'s README fence checks and `mkdocs build
  --strict`, neither of which this change should disturb.

## Choices made here (for the record)

The request says to record nothing in `docs/v1/15-decisions.md` unless
a real choice comes up. Three small ones did; none rises to a D-row —
each is the boring reading of the request, and this file records it.
**Do not add a row.**

1. **The wheel check is durable, not one-off.** "Check that it does" is
   done in `scripts/check_wheel.py` so the gate keeps checking it, for
   D178's reason. The alternative — `uv build` and `unzip -l` once, in
   the PR body — proves it for one hatchling version on one day.
2. **A static shields.io badge**, not the GitHub-license-detection one.
   Reasons in step 3.
3. **The README line lives under *Documentation***, as a list bullet,
   not as a new `## License` section. The request offered both; the
   list already is "the repository's own files, one line each".

## Done

- `LICENSE` exists at the root with the standard MIT text and
  `Copyright (c) 2026 Scott Russell`.
- `pyproject.toml` `[project]` has `license = "MIT"` (a string) and
  `classifiers` containing `License :: OSI Approved :: MIT License`;
  no `license-files` key.
- `README.md` has five badges under the title, the fifth an MIT badge
  linking to `https://github.com/artificer-ai/athanore/blob/main/LICENSE`,
  and one bullet under *Documentation* naming the license.
- `uv build` produces a wheel with `athanore-<version>.dist-info/licenses/LICENSE`
  byte-equal to the root file, and `scripts/check_wheel.py` fails if it
  does not.
- No source file gained a header comment; nothing under `docs/v1/`
  changed; `15-decisions.md` is untouched.
- `./scripts/test.sh` is green locally and CI is green on the PR.
