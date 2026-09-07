"""pi's session files, read as a :class:`SessionStatsProvider` (D27).

What no protocol carries — what a session cost, and whether its final
turn was cut off at the model's token limit — is written by the agent
into its own session log, in the agent's own format. The MVP read pi's
JSONL out of ``~/.pi/agent/sessions`` from inside the package; v1 states
the protocol in ``athanore.agents.stats`` and ships the reader here,
because "nothing in ``athanore/`` depends on pi" is the rule the small
core is made of (02 §Small core, D14).

**Unknown is omitted, here as well.** Every field of
:class:`~athanore.agents.stats.SessionStats` this module fills is one it
read; a counter it did not find stays ``None``, which the façade then
leaves out of the stats entry rather than writing a zero
(`AGENTS.md` §Real data only). The distinction matters twice over in a
session file: a ``cost`` object without a ``total`` is a shape this
reader does not understand and yields nothing, while a ``total`` of
``0.0`` from a local model is a measurement and is kept.

**Two layouts, one authority.** pi has written its sessions two ways, and
both are still on disk::

    <root>/<encoded-cwd>/<timestamp>_<session-id>.jsonl
    <root>/<encoded-cwd>/<timestamp>_<session-id>/<hash>/run-0/session.jsonl

Both are matched. ``<encoded-cwd>`` is pi's own encoding of the
directory the session ran in, and this module deliberately does not
reproduce it: guessing an encoding is how a provider comes to read the
wrong file confidently. The search is over every cwd directory, the
newest matching file wins, and the winner has to *say* it is the session
asked for — its first line is a ``session`` header carrying the id — so a
uuid prefix collision or a stale sibling is rejected rather than parsed.

Nothing here raises. A provider is called from the ``finally`` of an
agent run (05 §Stats entry): a session file that is missing, truncated
mid-write by a killed agent, or unreadable is an unknown measurement, and
an unknown measurement must not fail the task it is about.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from athanore.agents.stats import SessionStats

__all__ = [
    "PiSessionStats",
    "default_sessions_root",
    "final_assistant_stop_reason",
    "find_session_file",
    "parse_session_file",
]

#: What pi calls the stop reason of a turn that hit the model's output
#: cap. 05 §Truncation is about exactly this value: the final turn spent
#: its whole budget (typically inside a reasoning block) and ended
#: without the tool call or the submission the run needed.
LENGTH = "length"


def default_sessions_root() -> Path:
    """Where pi keeps its sessions on this machine.

    ``PI_CODING_AGENT_DIR`` is pi's own override of its home directory
    and the dev image sets it, so it is read first; ``~/.pi/agent`` is
    the default pi itself falls back to.
    """

    configured = os.environ.get("PI_CODING_AGENT_DIR")
    root = Path(configured) if configured else Path.home() / ".pi" / "agent"
    return root / "sessions"


def find_session_file(
    session_id: str, sessions_root: Path | None = None
) -> Path | None:
    """The session file for ``session_id``, or ``None``.

    Both layouts above are globbed, the candidates are ordered by mtime
    and the first whose header names ``session_id`` is returned. Never
    raises: an unreadable root, a vanished file and a header that is not
    JSON are all "no session file", which is what an unknown measurement
    looks like from here.
    """

    root = sessions_root if sessions_root is not None else default_sessions_root()
    if not session_id or not root.is_dir():
        return None
    try:
        candidates = [
            *root.glob(f"**/*_{session_id}.jsonl"),
            *root.glob(f"**/*_{session_id}/**/*.jsonl"),
        ]
        ordered = sorted(
            candidates, key=lambda path: path.stat().st_mtime, reverse=True
        )
    except OSError:
        return None
    for candidate in ordered:
        if _header_id(candidate) == session_id:
            return candidate
    return None


def _header_id(path: Path) -> str | None:
    """The ``id`` of the file's first line, when that line is a header."""

    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
        header = json.loads(first) if first.strip() else None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(header, dict):
        return None
    found = header.get("id")
    return found if isinstance(found, str) else None


