"""The skills under `skills/` are pointers, and every pointer resolves.

A skill is a pointer, never a copy (D213). That splits `skills/` in two
and this suite holds both halves:

- a `SKILL.md` is hand-written and cites; every path it names must exist,
  every section it names must be a real heading in the document it names
  it beside, and every code fence must be an excerpt of the file its
  source marker points at;
- everything a skill would otherwise have restated is generated into its
  `reference/` directory by `scripts/gen_skills.py`, and the committed
  bytes must be what that script writes.

The second half is the OpenAPI snapshot's check again
(`tests/test_openapi_snapshot.py`), and CI's `contract` job is its other
half: it regenerates and runs `git diff --exit-code` over `skills/`. The
first half is the one that cannot be generated — which section answers
which question is judgement — and making the citation form
machine-checkable is what keeps it honest.

A checker that passes everything is the one failure mode this design
cannot survive, so the parsers below are exercised against deliberately
broken text as well as against the tree.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

#: The five surfaces, and the whole of `skills/` besides its README.
NAMES = (
    "athanore-workflows",
    "athanore-plugins",
    "athanore-api",
    "athanore-cli",
    "athanore-web",
)

STALE = (
    "a file under skills/*/reference/ is stale. Regenerate it:\n"
    "    uv run scripts/gen_skills.py"
)

#: What the first segment of a path citation may be: the top-level
#: directories of the checkout a skill points into, and the root files it
#: cites. An inline-code span that starts with anything else is code
#: rather than a path — `wf.node(...)`, `run.completed`, `/api/health` —
#: and is deliberately not checked, so that code in prose needs no escape.
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

#: A path citation followed by the `§` that opens a section citation.
SECTION = re.compile(r"`([^`\n]+)`\s+§")

#: The source marker that must precede a code fence in a `SKILL.md`.
FROM = re.compile(r"<!--\s*from:\s*(\S+)\s*-->")

#: A markdown heading, once fenced blocks are out of the way.
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")


# --------------------------------------------------------------------------
# The three citation forms, parsed
# --------------------------------------------------------------------------


def strip_fences(text: str) -> str:
    """``text`` with every fenced code block removed, lines preserved.

    Inline code is what carries a citation; a fence carries an install
    command or an excerpt, and neither is one.
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
    """Every path citation in ``text``, in order, duplicates kept."""

    return [span for span in SPAN.findall(strip_fences(text)) if is_path(span.strip())]


def section_text(rest: str) -> str:
    """The heading named after a `§`, read to the citation's end.

    It runs to the end of the line, a comma, a semicolon, a table-cell
    pipe, a full stop, or a closing parenthesis that has no opening one
    inside the citation — so `§Fan-in (join nodes)` keeps its
    parentheses and `(§Slots)` does not take the wrapper's.
    """

    depth = 0
    out: list[str] = []
    for index, char in enumerate(rest):
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0:
            if char in ",;|":
                break
            if char == "." and (index + 1 == len(rest) or rest[index + 1] == " "):
                break
        out.append(char)
    return "".join(out).strip()


def cited_sections(text: str) -> list[tuple[str, str]]:
    """Every ``(document, heading)`` a section citation names."""

    found: list[tuple[str, str]] = []
    for line in strip_fences(text).splitlines():
        for match in SECTION.finditer(line):
            document = match.group(1).strip()
            if not is_path(document):
                continue
            heading = section_text(line[match.end() :])
            if heading:
                found.append((document, heading))
    return found


