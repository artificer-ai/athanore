"""Writing `[workflows.<name>]` rows in place (T085, 22 §Persistence, D228).

The subject is what happens to the *rest* of the file: the operator's
comments, the `[pools]` table, the other rows' spacing. Every test
starts from a file with all of those in it and asserts that exactly the
intended line changed — by diffing the text, not by parsing it back.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import pytest

from athanore.plugins.persist import PersistError, remove_row, write_row

#: A file with everything a writer could break: a header comment, a
#: top-level setting, a `[pools]` table with a trailing comment, and two
#: rows — one commented inline, one with an unusual spacing.
ORIGINAL = """\
# The project's athanore.toml — hands off the comments.
workers = 2

[pools]
local = 1   # one build at a time
cloud = 8

[workflows]
feature = { pool = "local" }   # the build
chat    = { target = "workflows/chat.py:wf", pool = "cloud" }
"""


@pytest.fixture
def toml(tmp_path: Path) -> Path:
    path = tmp_path / "athanore.toml"
    path.write_text(ORIGINAL)
    return path


def added_lines(before: str, after: str) -> list[str]:
    """The lines in ``after`` that are not in ``before``, in order."""

    old = before.splitlines()
    return [line for line in after.splitlines() if line not in old]


def removed_lines(before: str, after: str) -> list[str]:
    new = after.splitlines()
    return [line for line in before.splitlines() if line not in new]


def test_write_row_adds_one_line_and_changes_nothing_else(toml: Path) -> None:
    write_row(toml, "hello", "workflows/hello.py:wf", None)
    after = toml.read_text()
    assert added_lines(ORIGINAL, after) == [
        'hello = { target = "workflows/hello.py:wf" }'
    ]
    assert removed_lines(ORIGINAL, after) == []
    # And the row reads back as the registration it is.
    rows = tomllib.loads(after)["workflows"]
    assert rows["hello"] == {"target": "workflows/hello.py:wf"}
    assert rows["chat"] == {"target": "workflows/chat.py:wf", "pool": "cloud"}


def test_write_row_carries_the_pool_only_when_given(toml: Path) -> None:
    write_row(toml, "hello", "workflows/hello.py:wf", "cloud")
    assert added_lines(ORIGINAL, toml.read_text()) == [
        'hello = { target = "workflows/hello.py:wf", pool = "cloud" }'
    ]


def test_write_row_replaces_an_existing_row_whole(toml: Path) -> None:
    """A `pool` the call did not give is dropped: the row is the request."""

    write_row(toml, "chat", "workflows/chat2.py:wf", None)
    after = toml.read_text()
    assert removed_lines(ORIGINAL, after) == [
        'chat    = { target = "workflows/chat.py:wf", pool = "cloud" }'
    ]
    assert added_lines(ORIGINAL, after) == [
        'chat    = { target = "workflows/chat2.py:wf" }'
    ]
    assert tomllib.loads(after)["workflows"]["chat"] == {
        "target": "workflows/chat2.py:wf"
    }
    # The inline comment on the row beside it, and the header, survive.
    assert "# the build" in after
    assert after.startswith("# The project's athanore.toml")


def test_write_row_keeps_a_rows_inline_comment(toml: Path) -> None:
    write_row(toml, "feature", "flows.py:feature", "local")
    after = toml.read_text()
    assert (
        'feature = { target = "flows.py:feature", pool = "local" }   # the build'
        in (after)
    )


def test_a_missing_file_is_created_with_the_one_table(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    write_row(path, "hello", "workflows/hello.py:wf", None)
    assert (
        path.read_text()
        == '[workflows]\nhello = { target = "workflows/hello.py:wf" }\n'
    )


def test_a_file_without_the_table_gains_one_after_its_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text("# mine\nworkers = 3\n\n[pools]\nlocal = 1\n")
    write_row(path, "hello", "workflows/hello.py:wf", None)
    assert path.read_text() == (
        "# mine\nworkers = 3\n\n[pools]\nlocal = 1\n\n"
        '[workflows]\nhello = { target = "workflows/hello.py:wf" }\n'
    )


def test_a_quote_in_a_target_is_escaped(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    target = 'odd "name".py:wf'
    write_row(path, "odd", target, None)
    assert tomllib.loads(path.read_text())["workflows"]["odd"]["target"] == target


def test_remove_row_deletes_only_the_row(toml: Path) -> None:
    assert remove_row(toml, "chat") is True
    after = toml.read_text()
    assert removed_lines(ORIGINAL, after) == [
        'chat    = { target = "workflows/chat.py:wf", pool = "cloud" }'
    ]
    assert added_lines(ORIGINAL, after) == []


def test_remove_row_leaves_an_emptied_table_in_place(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text(
        '[pools]\nlocal = 1\n\n[workflows]\nchat = { target = "c.py:wf" }\n'
    )
    assert remove_row(path, "chat") is True
    assert path.read_text() == "[pools]\nlocal = 1\n\n[workflows]\n"


def test_remove_row_of_an_absent_row_does_not_rewrite(toml: Path) -> None:
    """A no-op that does not touch the file: same bytes, same mtime."""

    before = toml.stat()
    os.utime(toml, (before.st_atime - 100, before.st_mtime - 100))
    stamped = toml.stat().st_mtime_ns
    assert remove_row(toml, "nope") is False
    assert toml.read_text() == ORIGINAL
    assert toml.stat().st_mtime_ns == stamped


def test_remove_row_of_an_absent_file_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    assert remove_row(path, "nope") is False
    assert not path.exists()


def test_an_unparsable_file_is_a_persist_error(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text("[workflows\nbroken = \n")
    with pytest.raises(PersistError) as raised:
        write_row(path, "hello", "h.py:wf", None)
    assert raised.value.path == path
    assert raised.value.detail
    with pytest.raises(PersistError):
        remove_row(path, "hello")
    # Nothing was written over the operator's broken file.
    assert path.read_text() == "[workflows\nbroken = \n"


def test_a_table_that_is_not_one_is_a_persist_error(tmp_path: Path) -> None:
    path = tmp_path / "athanore.toml"
    path.write_text("workflows = 1\n")
    with pytest.raises(PersistError, match="is not a table"):
        write_row(path, "hello", "h.py:wf", None)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes read-only files")
def test_a_read_only_file_is_a_persist_error(toml: Path) -> None:
    toml.chmod(stat.S_IRUSR)
    try:
        with pytest.raises(PersistError) as raised:
            write_row(toml, "hello", "h.py:wf", None)
        assert raised.value.path == toml
        with pytest.raises(PersistError):
            remove_row(toml, "chat")
    finally:
        toml.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert toml.read_text() == ORIGINAL
