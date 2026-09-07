"""pi's session file, read (T040; `docs/porting-ledger.md`: `test_stats.py`).

The half of the MVP's stats suite that is vendor knowledge. The pure half
— the ACP ``usage`` read, the merge precedence, the entry's omissions and
the ``[stats]`` line — is ``tests/agents/test_stats_unit.py``'s and stays
in the package; what is here is everything that only makes sense if you
know what pi writes to disk, which is why it is tested from outside
``athanore`` (D14, D27).

Every file these tests read is written by :func:`session`, in pi's own
shape: a ``session`` header line, an optional ``model_change``, and
assistant messages carrying ``usage`` objects. The two layouts pi has
used are both built, because both are still on disk and the reader has to
find either.

What is asserted throughout is the same rule the package's half asserts:
a counter that was not there comes back ``None``, never a zero. The one
place that is easy to get wrong is ``cost`` — a real ``$0.0000`` from a
local model and a cost object pi wrote without a total are different
answers, and only the first is a measurement.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from athanore.agents.stats import SessionStats, SessionStatsProvider
from pi.stats import (
    PiSessionStats,
    default_sessions_root,
    final_assistant_stop_reason,
    find_session_file,
    parse_session_file,
)

#: A pi session id: a uuid, as pi mints them.
SID = "01a012f7-d9d7-700e-8661-04d982431e5c"

#: What the fixtures below say answered the prompt.
MODEL = "llama-server/qwen3.8-27b"


def usage(
    input_tokens: int = 100, output_tokens: int = 50, cost: float | None = 0.0
) -> dict[str, Any]:
    """One assistant message's ``usage``, as pi writes it.

    ``totalTokens`` is deliberately larger than input + output: it counts
    the context the turn re-read, which is why the reader must not sum
    it. ``cost=None`` writes no cost object at all.
    """

    written: dict[str, Any] = {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": 0,
        "cacheWrite": 0,
        "reasoning": 3,
        "totalTokens": input_tokens + output_tokens + 5000,
    }
    if cost is not None:
        written["cost"] = {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": cost,
        }
    return written


def assistant(
    message_id: str = "m1", stop_reason: str | None = "endTurn", **fields: Any
) -> dict[str, Any]:
    """One assistant message entry, with ``usage`` unless told otherwise."""

    message: dict[str, Any] = {
        "role": "assistant",
        "content": [{"type": "text", "text": "hi"}],
        "provider": "llama-server",
        "model": "qwen3.8-27b",
        "usage": usage(),
    }
    message.update(fields)
    if stop_reason is not None:
        message.setdefault("stopReason", stop_reason)
    return {
        "type": "message",
        "id": message_id,
        "parentId": None,
        "timestamp": "t",
        "message": message,
    }


def session(
    root: Path,
    session_id: str = SID,
    *,
    header_id: str | None = None,
    nested: bool = False,
    model_change: bool = True,
    entries: list[dict[str, Any]] | None = None,
    truncate_last: bool = False,
    cwd_dir: str = "cwd",
) -> Path:
    """Write one pi session file under ``root`` and return its path.

    ``nested`` writes the second layout — the run directory pi files a
    resumed session under — and ``truncate_last`` cuts the tail off, the
    way a killed pi leaves a half-written final line.
    """

    lines: list[dict[str, Any]] = [
        {
            "type": "session",
            "version": 3,
            "id": header_id or session_id,
            "timestamp": "t",
            "cwd": "/x",
        }
    ]
    if model_change:
        lines.append(
            {
                "type": "model_change",
                "id": "mc",
                "parentId": None,
                "timestamp": "t",
                "provider": "llama-server",
                "modelId": "qwen3.8-27b",
            }
        )
    lines.extend(entries if entries is not None else [assistant()])

    stamped = f"2026-01-01T00-00-00Z_{session_id}"
    if nested:
        directory = root / cwd_dir / stamped / "abc123" / "run-0"
        path = directory / "session.jsonl"
    else:
        directory = root / cwd_dir
        path = directory / f"{stamped}.jsonl"
    directory.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line) + "\n" for line in lines)
    path.write_text(text[:-20] if truncate_last else text, encoding="utf-8")
    return path


def rewrite(path: Path, **usage_changes: Any) -> None:
    """Rewrite every assistant ``usage`` in ``path`` with ``usage_changes``.

    A key set to ``None`` is removed. Used to take a field back out of a
    real file rather than to build a file the reader has never seen.
    """

    entries = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    for entry in entries:
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        for key, value in usage_changes.items():
            if value is None:
                message["usage"].pop(key, None)
            else:
                message["usage"][key] = value
    path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Finding the file
# --------------------------------------------------------------------------


def test_the_flat_layout_is_found(tmp_path: Path) -> None:
    written = session(tmp_path)
    assert find_session_file(SID, tmp_path) == written


def test_the_nested_run_layout_is_found(tmp_path: Path) -> None:
    """The second layout: a run directory under the session directory."""

    written = session(tmp_path, nested=True)
    found = find_session_file(SID, tmp_path)
    assert found == written
    assert found is not None and "run-0" in found.parts


def test_an_unknown_session_is_not_found(tmp_path: Path) -> None:
    session(tmp_path)
    assert find_session_file("01a00000-0000-0000-0000-000000000000", tmp_path) is None


def test_the_header_has_to_agree_with_the_name(tmp_path: Path) -> None:
    """A filename carrying the id is not enough: the header decides.

    Session ids are uuids and the glob matches on a suffix, so this is
    what keeps a prefix collision — or a file someone copied — from being
    read as another run's session.
    """

    session(tmp_path, header_id="some-other-session")
    assert find_session_file(SID, tmp_path) is None


def test_the_newest_of_several_matches_wins(tmp_path: Path) -> None:
    """One session id under two cwd directories: the newest file answers."""

    first = session(tmp_path, cwd_dir="cwd-a")
    os.utime(first, (time.time() - 100, time.time() - 100))
    second = session(tmp_path, cwd_dir="cwd-b")
    assert find_session_file(SID, tmp_path) == second

    os.utime(first, (time.time() + 50, time.time() + 50))
    assert find_session_file(SID, tmp_path) == first


def test_a_missing_root_is_no_session(tmp_path: Path) -> None:
    assert find_session_file(SID, tmp_path / "nope") is None


def test_no_session_id_is_no_session(tmp_path: Path) -> None:
    session(tmp_path)
    assert find_session_file("", tmp_path) is None


def test_a_header_that_is_not_json_is_skipped(tmp_path: Path) -> None:
    """A file pi had only just created, with nothing readable in it yet."""

    directory = tmp_path / "cwd"
    directory.mkdir()
    (directory / f"2026-01-01T00-00-00Z_{SID}.jsonl").write_text("{ not json\n")
    assert find_session_file(SID, tmp_path) is None


def test_the_default_root_follows_pis_own_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PI_CODING_AGENT_DIR`` is what the dev image sets; pi reads it."""

    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "elsewhere"))
    assert default_sessions_root() == tmp_path / "elsewhere" / "sessions"

    monkeypatch.delenv("PI_CODING_AGENT_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert default_sessions_root() == tmp_path / "home" / ".pi" / "agent" / "sessions"


# --------------------------------------------------------------------------
# Reading it
# --------------------------------------------------------------------------


def test_usage_is_summed_over_the_assistant_messages(tmp_path: Path) -> None:
    """And over those only: a tool result carries no usage to sum."""

    path = session(
        tmp_path,
        entries=[
            assistant(),
            assistant("m2", usage=usage(200, 75)),
            {
                "type": "message",
                "id": "m3",
                "parentId": "m2",
                "timestamp": "t",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "x",
                    "content": [{"type": "text", "text": "out"}],
                },
            },
        ],
    )
    parsed = parse_session_file(path)
    assert parsed.input_tokens == 300
    assert parsed.output_tokens == 125
    assert parsed.model == MODEL