def headings(path: Path) -> set[str]:
    """Every heading of a markdown file, without its trailing aside.

    Some headings carry an aside after a long gap — 05 and 19 both do —
    and a citation names the heading, not the aside, so the comparison is
    against the leading text up to a run of two or more spaces.
    """

    found: set[str] = set()
    for line in strip_fences(path.read_text(encoding="utf-8")).splitlines():
        match = HEADING.match(line)
        if match:
            found.add(re.split(r"\s{2,}", match.group(1))[0].strip())
    return found


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
    test is the one CI runs, not a copy of it.
    """

    path = ROOT / "scripts" / "gen_skills.py"
    spec = importlib.util.spec_from_file_location("gen_skills", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def skill_files() -> list[Path]:
    """Every hand-written skill file: the five skills and the README."""

    return [SKILLS / "README.md", *(SKILLS / name / "SKILL.md" for name in NAMES)]


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
    """The install command lives in one place, and this is it (D213)."""

    readme = (SKILLS / "README.md").read_text(encoding="utf-8")
    assert "uv run scripts/gen_skills.py" in readme
    assert any("ln -s" in block for _, block in fenced_blocks(readme)), (
        "the symlink install is the form to lead with"
    )


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
    the second, weaker copy this design exists to prevent (D213)."""

    assert not (SKILLS / "athanore-web" / "reference").exists()
    assert not any(
        target.startswith("skills/athanore-web/") for target in generator.TARGETS
    )


def test_only_generated_files_carry_the_marker(generator: ModuleType) -> None:
    """The marker is the one thing that says "do not edit this by hand"."""

    for target in generator.TARGETS:
        first = (ROOT / target).read_text(encoding="utf-8").splitlines()[0]
        assert first == generator.MARKER, target
    for path in skill_files():
        assert generator.MARKER not in path.read_text(encoding="utf-8"), path


# --------------------------------------------------------------------------
# The hand-written half: every pointer resolves
# --------------------------------------------------------------------------


def skill_and_reference_files() -> list[Path]:
    """Every markdown file under `skills/`, generated ones included.

    The generated files carry citations too — each says which section
    specifies what it lists — and a renamed heading must fail the gate
    wherever it is cited.
    """

    return sorted(SKILLS.rglob("*.md"))


@pytest.mark.parametrize(
    "path", skill_and_reference_files(), ids=lambda p: p.relative_to(SKILLS).as_posix()
)
def test_every_cited_path_exists(path: Path) -> None:
    for cited in cited_paths(path.read_text(encoding="utf-8")):
        assert (ROOT / cited).exists(), f"{path.relative_to(ROOT)} cites {cited}"


@pytest.mark.parametrize(
    "path", skill_and_reference_files(), ids=lambda p: p.relative_to(SKILLS).as_posix()
)
def test_every_cited_section_is_a_heading_of_the_document_beside_it(
    path: Path,
) -> None:
    for document, heading in cited_sections(path.read_text(encoding="utf-8")):
        target = ROOT / document
        assert target.is_file(), f"{path.relative_to(ROOT)} cites {document}"
        assert heading in headings(target), (
            f"{path.relative_to(ROOT)} cites {document} §{heading}, "
            f"which is not a heading of it"
        )


@pytest.mark.parametrize("name", NAMES)
def test_every_code_fence_is_an_excerpt_of_the_file_it_names(name: str) -> None:
    """A fence in a `SKILL.md` is code from the tree, or it is a copy.

    `skills/README.md` is exempt: its fences are the install commands,
    which are excerpts of nothing.
    """

    path = SKILLS / name / "SKILL.md"
    for source, block in fenced_blocks(path.read_text(encoding="utf-8")):
        assert source is not None, f"{path.relative_to(ROOT)}: fence with no marker"
        target = ROOT / source
        assert target.is_file(), f"{path.relative_to(ROOT)} names {source}"
        assert is_excerpt(block, target.read_text(encoding="utf-8")), (
            f"{path.relative_to(ROOT)}: the fence marked `from: {source}` "
            f"is not in that file"
        )


