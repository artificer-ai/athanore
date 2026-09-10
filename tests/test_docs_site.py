"""The documentation site is generated where it can be, and narrative where it cannot.

`docs/site/` is for someone who has just installed Athanore. The design
documents in `docs/v1/` are the specification, for whoever is building
it, and the site restates none of it (D214). That splits the tree in two
and this suite holds both halves:

- everything with a shape — a default, a name, a signature, a field list,
  a status code, a wire shape — is generated into
  `docs/site/src/reference/` by `scripts/gen_docs.py`, and the committed
  bytes must be what that script writes. This is the OpenAPI snapshot's
  check again (`tests/test_openapi_snapshot.py`) and the skills' check
  again (`tests/test_skills.py`); CI's `contract` job is its other half,
  regenerating and running `git diff --exit-code`;
- every hand-written page is narrative, and the separation is checked
  rather than remembered: no page carries a capitalised RFC 2119
  keyword, no page names `docs/v1`, and every Python example is a module
  that parses. Those three parsers are `tests/_prose.py`, because the
  skills are held to the same rules.

The `mkdocs build --strict` step of `./scripts/test.sh` catches a broken
link and a page nothing links to. What it cannot catch is a page that
builds and says the wrong thing, which is what the rules above are for.

A checker that passes everything is the one failure mode this design
cannot survive, so the parsers below are exercised against deliberately
broken text as well as against the tree.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from athanore.events.names import EventName
from athanore.settings import AthanoreSettings, Retention
from tests._generators import load_script
from tests._prose import SPEC, keywords, python_fences

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs" / "site"
SRC = SITE / "src"
CONFIG = SITE / "mkdocs.yml"
REFERENCE = SRC / "reference"

STALE = (
    "a file under docs/site/src/reference/ is stale. Regenerate it:\n"
    "    uv run scripts/gen_docs.py"
)

#: The five `validation:` keys that make `--strict` worth having, and the
#: level each is raised to. mkdocs' own levels are `warn`, `info` and
#: `ignore`; `strict: true` is what turns a warning into a non-zero exit.
VALIDATION = {
    ("nav", "omitted_files"): "warn",
    ("nav", "not_found"): "warn",
    ("links", "absolute_links"): "warn",
    ("links", "unrecognized_links"): "warn",
    ("links", "anchors"): "warn",
}


# --------------------------------------------------------------------------
# The parsers — the prose rules are `tests/_prose.py`, shared with the skills
# --------------------------------------------------------------------------


def nav_targets(nav: Any) -> list[str]:
    """Every target a nav entry names, sections walked, in order."""

    found: list[str] = []
    if isinstance(nav, str):
        found.append(nav)
    elif isinstance(nav, list):
        for entry in nav:
            found += nav_targets(entry)
    elif isinstance(nav, dict):
        for value in nav.values():
            found += nav_targets(value)
    return found


def pages() -> list[Path]:
    """Every markdown page of the site, generated ones included."""

    return sorted(SRC.rglob("*.md"))


def written_pages() -> list[Path]:
    """The hand-written half: every page that is not under `reference/`."""

    return [path for path in pages() if REFERENCE not in path.parents]


def page_id(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    """`scripts/gen_docs.py`, loaded by path.

    The real file, for the reason `tests/test_skills.py` loads the real
    `gen_skills.py`: the renderer under test is the one CI runs.
    """

    return load_script("gen_docs")


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    """`docs/site/mkdocs.yml`, read with `yaml.safe_load`.

    Which is why the file carries no `!!python/name:` tag: a config only
    mkdocs can parse is a config no test can check.
    """

    loaded = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    path = ROOT / "tests" / "snapshots" / "openapi.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------
# The generated half
# --------------------------------------------------------------------------


def test_every_generated_page_is_one_the_script_writes(
    generator: ModuleType,
) -> None:
    """No page under `reference/` is missing, and none is orphaned."""

    on_disk = {
        path.relative_to(ROOT).as_posix()
        for path in REFERENCE.rglob("*")
        if path.is_file()
    }
    assert on_disk == set(generator.TARGETS), STALE


def test_generated_pages_are_byte_for_byte_what_the_script_writes(
    generator: ModuleType,
) -> None:
    """The freshness check CI runs is `git diff`, so formatting counts."""

    for target in generator.TARGETS:
        assert generator.render(target) == (ROOT / target).read_text(
            encoding="utf-8"
        ), f"{target}: {STALE}"


def test_the_rendering_is_deterministic(generator: ModuleType) -> None:
    """A dict ordering that varied between runs would make the check flap."""

    for target in generator.TARGETS:
        assert generator.render(target) == generator.render(target), target


def test_render_refuses_a_file_it_does_not_own(generator: ModuleType) -> None:
    with pytest.raises(KeyError):
        generator.render("docs/site/src/reference/panes.md")


def test_only_generated_pages_carry_the_marker(generator: ModuleType) -> None:
    """The marker is the one thing that says "do not edit this by hand"."""

    for target in generator.TARGETS:
        first = (ROOT / target).read_text(encoding="utf-8").splitlines()[0]
        assert first == generator.MARKER, target
    for path in written_pages():
        assert generator.MARKER not in path.read_text(encoding="utf-8"), path


def test_the_two_generators_are_two_front_ends_over_one_renderer(
    generator: ModuleType,
) -> None:
    """The skills republish the site's pages rather than frame the same
    bodies a second time: one `_reference` module, disjoint targets, and
    a marker each, so a page says which script wrote it."""

    skills = load_script("gen_skills")
    assert generator.MARKER != skills.MARKER
    assert generator.reference is skills.reference
    assert not set(generator.TARGETS) & set(skills.TARGETS)


# --------------------------------------------------------------------------
# What the generated pages have to cover
# --------------------------------------------------------------------------


def test_every_setting_is_in_the_settings_table() -> None:
    """A field added to the model with no row here would be undocumented."""

    page = (REFERENCE / "settings.md").read_text(encoding="utf-8")
    for name in AthanoreSettings.model_fields:
        assert f"`{name}`" in page, name
    for name in Retention.model_fields:
        assert f"`{name}`" in page, name


def test_every_setting_has_a_description() -> None:
    """The descriptions are the table's last column (D214).

    Without this the table goes quietly blank as fields are added: the
    row appears, the sentence that says what it does does not.
    """

    for model in (AthanoreSettings, Retention):
        for name, field in model.model_fields.items():
            assert (field.description or "").strip(), f"{model.__name__}.{name}"


def test_the_settings_page_carries_no_absolute_path() -> None:
    """`root_path`'s default is `Path.cwd()`.

    Rendering what that returns would put this machine's absolute path
    into a committed file and make the output depend on where it was
    generated, so it is written out in words instead.
    """

    page = (REFERENCE / "settings.md").read_text(encoding="utf-8")
    assert str(ROOT) not in page
    assert "the working directory" in page


def test_the_http_page_names_every_operation_and_every_schema(
    snapshot: dict[str, Any],
) -> None:
    page = (REFERENCE / "http-api.md").read_text(encoding="utf-8")
    for path, item in snapshot["paths"].items():
        for method, operation in item.items():
            assert f"`{method.upper()} {path}`" in page, f"{method} {path}"
            assert operation["operationId"] in page, operation["operationId"]
    for name in snapshot["components"]["schemas"]:
        assert f"### `{name}`" in page, name


def test_the_http_page_links_the_document_it_was_generated_from() -> None:
    """The hook publishes the snapshot at the site root; this is the link."""

    page = (REFERENCE / "http-api.md").read_text(encoding="utf-8")
    assert "(../openapi.json)" in page
    assert (SITE / "hooks" / "openapi.py").is_file()


def test_the_events_page_names_every_event() -> None:
    page = (REFERENCE / "events.md").read_text(encoding="utf-8")
    for member in EventName:
        assert f"`{member.value}`" in page, member.value


# --------------------------------------------------------------------------
# The hand-written half: the audience separation, machine-checked
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", pages(), ids=page_id)
def test_no_page_specifies_anything(path: Path) -> None:
    """RFC 2119's keywords belong to the specification, not to a guide."""

    found = keywords(path.read_text(encoding="utf-8"))
    assert not found, f"{page_id(path)} carries {sorted(set(found))}"


