"""The skills under `skills/` stand alone, and every link in one resolves.

A skill is installed into somebody else's coding agent, working on their
own project, with no checkout of this repository on disk. That splits
`skills/` in two and this suite holds both halves:

- a `SKILL.md` is hand-written and is the minimum to act. It names no
  design document and — the web skill excepted — no path in this
  checkout, carries no RFC 2119 keyword, keeps under 150 lines, names
  every file in its own `reference/`, and every code fence in it is an
  excerpt of a file in this tree, with every Python fence a module that
  parses;
- everything else is the documentation site's pages, republished into
  the skill's `reference/` by `scripts/gen_skills.py` with their links
  rewritten to resolve inside the skill, and the committed bytes must be
  what that script writes.

The second half is the OpenAPI snapshot's check again
(`tests/test_openapi_snapshot.py`), and CI's `contract` job is its other
half: it regenerates and runs `git diff --exit-code` over `skills/`. The
first half is the one that cannot be generated, and holding it to a few
machine-checkable rules is what keeps it honest.

A checker that passes everything is the one failure mode this design
cannot survive, so the parsers below are exercised against deliberately
broken text as well as against the tree.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests._generators import load_script
from tests._prose import SPEC, keywords, python_fences

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
SITE = ROOT / "docs" / "site" / "src"

#: The five surfaces, and the whole of `skills/` besides its README.
NAMES = (
    "athanore-workflows",
    "athanore-plugins",
    "athanore-api",
    "athanore-cli",
    "athanore-web",
)

#: The four whose reader has no checkout. `athanore-web` is for a
#: contributor to the SPA, which exists nowhere but here, so it alone
#: may point into the tree.
PORTABLE = tuple(name for name in NAMES if name != "athanore-web")

#: The cap on a `SKILL.md`, frontmatter included. "Keep them short" is
#: a rule that only holds if something holds it.
MAX_LINES = 150

STALE = (
    "a file under skills/*/reference/ is stale. Regenerate it:\n"
    "    uv run scripts/gen_skills.py"
)

#: What the first segment of a path citation may be: the top-level
#: directories of the checkout and the root files a skill could point at.
#: An inline-code span that starts with anything else is code rather than
#: a path — `wf.node(...)`, `run.completed`, `/api/health`,
#: `reference/events.md` — and is deliberately not checked as one, so
#: that code in prose needs no escape.
ROOTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "athanore",
    "compose.yaml",
    "docs",
    "examples",
    "pyproject.toml",
    "scripts",
    "skills",
    "tests",
    "web",
    "workflows",
)

#: One inline-code span. Fenced blocks are removed before this is applied.
SPAN = re.compile(r"`([^`\n]+)`")

#: The source marker that must precede a code fence in a `SKILL.md`.
FROM = re.compile(r"<!--\s*from:\s*(\S+)\s*-->")

#: One markdown link, as `scripts/gen_skills.py` matches it: the text may
#: wrap a line, the target may not contain whitespace or a parenthesis.
LINK = re.compile(r"\[([^\[\]]+)\]\(([^()\s]+)\)")

#: What the rewriter leaves after a link into another skill's bundle:
#: the text, then the skill to install. Set aside when a republished
#: page is compared with the site's.
CARRIER = re.compile(r" \(see the athanore-[a-z]+ skill\)")


# --------------------------------------------------------------------------
# The parsers
# --------------------------------------------------------------------------


def strip_fences(text: str) -> str:
    """``text`` with every fenced code block removed, lines preserved.

    Inline code and links are what the rules read; a fence carries an
    install command or an excerpt, and neither is either.
    """

    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def is_path(span: str) -> bool:
    """Whether an inline-code span is meant as a checkout-relative path."""

    return not any(ch.isspace() for ch in span) and span.split("/", 1)[0] in ROOTS


def cited_paths(text: str) -> list[str]:
    """Every checkout path cited in ``text``, in order, duplicates kept."""

    return [span for span in SPAN.findall(strip_fences(text)) if is_path(span.strip())]


def reference_spans(text: str) -> list[str]:
    """Every inline-code span naming a file under the skill's `reference/`."""

    prefix = "reference/"
    return [
        span.strip()
        for span in SPAN.findall(strip_fences(text))
        if span.strip().startswith(prefix) and len(span.strip()) > len(prefix)
    ]


