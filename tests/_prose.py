"""The prose rules the site and the skills share, parsed.

`docs/site/src/` and `skills/` are both written for a reader who is
*using* Athanore rather than building it, and neither may become a
second specification: no page names the design documents, no page
carries a capitalised RFC 2119 keyword, and every Python example is a
module that parses. `tests/test_docs_site.py` and `tests/test_skills.py`
hold their trees to those rules with the parsers here, so a rule is one
regular expression rather than two that drift.
"""

from __future__ import annotations

import re

#: RFC 2119's keywords, in the capitalised form the design documents give
#: them. A guide and a skill describe; they do not specify, so none of
#: them belongs in either. Longest first, so `MUST NOT` is reported as
#: itself.
KEYWORDS = (
    "MUST NOT",
    "SHOULD NOT",
    "MUST",
    "SHOULD",
    "SHALL",
    "REQUIRED",
    "RECOMMENDED",
    "OPTIONAL",
    "MAY",
)
KEYWORD = re.compile(r"\b(" + "|".join(KEYWORDS) + r")\b")

#: The directory neither tree is a second copy of. One nav entry in
#: `docs/site/mkdocs.yml` links it, and no page and no skill names it.
SPEC = "docs/v1"

#: The per-task plans, the other developer-only tree. Named beside
#: `SPEC` wherever a user-facing tree is checked for it.
PLANS = "docs/plans"


def keywords(text: str) -> list[str]:
    """Every capitalised RFC 2119 keyword in ``text``."""

    return KEYWORD.findall(text)


def python_fences(text: str) -> list[str]:
    """The body of every ` ```python ` block, in order."""

    blocks: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opening = lines[index].strip()
        index += 1
        if opening != "```python":
            continue
        body: list[str] = []
        while index < len(lines) and not lines[index].strip().startswith("```"):
            body.append(lines[index])
            index += 1
        index += 1
        blocks.append("\n".join(body))
    return blocks