def parse_session_file(path: Path) -> SessionStats:
    """Sum what one pi session file actually reports.

    ``input_tokens`` and ``output_tokens`` are the per-message
    ``usage.input`` / ``usage.output`` summed over the session's
    **assistant** messages. ``usage.totalTokens`` is deliberately not
    summed: it counts the context the turn re-read, so a sum of it counts
    the same tokens once per turn. The façade derives the total from the
    two sides instead (:func:`~athanore.agents.stats.merge_usage`).

    ``cost`` is the sum of ``usage.cost.total``, and only when at least
    one message carried a numeric one. ``model`` is
    ``provider/modelId`` of the last ``model_change`` entry — a session
    may switch models, and the last switch is what answered last — and
    falls back to the ``provider/model`` the last assistant message
    names.

    Every line is parsed on its own, so a file pi was killed halfway
    through writing gives up only its final, half-written line.
    """

    tokens: dict[str, int] = {}
    cost: float | None = None
    switched: str | None = None
    answered: str | None = None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                entry = _entry(line)
                if entry is None:
                    continue
                kind = entry.get("type")
                if kind == "model_change":
                    switched = _model(entry.get("provider"), entry.get("modelId"))
                    continue
                if kind != "message":
                    continue
                message = entry.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                named = _model(message.get("provider"), message.get("model"))
                answered = named or answered
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                for field, key in (
                    ("input", "input_tokens"),
                    ("output", "output_tokens"),
                ):
                    counted = _number(usage.get(field))
                    if counted is not None:
                        tokens[key] = tokens.get(key, 0) + int(counted)
                spent = _cost(usage.get("cost"))
                if spent is not None:
                    cost = (cost or 0.0) + spent
    except OSError:
        pass
    return SessionStats(
        model=switched or answered,
        input_tokens=tokens.get("input_tokens"),
        output_tokens=tokens.get("output_tokens"),
        cost=cost,
    )


def final_assistant_stop_reason(path: Path) -> str | None:
    """The ``stopReason`` of the last assistant message in ``path``.

    The last assistant message is the one the session ended on, so
    :data:`LENGTH` here means the run's final turn was cut off at the
    model's output cap. ``None`` is *not determined* — an unreadable
    file, or a session whose assistant messages carry no stop reason —
    and the façade treats not determined as not truncated, because this
    decides whether a run that may have worked is reported failed.
    """

    last: str | None = None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                entry = _entry(line)
                if entry is None or entry.get("type") != "message":
                    continue
                message = entry.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                reason = message.get("stopReason")
                if isinstance(reason, str):
                    last = reason
    except OSError:
        pass
    return last


def _entry(line: str) -> dict[str, Any] | None:
    """One JSONL line as an object, or ``None`` if it is not one."""

    stripped = line.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _model(provider: Any, name: Any) -> str | None:
    """``provider/model``, when both halves are there."""

    if isinstance(provider, str) and provider and isinstance(name, str) and name:
        return f"{provider}/{name}"
    return None


def _number(value: Any) -> float | None:
    """``value`` as a number, excluding ``bool`` (an ``int`` to Python)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _cost(value: Any) -> float | None:
    """The ``total`` of one message's cost object, when it has one.

    A cost object without a numeric ``total`` yields nothing rather than
    a zero: pi writes the per-part breakdown before it knows the total
    for a provider that reports none, and a ``$0.0000`` invented there
    would be indistinguishable from a local model's real zero.
    """

    if not isinstance(value, dict):
        return None
    return _number(value.get("total"))


class PiSessionStats:
    """The pi reader as the façade's provider (05 §Truncation detection).

    Set it on an agent class and the two fields ACP cannot carry arrive::

        class Builder(ACPAgent):
            command = ["npx", "-y", "pi-acp@0.0.33"]
            stats_provider = PiSessionStats()

    ``sessions_root`` is for a pi told to keep its sessions somewhere
    else (``--session-dir``); by default it is
    :func:`default_sessions_root`, resolved on **every** call rather than
    once at construction, so a provider built at import time still reads
    the right directory when the environment says so later.

    ``cwd`` is part of the protocol and is not used here: the directory
    pi files a session under is an encoding of the cwd that this module
    does not reproduce (see the module docstring). The search covers
    every cwd directory instead, and the session header is what decides.

    Both methods are ``async`` and both do file I/O, so the work runs in
    a worker thread: this is called from the ``finally`` of an agent run,
    on the engine's event loop, with a task waiting on the other side of
    it.
    """

    def __init__(self, sessions_root: Path | str | None = None) -> None:
        self.sessions_root = Path(sessions_root) if sessions_root is not None else None

    def _root(self) -> Path:
        return self.sessions_root or default_sessions_root()

    async def stats(self, session_id: str, cwd: str | None) -> SessionStats | None:
        """Tokens, cost and the model that answered, or ``None``."""

        return await asyncio.to_thread(self._stats, session_id)

    async def final_stop_reason(self, session_id: str, cwd: str | None) -> str | None:
        """The final turn's stop reason; :data:`LENGTH` means truncated."""

        return await asyncio.to_thread(self._stop_reason, session_id)

    def _stats(self, session_id: str) -> SessionStats | None:
        path = find_session_file(session_id, self._root())
        return None if path is None else parse_session_file(path)

    def _stop_reason(self, session_id: str) -> str | None:
        path = find_session_file(session_id, self._root())
        return None if path is None else final_assistant_stop_reason(path)