def relative_links(text: str) -> list[str]:
    """Every link target that is neither external nor fragment-only.

    The fragment is stripped: what has to exist is the file. A link in a
    fence is not a link, so fences are removed first.
    """

    found: list[str] = []
    for _, target in LINK.findall(strip_fences(text)):
        if "://" in target or target.startswith("#"):
            continue
        found.append(target.partition("#")[0])
    return found


def unlinked(text: str) -> str:
    """``text`` with every link reduced to its text and every carrier dropped.

    What a republished page and the site page it came from have in
    common, once links — and the "(see the athanore-x skill)" a link
    into another skill's bundle becomes — are set aside.
    """

    return CARRIER.sub("", LINK.sub(lambda match: match.group(1), text))


def fenced_blocks(text: str) -> list[tuple[str | None, str]]:
    """Every fenced block, with the path of the source marker above it."""

    blocks: list[tuple[str | None, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("```"):
            index += 1
            continue
        source: str | None = None
        for previous in reversed(lines[:index]):
            if previous.strip():
                marker = FROM.search(previous)
                source = marker.group(1) if marker else None
                break
        body: list[str] = []
        index += 1
        while index < len(lines) and not lines[index].lstrip().startswith("```"):
            body.append(lines[index])
            index += 1
        index += 1
        blocks.append((source, "\n".join(body)))
    return blocks


def is_excerpt(block: str, source: str) -> bool:
    """Whether ``block`` appears in ``source``, verbatim or indented.

    An excerpt of a declaration written inside a function is worth
    dedenting to read, so a uniform indent is allowed and nothing else
    is: the text itself must be the file's.
    """

    return any(textwrap.indent(block, " " * width) in source for width in range(0, 17))


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    """`scripts/gen_skills.py`, loaded by path.

    `scripts/` is dev machinery rather than a package, so there is no
    import to do. Loading the real file is the point: the renderer under
    test is the one CI runs, not a copy of it. The loader is shared with
    `tests/test_docs_site.py`, which loads the generator whose pages this
    one republishes.
    """

    return load_script("gen_skills")


@pytest.fixture(scope="module")
def site() -> ModuleType:
    """`scripts/gen_docs.py`, the generator whose pages the skills carry."""

    return load_script("gen_docs")


def skill_files() -> list[Path]:
    """Every hand-written skill file: the five skills and the README."""

    return [SKILLS / "README.md", *(SKILLS / name / "SKILL.md" for name in NAMES)]


def markdown_files() -> list[Path]:
    """Every markdown file under `skills/`, generated ones included."""

    return sorted(SKILLS.rglob("*.md"))


def relative(path: Path) -> str:
    return path.relative_to(SKILLS).as_posix()


def frontmatter(path: Path) -> dict[str, object]:
    """The YAML block a `SKILL.md` opens with."""

    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    closing = text.index("\n---\n", 3)
    loaded = yaml.safe_load(text[4:closing])
    assert isinstance(loaded, dict), path
    return loaded


# --------------------------------------------------------------------------
# The directory
# --------------------------------------------------------------------------


def test_the_five_skills_are_the_five_skills() -> None:
    """One skill per surface, and a README that is the front door."""

    assert sorted(p.name for p in SKILLS.iterdir() if p.is_dir()) == sorted(NAMES)
    assert (SKILLS / "README.md").is_file()
    for name in NAMES:
        assert (SKILLS / name / "SKILL.md").is_file(), name


def test_every_skill_is_linked_from_the_readme() -> None:
    """A sixth skill nobody can find would be a skill nobody loads."""

    readme = (SKILLS / "README.md").read_text(encoding="utf-8")
    for name in NAMES:
        assert f"{name}/SKILL.md" in readme, name


def test_the_readme_says_how_to_install_one() -> None:
    """Copying leads, because a copy now works; the symlink is how a
    checkout stays current; `npx skills add` is the convenience."""

    readme = (SKILLS / "README.md").read_text(encoding="utf-8")
    installs = [
        block
        for _, block in fenced_blocks(readme)
        if "cp -r" in block or "ln -s" in block or "npx skills" in block
    ]
    assert installs, "the README has no install command"
    assert "cp -r" in installs[0], "the copy is the form to lead with"
    assert any("ln -s" in block for block in installs)
    assert "npx skills add" in readme
    assert "uv run scripts/gen_skills.py" in readme


@pytest.mark.parametrize("name", NAMES)
def test_frontmatter_is_the_two_keys_the_format_reads(name: str) -> None:
    """`name` matches the directory, so installing is a copy with no rename."""

    loaded = frontmatter(SKILLS / name / "SKILL.md")
    assert set(loaded) == {"name", "description"}
    assert loaded["name"] == name
    description = loaded["description"]
    assert isinstance(description, str)
    assert description.strip()
    assert "\n" not in description
    # The format's cap. The description is the only part most agents read
    # before deciding whether to open the file, so it is also the one
    # sentence that has to say what the skill covers *and* when to load it.
    assert len(description) <= 1024, len(description)


# --------------------------------------------------------------------------
# The generated half
# --------------------------------------------------------------------------


def test_every_generated_file_is_one_the_script_writes(
    generator: ModuleType,
) -> None:
    """No file under a `reference/` directory is missing, and none is orphaned."""

    on_disk = {
        path.relative_to(ROOT).as_posix()
        for path in SKILLS.rglob("reference/*")
        if path.is_file()
    }
    assert on_disk == set(generator.TARGETS), STALE


def test_generated_files_are_byte_for_byte_what_the_script_writes(
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
        generator.render("skills/athanore-web/reference/panes.md")


def test_the_web_skill_has_no_generated_reference(generator: ModuleType) -> None:
    """Its facts are TypeScript; a Python parser restating them would be
    the second, weaker copy this design exists to prevent."""

    assert not (SKILLS / "athanore-web" / "reference").exists()
    assert not any(
        target.startswith("skills/athanore-web/") for target in generator.TARGETS
    )


def test_only_generated_files_carry_the_marker(
    generator: ModuleType, site: ModuleType
) -> None:
    """The marker is the one thing that says "do not edit this by hand".

    `reference/openapi.json` carries none — JSON has no comment — and is
    held to the snapshot instead. The site's own marker appears nowhere
    under `skills/`: a republished page says which script wrote *it*.
    """

    for target in generator.TARGETS:
        if target.endswith(".json"):
            continue
        first = (ROOT / target).read_text(encoding="utf-8").splitlines()[0]
        assert first == generator.MARKER, target
    for path in skill_files():
        assert generator.MARKER not in path.read_text(encoding="utf-8"), path
    for path in SKILLS.rglob("*"):
        if path.is_file():
            assert site.MARKER not in path.read_text(encoding="utf-8"), path


def test_the_api_skill_carries_the_openapi_document_byte_for_byte() -> None:
    """A client can be generated from the skill with no server running."""

    bundled = SKILLS / "athanore-api" / "reference" / "openapi.json"
    snapshot = ROOT / "tests" / "snapshots" / "openapi.json"
    assert bundled.read_bytes() == snapshot.read_bytes(), STALE


def generated_pages() -> list[Path]:
    """Every republished markdown page on disk, generated ones only."""

    return sorted(SKILLS.rglob("reference/*.md"))


@pytest.mark.parametrize("path", generated_pages(), ids=relative)
def test_a_republished_page_is_the_site_page_modulo_links_and_marker(
    path: Path, generator: ModuleType, site: ModuleType
) -> None:
    """What makes "one narrative" a checked fact rather than a described one.

    A guide is read from disk; a reference page is what `gen_docs.py`
    renders, in process. Either way, with the marker dropped and every
    link reduced to its text, the skill's copy is the site's page.
    """

    target = path.relative_to(ROOT).as_posix()
    skill, _, name = target.removeprefix("skills/").partition("/reference/")
    if name.startswith("guide-"):
        page = f"guide/{name.removeprefix('guide-')}"
    else:
        page = f"reference/{name}"
    assert page in generator.BUNDLES[skill], target

    copied = generator.render(target)
    assert copied.startswith(generator.MARKER + "\n\n")
    copied = copied[len(generator.MARKER) + 2 :]

    if page.startswith("guide/"):
        original = (SITE / page).read_text(encoding="utf-8")
        original = original.rstrip("\n") + "\n"
    else:
        original = site.render(f"docs/site/src/{page}")
        assert original.startswith(site.MARKER + "\n\n")
        original = original[len(site.MARKER) + 2 :]

    assert unlinked(copied) == unlinked(original), target


# --------------------------------------------------------------------------
# The hand-written half: nothing points outside the skill
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", markdown_files(), ids=relative)
def test_no_file_names_the_design_documents(path: Path) -> None:
    """A path the reader cannot open teaches nothing."""

    assert SPEC not in path.read_text(encoding="utf-8"), relative(path)


@pytest.mark.parametrize("path", markdown_files(), ids=relative)
def test_no_file_specifies_anything(path: Path) -> None:
    """RFC 2119's keywords belong to the specification, not to a skill."""

    found = keywords(path.read_text(encoding="utf-8"))
    assert not found, f"{relative(path)} carries {sorted(set(found))}"


@pytest.mark.parametrize("name", PORTABLE)
def test_a_portable_skill_names_no_checkout_path(name: str) -> None:
    """Its reader has no checkout, so a path into one is a dead pointer."""

    path = SKILLS / name / "SKILL.md"
    cited = cited_paths(path.read_text(encoding="utf-8"))
    assert cited == [], f"{relative(path)} cites {cited}"


@pytest.mark.parametrize(
    "path",
    [SKILLS / "README.md", SKILLS / "athanore-web" / "SKILL.md"],
    ids=relative,
)
def test_every_cited_path_exists(path: Path) -> None:
    """The two files that may point into the tree point at what is there."""

    cited = cited_paths(path.read_text(encoding="utf-8"))
    assert cited, f"{relative(path)} cites nothing, so this checks nothing"
    for target in cited:
        assert (ROOT / target).exists(), f"{relative(path)} cites {target}"


@pytest.mark.parametrize("path", markdown_files(), ids=relative)
def test_every_relative_link_resolves_inside_the_skill(path: Path) -> None:
    """The check that proves the link rewriter and the bundles agree.

    Every `[text](target)` that is neither external nor a fragment must
    name a file relative to the linking file's own directory, and every
    `reference/...` span in a `SKILL.md` must name a file under it.
    """

    text = path.read_text(encoding="utf-8")
    for target in relative_links(text):
        assert (path.parent / target).is_file(), f"{relative(path)} links {target}"
    if path.name == "SKILL.md":
        for span in reference_spans(text):
            assert (path.parent / span).is_file(), f"{relative(path)} names {span}"


@pytest.mark.parametrize("name", NAMES)
def test_every_reference_file_is_named_by_its_skill(name: str) -> None:
    """A generated file the front door never mentions is one an agent
    never loads."""

    skill = SKILLS / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    named = set(reference_spans(text)) | set(relative_links(text))
    reference = skill / "reference"
    files = sorted(reference.iterdir()) if reference.is_dir() else []
    for file in files:
        assert f"reference/{file.name}" in named, f"{name} never names {file.name}"


@pytest.mark.parametrize("name", NAMES)
def test_every_code_fence_is_a_marked_excerpt_that_parses(name: str) -> None:
    """A fence in a `SKILL.md` is code from the tree, or it is a copy.

    Every fence is preceded by `<!-- from: path -->` and its text appears
    in that file, verbatim or uniformly indented; every Python fence is
    a module that parses. `skills/README.md` is exempt: its fences are
    the install commands, which are excerpts of nothing.
    """

    path = SKILLS / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    blocks = fenced_blocks(text)
    assert blocks, f"{relative(path)} excerpts nothing, so this checks nothing"
    for source, block in blocks:
        assert source is not None, f"{relative(path)}: fence with no marker"
        target = ROOT / source
        assert target.is_file(), f"{relative(path)} names {source}"
        assert is_excerpt(block, target.read_text(encoding="utf-8")), (
            f"{relative(path)}: the fence marked `from: {source}` is not in that file"
        )
    for index, block in enumerate(python_fences(text)):
        try:
            ast.parse(block)
        except SyntaxError as exc:  # pragma: no cover - the assert reports it
            pytest.fail(f"{relative(path)} python fence {index}: {exc}")


@pytest.mark.parametrize("name", NAMES)
def test_a_skill_is_the_minimum_to_act(name: str) -> None:
    """A skill nobody finishes reading is a skill that does not work."""

    path = SKILLS / name / "SKILL.md"
    count = len(path.read_text(encoding="utf-8").splitlines())
    assert count <= MAX_LINES, f"{relative(path)} is {count} lines"


# --------------------------------------------------------------------------
# The rewriter, against text
# --------------------------------------------------------------------------


def test_a_link_into_the_bundle_becomes_the_filename(generator: ModuleType) -> None:
    text = "see [Node options](../reference/node-options.md) here"
    out = generator.rewrite(text, page="guide/workflows.md", skill="athanore-workflows")
    assert out == "see [Node options](node-options.md) here"


def test_a_fragment_is_kept(generator: ModuleType) -> None:
    text = (
        "[Writing a workflow](workflows.md#rule-3-the-exception-is-the-failure-policy)"
    )
    out = generator.rewrite(text, page="guide/runs.md", skill="athanore-workflows")
    assert out == (
        "[Writing a workflow]"
        "(guide-workflows.md#rule-3-the-exception-is-the-failure-policy)"
    )


def test_a_link_into_another_skill_names_that_skill(generator: ModuleType) -> None:
    text = "- [The command line](cli.md) — the answering verbs in full."
    out = generator.rewrite(
        text, page="guide/human-in-the-loop.md", skill="athanore-workflows"
    )
    assert out == (
        "- The command line (see the athanore-cli skill) — the answering verbs in full."
    )

    text = "described in\n[Driving the API](../guide/http-api.md)."
    out = generator.rewrite(text, page="reference/events.md", skill="athanore-plugins")
    assert out == "described in\nDriving the API (see the athanore-api skill)."


def test_a_link_to_an_unbundled_page_becomes_its_text(generator: ModuleType) -> None:
    text = "start at the [quickstart](../quickstart.md), then [install](../install.md)"
    out = generator.rewrite(text, page="guide/workflows.md", skill="athanore-workflows")
    assert out == "start at the quickstart, then install"


def test_the_openapi_document_resolves_in_the_api_skill(generator: ModuleType) -> None:
    text = "this page: [openapi.json](../openapi.json)."
    out = generator.rewrite(text, page="reference/http-api.md", skill="athanore-api")
    assert out == "this page: [openapi.json](openapi.json)."
    out = generator.rewrite(text, page="reference/http-api.md", skill="athanore-cli")
    assert out == "this page: openapi.json (see the athanore-api skill)."


def test_external_and_fragment_only_links_are_untouched(generator: ModuleType) -> None:
    text = "[ACP](https://agentclientprotocol.com) and [`Run`](#schema-Run)"
    out = generator.rewrite(text, page="reference/http-api.md", skill="athanore-api")
    assert out == text


def test_a_link_whose_text_wraps_keeps_its_line_break(generator: ModuleType) -> None:
    """A republished page has exactly the site page's line count."""

    text = "see [Runs, retries\nand capacity](runs.md) next"
    out = generator.rewrite(text, page="guide/workflows.md", skill="athanore-workflows")
    assert out == "see [Runs, retries\nand capacity](guide-runs.md) next"
    assert out.count("\n") == text.count("\n")


def test_a_list_comprehension_is_not_a_link(generator: ModuleType) -> None:
    text = '    return [build(item) for item in payload["items"]]'
    out = generator.rewrite(text, page="guide/workflows.md", skill="athanore-workflows")
    assert out == text


def test_every_bundled_page_is_a_site_page(generator: ModuleType) -> None:
    """A bundle naming a page that is not there would republish nothing."""

    for skill, bundle in generator.BUNDLES.items():
        assert skill in NAMES
        for page in bundle:
            assert (SITE / page).is_file() or page == generator.OPENAPI, page


# --------------------------------------------------------------------------
# The checkers, against text that is deliberately wrong
# --------------------------------------------------------------------------


def test_a_design_document_in_a_skill_is_caught() -> None:
    assert SPEC in "the rule is fixed in `docs/v1/04-engine.md` §Routing"


def test_a_keyword_in_a_skill_is_caught() -> None:
    assert keywords("A node body MUST NOT retry an agent call.") == ["MUST NOT"]
    assert keywords("A body may raise, and should say why.") == []


def test_a_checkout_path_in_a_portable_skill_is_caught() -> None:
    assert cited_paths("copy `workflows/feature/files.py` for this") == [
        "workflows/feature/files.py"
    ]
    assert cited_paths("see `README.md` §The CLI") == ["README.md"]


def test_code_in_prose_is_not_mistaken_for_a_path() -> None:
    """The rule has to be quiet about code, or every skill needs escapes."""

    text = (
        "`wf.node(...)`, `run.completed`, `/api/health`, `path/to/file.py:wf`, "
        "`athanore serve hello.py:wf`, `reference/events.md`, `athanore.testing`"
    )
    assert cited_paths(text) == []
    assert reference_spans(text) == ["reference/events.md"]
    assert reference_spans("this skill's `reference/` directory") == []


def test_a_path_inside_a_fence_is_not_a_citation() -> None:
    text = "```sh\nls docs/v1/nothing-here.md\n```\n"
    assert cited_paths(text) == []


def test_a_link_to_a_missing_file_is_caught() -> None:
    text = "see [the guide](guide-invented.md#anchor) and [top](#top)"
    assert relative_links(text) == ["guide-invented.md"]
    assert not (
        SKILLS / "athanore-workflows" / "reference" / "guide-invented.md"
    ).exists()


def test_an_external_link_is_not_a_relative_one() -> None:
    assert relative_links("[ACP](https://agentclientprotocol.com)") == []


def test_a_republished_page_that_drifted_is_caught() -> None:
    """The comparison sets links and carriers aside, and nothing else."""

    site = "see [Driving the API](http-api.md) for the stream."
    copy = "see Driving the API (see the athanore-api skill) for the stream."
    assert unlinked(copy) == unlinked(site)
    assert unlinked("see Driving the API for the socket.") != unlinked(site)


def test_a_fence_with_no_source_marker_is_caught() -> None:
    assert fenced_blocks("prose\n\n```python\nx = 1\n```\n") == [(None, "x = 1")]


def test_a_fence_that_is_not_in_the_file_it_names_is_caught() -> None:
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    assert is_excerpt("async def shout(*, name):", source)
    assert not is_excerpt("async def shout(*, name, invented):", source)

    # A declaration written inside a function may be dedented to read,
    # which is the one liberty `is_excerpt` takes.
    nested = (ROOT / "docs/site/src/guide/workflows.md").read_text(encoding="utf-8")
    assert is_excerpt('return {"shipped": True}', nested)
    assert not is_excerpt('return {"invented": True}', nested)


def test_a_python_fence_that_does_not_parse_is_caught() -> None:
    text = "<!-- from: README.md -->\n```python\nasync def n(\n```\n"
    assert python_fences(text) == ["async def n("]
    with pytest.raises(SyntaxError):
        ast.parse(python_fences(text)[0])


def test_a_stale_copy_is_caught(
    generator: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edited guide is a red byte-check until the skills are regenerated.

    The generator reads guides under its `ROOT`, so pointing that at a
    tree holding an edited copy is the edit without touching the site.
    """

    page = "docs/site/src/guide/workflows.md"
    edited = tmp_path / page
    edited.parent.mkdir(parents=True)
    edited.write_text(
        (ROOT / page).read_text(encoding="utf-8") + "\nAn edit.\n", encoding="utf-8"
    )
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    target = "skills/athanore-workflows/reference/guide-workflows.md"
    committed = (ROOT / target).read_text(encoding="utf-8")
    assert generator.render(target) != committed
    assert generator.render(target).endswith("\nAn edit.\n")