def test_the_skills_actually_cite_something() -> None:
    """The checkers must have work to do.

    A parser that never matched would pass every file above without
    reading a single citation, which is the quiet way this whole design
    stops working.
    """

    for name in NAMES:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert len(cited_paths(text)) >= 5, name
        assert len(cited_sections(text)) >= 5, name
    assert any(
        fenced_blocks((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
        for name in NAMES
    ), "no skill excerpts any code, so the excerpt check checks nothing"


# --------------------------------------------------------------------------
# The checkers, against text that is deliberately wrong
# --------------------------------------------------------------------------


def test_a_deleted_path_is_caught() -> None:
    assert cited_paths("see `docs/v1/99-nonexistent.md` for this") == [
        "docs/v1/99-nonexistent.md"
    ]
    assert not (ROOT / "docs/v1/99-nonexistent.md").exists()


def test_code_in_prose_is_not_mistaken_for_a_path() -> None:
    """The rule has to be quiet about code, or every skill needs escapes."""

    text = "`wf.node(...)`, `run.completed`, `/api/health`, `path/to/file.py:wf`"
    assert cited_paths(text) == []


def test_a_path_inside_a_fence_is_not_a_citation() -> None:
    text = "```sh\nls docs/v1/nothing-here.md\n```\n"
    assert cited_paths(text) == []


def test_an_invented_heading_is_caught() -> None:
    text = "`docs/v1/04-engine.md` §Not A Real Heading"
    assert cited_sections(text) == [("docs/v1/04-engine.md", "Not A Real Heading")]
    assert "Not A Real Heading" not in headings(ROOT / "docs/v1/04-engine.md")


def test_a_renamed_section_is_caught() -> None:
    """The failure a rename produces: the citation parses, and misses."""

    document = ROOT / "docs/v1/04-engine.md"
    assert "Fan-in (join nodes)" in headings(document)
    assert "Fan-in" not in headings(document)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("`d.md` §Fan-in (join nodes)", "Fan-in (join nodes)"),
        ("(`d.md` §Slots)", "Slots"),
        (
            "`d.md` §Node options (metadata seam). Then prose.",
            "Node options (metadata seam)",
        ),
        ("| `d.md` §Fakes |", "Fakes"),
        ("`d.md` §Pools, and `e.md` §Scheduling", "Pools"),
        (
            "`d.md` §Failure classes (rule 3, refined).",
            "Failure classes (rule 3, refined)",
        ),
        ("(`d.md` §The three rules (unchanged)):", "The three rules (unchanged)"),
    ],
)
def test_the_section_parse_stops_where_the_citation_does(
    line: str, expected: str
) -> None:
    match = SECTION.search(line)
    assert match is not None
    assert section_text(line[match.end() :]) == expected


def test_a_second_citation_on_one_line_is_read_too() -> None:
    line = "`docs/v1/04-engine.md` §Pools, and `docs/v1/04-engine.md` §Scheduling"
    assert cited_sections(line) == [
        ("docs/v1/04-engine.md", "Pools"),
        ("docs/v1/04-engine.md", "Scheduling"),
    ]


def test_a_fence_with_no_source_marker_is_caught() -> None:
    assert fenced_blocks("prose\n\n```python\nx = 1\n```\n") == [(None, "x = 1")]


def test_a_fence_that_is_not_in_the_file_it_names_is_caught() -> None:
    source = (ROOT / "workflows" / "rps.py").read_text(encoding="utf-8")
    assert is_excerpt("async def tally(*, payload):", source)
    assert not is_excerpt("async def tally(*, payload, invented):", source)

    # A declaration written inside a function may be dedented to read,
    # which is the one liberty `is_excerpt` takes.
    nested = (ROOT / "workflows" / "feature" / "files.py").read_text(encoding="utf-8")
    assert is_excerpt('@wf.route("/files")', nested)
    assert not is_excerpt('@wf.route("/invented")', nested)


def test_a_heading_inside_a_fence_is_not_a_heading() -> None:
    """07 has a `#` comment inside a code block, and it is not a section."""

    assert "commit → events inserted in the same transaction" not in " ".join(
        headings(ROOT / "docs/v1/07-storage.md")
    )