def test_the_re_read_context_is_not_summed(tmp_path: Path) -> None:
    """``totalTokens`` counts the context again on every turn.

    Summing it over a session would count the same tokens once per turn,
    which is why the reader reports the two sides and the façade derives
    the total from them (05 §Stats entry).
    """

    path = session(
        tmp_path, entries=[assistant(), assistant("m2", usage=usage(200, 75))]
    )
    parsed = parse_session_file(path)
    assert (parsed.input_tokens, parsed.output_tokens) == (300, 125)
    assert parsed.input_tokens is not None and parsed.output_tokens is not None
    assert parsed.input_tokens + parsed.output_tokens == 425


def test_a_reported_zero_cost_is_a_measurement(tmp_path: Path) -> None:
    """A local model really does cost nothing, and that is data (01)."""

    assert parse_session_file(session(tmp_path)).cost == 0.0


def test_a_cost_object_without_a_total_reports_nothing(tmp_path: Path) -> None:
    """Not a `$0.0000`: the sum of no totals is not a total of zero."""

    path = session(tmp_path)
    rewrite(path, cost={"input": 0.0, "output": 0.0})
    assert parse_session_file(path).cost is None


def test_a_session_with_no_cost_at_all_reports_nothing(tmp_path: Path) -> None:
    path = session(tmp_path)
    rewrite(path, cost=None)
    assert parse_session_file(path).cost is None