@pytest.mark.parametrize("path", pages(), ids=page_id)
def test_no_page_names_the_design_documents(path: Path) -> None:
    """One nav entry in `mkdocs.yml` links them, and nothing else does.

    A site that cited the specification would be inviting a reader into
    a second document written for somebody else, and a page that
    paraphrased one would become a second specification that drifts.
    """

    assert SPEC not in path.read_text(encoding="utf-8"), page_id(path)


@pytest.mark.parametrize("path", pages(), ids=page_id)
def test_every_python_example_parses(path: Path) -> None:
    """An example nothing runs is one nothing keeps honest.

    Every ` ```python ` fence is a complete module; a body that is not
    worth showing is `...` rather than prose inside code.
    """

    for index, block in enumerate(python_fences(path.read_text(encoding="utf-8"))):
        try:
            ast.parse(block)
        except SyntaxError as exc:  # pragma: no cover - the assert reports it
            pytest.fail(f"{page_id(path)} python fence {index}: {exc}")


def test_the_pages_actually_carry_examples() -> None:
    """The checker above must have work to do."""

    total = sum(
        len(python_fences(path.read_text(encoding="utf-8"))) for path in written_pages()
    )
    assert total >= 10, total


# --------------------------------------------------------------------------
# The config
# --------------------------------------------------------------------------