def test_costs_are_summed_over_the_session(tmp_path: Path) -> None:
    path = session(
        tmp_path,
        entries=[
            assistant(usage=usage(cost=0.0004)),
            assistant("m2", usage=usage(cost=0.0006)),
        ],
    )
    assert parse_session_file(path).cost == pytest.approx(0.001)


def test_the_last_model_change_is_the_model(tmp_path: Path) -> None:
    """A session may switch models; the last switch is what answered."""

    path = session(
        tmp_path,
        entries=[
            assistant(),
            {
                "type": "model_change",
                "id": "mc2",
                "parentId": "m1",
                "timestamp": "t2",
                "provider": "openrouter",
                "modelId": "qwen/qwen3.8-max",
            },
        ],
    )
    assert parse_session_file(path).model == "openrouter/qwen/qwen3.8-max"


def test_without_a_switch_the_message_names_the_model(tmp_path: Path) -> None:
    assert parse_session_file(session(tmp_path, model_change=False)).model == MODEL


def test_a_half_written_final_line_is_skipped(tmp_path: Path) -> None:
    """pi killed mid-write: the truncated line goes, the rest survives."""

    path = session(
        tmp_path,
        entries=[assistant(), assistant("m2", usage=usage(200, 75))],
        truncate_last=True,
    )
    parsed = parse_session_file(path)
    assert parsed.model == MODEL
    assert parsed.input_tokens == 100


def test_an_empty_file_determines_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert parse_session_file(empty) == SessionStats()


def test_an_unreadable_file_determines_nothing(tmp_path: Path) -> None:
    """A path that is not a file at all: unknown, not an exception."""

    assert parse_session_file(tmp_path / "gone.jsonl") == SessionStats()


def test_a_session_that_never_answered_has_no_counters(tmp_path: Path) -> None:
    """The model is still known: the header's switch said what was loaded."""

    parsed = parse_session_file(session(tmp_path, entries=[]))
    assert parsed.input_tokens is None
    assert parsed.output_tokens is None
    assert parsed.cost is None
    assert parsed.model == MODEL


def test_one_sided_usage_stays_one_sided(tmp_path: Path) -> None:
    """pi writes usage on some messages and not others; both are read.

    The side that was measured is reported and the side that was not is
    ``None`` — which is what makes the ``[stats]`` line's ``n`` marker
    honest rather than a zero.
    """

    path = session(
        tmp_path,
        entries=[
            assistant(usage={"input": 7}),
            assistant("m2", usage={"input": 3, "output": 2}),
        ],
    )
    parsed = parse_session_file(path)
    assert (parsed.input_tokens, parsed.output_tokens) == (10, 2)

    only_output = session(
        tmp_path,
        "01a013aa-0000-0000-0000-000000000002",
        entries=[assistant(usage={"output": 4})],
    )
    parsed = parse_session_file(only_output)
    assert parsed.output_tokens == 4
    assert parsed.input_tokens is None


def test_a_boolean_is_not_a_token_count(tmp_path: Path) -> None:
    """``True`` is an ``int`` to Python and a mistake in a usage object."""

    path = session(tmp_path, entries=[assistant(usage={"input": True, "output": 5})])
    parsed = parse_session_file(path)
    assert parsed.input_tokens is None
    assert parsed.output_tokens == 5


# --------------------------------------------------------------------------
# The final turn's stop reason
# --------------------------------------------------------------------------


def test_the_last_assistant_stop_reason_is_the_final_one(tmp_path: Path) -> None:
    path = session(
        tmp_path,
        entries=[
            assistant(stop_reason="toolUse"),
            assistant("m2", stop_reason="length"),
        ],
    )
    assert final_assistant_stop_reason(path) == "length"


def test_a_later_tool_result_does_not_displace_it(tmp_path: Path) -> None:
    """Only assistant messages carry a stop reason worth reading."""

    path = session(
        tmp_path,
        entries=[
            assistant(stop_reason="length"),
            {
                "type": "message",
                "id": "m2",
                "message": {"role": "toolResult", "stopReason": "endTurn"},
            },
        ],
    )
    assert final_assistant_stop_reason(path) == "length"


def test_no_stop_reason_is_not_determined(tmp_path: Path) -> None:
    path = session(tmp_path, entries=[assistant(stop_reason=None)])
    assert final_assistant_stop_reason(path) is None
    assert final_assistant_stop_reason(tmp_path / "gone.jsonl") is None


# --------------------------------------------------------------------------
# The provider the façade holds
# --------------------------------------------------------------------------


def test_the_provider_satisfies_the_protocol() -> None:
    """What ``ACPAgent.stats_provider`` is typed as (05 §Truncation)."""

    provider: SessionStatsProvider = PiSessionStats()
    assert provider is not None


async def test_the_provider_reports_what_the_file_says(tmp_path: Path) -> None:
    session(tmp_path)
    provider = PiSessionStats(tmp_path)

    reported = await provider.stats(SID, "/some/cwd")
    assert reported == SessionStats(
        model=MODEL, input_tokens=100, output_tokens=50, cost=0.0
    )
    assert await provider.final_stop_reason(SID, "/some/cwd") == "endTurn"


async def test_the_provider_reports_truncation(tmp_path: Path) -> None:
    """The one answer the façade turns into a failed run (05 §Truncation)."""

    session(tmp_path, entries=[assistant(stop_reason="length")])
    assert await PiSessionStats(tmp_path).final_stop_reason(SID, None) == "length"


async def test_a_session_with_no_file_is_not_determined(tmp_path: Path) -> None:
    """No file is ``None``, which the façade omits rather than zero-fills."""

    provider = PiSessionStats(tmp_path)
    assert await provider.stats(SID, None) is None
    assert await provider.final_stop_reason(SID, None) is None


async def test_the_root_is_resolved_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider built at import time still reads today's directory.

    An agent class carries one ``stats_provider`` instance for the life
    of the process, and the environment that says where pi keeps its
    sessions is read when the container starts, not when the class body
    ran.
    """

    provider = PiSessionStats()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    session(tmp_path / "agent" / "sessions")

    reported = await provider.stats(SID, None)
    assert reported is not None and reported.input_tokens == 100