def test_the_config_says_where_the_site_is(config: dict[str, Any]) -> None:
    assert config["docs_dir"] == "src"
    assert config["site_dir"] == "build"
    assert config["site_name"] == "Athanore"


def test_the_build_is_strict_and_validates(config: dict[str, Any]) -> None:
    """`strict: true` is what makes the gate's `docs` step mean something.

    Without it the five checks below are lines in a build log, and a
    broken link ships.
    """

    assert config["strict"] is True
    validation = config["validation"]
    for (group, key), level in VALIDATION.items():
        assert validation[group][key] == level, f"{group}.{key}"


def test_the_gate_builds_the_site() -> None:
    """`./scripts/test.sh` is the definition of green (D74, D178).

    This repository has no runner, so a docs build only `ci.yml`
    performs is one that first goes red in front of a reader.
    """

    gate = (ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")
    assert "mkdocs build --strict -f docs/site/mkdocs.yml" in gate


def test_the_site_has_a_wrapper_of_its_own() -> None:
    """Every recurring job in `scripts/` has one, and the site is one.

    `./scripts/docs.sh` serves it on `127.0.0.1:8000` and
    `./scripts/docs.sh build` builds it, from the host or from inside the
    container like `run.sh` and `test.sh` — which is why it sources
    `_lib.sh` and dispatches on `in_container` rather than assuming a
    side. `AGENTS.md` names it beside the others so it is findable.
    """

    wrapper = ROOT / "scripts" / "docs.sh"
    assert wrapper.stat().st_mode & 0o111, "scripts/docs.sh is not executable"

    text = wrapper.read_text(encoding="utf-8")
    assert "_lib.sh" in text
    assert "in_container" in text
    assert "mkdocs serve" in text
    assert "mkdocs build --strict" in text
    assert "8000" in text

    for named_in in (ROOT / "AGENTS.md", ROOT / "README.md"):
        assert "./scripts/docs.sh" in named_in.read_text(encoding="utf-8"), named_in


def test_every_page_is_in_the_nav_exactly_once(config: dict[str, Any]) -> None:
    """`nav.omitted_files` catches the same thing at build time.

    It names the count and not the file, and it runs in a step that only
    happens when the whole site builds; this runs in the pytest step with
    the rest of this suite and says which page it was.
    """

    targets = [target for target in nav_targets(config["nav"]) if "://" not in target]
    assert sorted(targets) == sorted(page_id(path) for path in pages())
    assert len(targets) == len(set(targets))


def test_every_nav_entry_resolves(config: dict[str, Any]) -> None:
    for target in nav_targets(config["nav"]):
        if "://" in target:
            continue
        assert (SRC / target).is_file(), target


def test_the_design_documents_are_linked_from_the_nav_and_nowhere_else(
    config: dict[str, Any],
) -> None:
    """The one place the specification is named (D214)."""

    external = [target for target in nav_targets(config["nav"]) if "://" in target]
    assert any(target.endswith(SPEC) for target in external), external


# --------------------------------------------------------------------------
# The checkers, against text that is deliberately wrong
# --------------------------------------------------------------------------


def test_a_specifying_page_is_caught() -> None:
    assert keywords("A node body MUST NOT retry an agent call.") == ["MUST NOT"]
    assert keywords("The engine SHOULD retry, and MAY give up.") == ["SHOULD", "MAY"]


def test_ordinary_prose_is_not_mistaken_for_a_keyword() -> None:
    """The rule is about the capitalised form, and only that."""

    assert keywords("A body may raise, and should say why. Must it? No.") == []
    assert keywords("MUSTARD, SHOULDER, MAYBE") == []


def test_a_link_into_the_specification_is_caught() -> None:
    assert SPEC in "see `docs/v1/04-engine.md` for the routing table"


def test_a_python_fence_that_does_not_parse_is_caught() -> None:
    text = "prose\n\n```python\nasync def n(\n```\n"
    assert python_fences(text) == ["async def n("]
    with pytest.raises(SyntaxError):
        ast.parse(python_fences(text)[0])


def test_a_shell_fence_is_not_a_python_fence() -> None:
    text = "```sh\nathanore serve hello.py:wf\n```\n"
    assert python_fences(text) == []


def test_a_page_missing_from_the_nav_is_caught(config: dict[str, Any]) -> None:
    """The assertion is a set comparison, so this is the shape of a miss."""

    targets = {target for target in nav_targets(config["nav"]) if "://" not in target}
    assert "guide/invented.md" not in targets
    assert not (SRC / "guide" / "invented.md").exists()


def test_nav_sections_are_walked() -> None:
    """A page nested under a section heading still counts as navigable."""

    nav = [{"Home": "index.md"}, {"Guide": [{"One": "guide/one.md"}]}, "loose.md"]
    assert nav_targets(nav) == ["index.md", "guide/one.md", "loose.md"]
