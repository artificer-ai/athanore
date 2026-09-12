"""`FakeACPAgent`: a real subprocess speaking ACP over stdio, from a script.

13 §Fakes. This is the only "agent" CI runs, so everything downstream —
the ACP lifecycle tests of T039, the API tests, the E2E suite, the phase
gates that run the examples with no model in the loop — is exactly as
trustworthy as this file. That is why the scenario vocabulary below is a
**contract** rather than a convenience, and why an unknown key is an
error: a typo in a scenario would otherwise produce a green test that
asserted nothing.

It is a *script*, not a class. Nothing here imports the rest of the
package — it is spawned as ``python athanore/testing/fake_acp.py
--scenario <path>``, which is what :func:`athanore.testing.scenario`
builds — so it stays stdlib-only and starts in milliseconds. The one
exception is the ``mcp`` client, imported inside the handler that needs
it (``mcp_calls``) and nowhere else.

Wire framing, verified against `agent-client-protocol` 0.12: newline
delimited JSON-RPC 2.0 on stdin/stdout; responses carry
``{"jsonrpc", "id", "result"}``; notifications carry
``{"method": "session/update", "params": {"sessionId", "update": {…}}}``
with the ``sessionUpdate`` discriminator.

Scenario selection, in order:

- ``--scenario <path>`` or ``$ATHANORE_FAKE_SCENARIO`` — one file for the
  whole process;
- ``$ATHANORE_FAKE_SCENARIOS=<dir>`` — one file **per node**, picked when
  a prompt arrives: ``<workflow>.<node>.json``, then ``<node>.json``,
  then ``default.json``. The workflow and the node come from the kickoff
  prompt the fake is handed, which is why 19 is byte-exact. ``initialize``
  and ``session/new`` land before any prompt, so they are answered from
  ``default.json`` — the only scenario that exists at that point.

**One run, one script.** Every content block — text, thoughts, tool
calls, permissions, elicitations, the environment echo, the MCP calls —
is emitted on the **first** prompt turn and not repeated on the repair
turns that follow it (D122). ``sleep_s``, ``stop_reason`` and ``usage``
belong to a turn rather than to the run, so they apply to every one; and
a repair turn is what submits ``repair_submit``.

**A session held across several prompts** (23 §The fake, T090). A held
session's prompts are not repair turns, so ``prompts: [scenario, ...]``
scripts them: the n-th element scripts the n-th *body* prompt of the
session and the last one repeats for every prompt past the end of the
list. Each element is a scenario less the keys the process consumes
before or outside any prompt (:data:`PROMPT_KEYS`), which stay on the
outer scenario. On the wire a repair turn and the next prompt are both
``session/prompt``, so the fake tells them apart by the text: a prompt
opening with 19 §Repair turn's first words (:data:`REPAIR_MARKER`) is a
repair of the prompt before it and posts that script's ``repair_submit``;
anything else is the next prompt and runs the next script's first turn.
Without the key nothing changes: the second ``session/prompt`` is the
run's repair turn, as above.

**Sessions that survive the process** (23 §The fake, D257). A continued
run is a second process, so ``sessions: {dir, resume?: bool}`` puts the
session on disk. With it, ``initialize`` advertises ``loadSession: true``
(and ``sessionCapabilities.resume: {}`` when ``resume`` is true), and
``session/new`` creates ``<dir>/<sessionId>.json``: a JSON list of update
objects, one ``user_message_chunk`` recorded per ``session/prompt`` (its
text blocks concatenated) and every update the session sends, in the
order they happen. ``session/load`` re-sends that list verbatim before
answering ``{configOptions}``; ``session/resume`` answers without a
replay, and only when advertised. Both adopt the id, record
``mcpServers`` as ``session/new`` does, and keep appending to the same
file. An unknown id is ``-32602`` ``no such session: <id>``; an
unadvertised method is ``-32601``, as any unknown method. The scenario
still scripts one run, so the second process's first prompt runs the
first-turn script again (D122).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

#: The whole scenario vocabulary of 13 §Fakes. Anything else is an error.
SCENARIO_KEYS = frozenset(
    {
        "text",
        "thoughts",
        "tool_calls",
        "permissions",
        "elicitations",
        "config_options",
        "reject_config",
        "usage",
        "stop_reason",
        "sleep_s",
        "session_file",
        "log",
        "submit",
        "repair_submit",
        "request_log",
        "response_log",
        "env_echo",
        "advertise_mcp",
        "mcp_calls",
        "sessions",
        "prompts",
    }
)

#: What a per-prompt scenario under ``prompts`` may say: a turn's script.
#: The keys the process consumes before or outside any prompt — the
#: session's capabilities and options, what is read at
#: ``session/set_config_option``, what is written at start, the two logs
#: — belong to the outer scenario and are refused here rather than
#: silently ignored (13 §Fakes: a key that does nothing is a green test
#: that asserted nothing).
PROMPT_KEYS = SCENARIO_KEYS - {
    "prompts",
    "sessions",
    "advertise_mcp",
    "config_options",
    "reject_config",
    "session_file",
    "request_log",
    "response_log",
}

#: The first words of 19 §Repair turn, both texts. Under ``prompts`` a
#: ``session/prompt`` opening with them is a repair turn of the prompt
#: before it, not the next prompt of the session.
REPAIR_MARKER = "Your turn ended, but no valid structured result"

#: The stop reasons a scenario may name (ACP ``StopReason``, the subset 13
#: fixes). ``end_turn`` is what a turn ends with when nothing says
#: otherwise.
STOP_REASONS = ("end_turn", "refusal", "cancelled")

#: The claude-agent-acp option order, and the reason ``"reject_first"``
#: exists as a shorthand: rejection is listed **first**, so a façade that
#: selected an option by index rather than by kind would deny every tool
#: call (20 §Finding 1).
REJECT_FIRST = [
    {"optionId": "reject", "name": "Deny", "kind": "reject_once"},
    {"optionId": "allow", "name": "Allow Once", "kind": "allow_once"},
    {"optionId": "allow_always", "name": "Always Allow", "kind": "allow_always"},
]

#: What ``session/new`` advertises when a scenario names no
#: ``config_options``: pi's two, with pi's categories, so a façade
#: resolving an id *by category* (05 §Agent classes) has something to
#: resolve without every scenario restating it.
DEFAULT_CONFIG_OPTIONS = [
    {
        "id": "model",
        "category": "model",
        "values": ["fake/fake-model", "fake/fake-model-mini"],
    },
    {
        "id": "thought_level",
        "category": "thought_level",
        "values": ["off", "low", "high"],
    },
]

#: The pi session file's token counts. Fixed rather than scriptable: 13's
#: ``session_file`` vocabulary is ``{dir, cost?, stop_reason?, model?}``,
#: and a provider test that wants other numbers writes its own fixture.
SESSION_INPUT_TOKENS = 100
SESSION_OUTPUT_TOKENS = 50

#: The line the environment echo opens with, so a scrub test can find it
#: in the transcript. ACP has no wire form for a ``notice`` chunk —
#: ``notice`` is a kind the façade itself writes (05, 07) — so the listing
#: travels as an assistant message chunk under this marker (D122).
ENV_MARKER = "[env]"

_KICKOFF_RE = re.compile(r'stage "([^"]*)" of workflow "([^"]*)"')


class ScenarioError(ValueError):
    """A scenario names a key, or a shape, the vocabulary does not have."""


# --------------------------------------------------------------------------
# Scenario validation. Loud, because a silent typo is a test that passes
# without exercising anything.
# --------------------------------------------------------------------------


def validate_scenario(
    scenario: Any, *, where: str = "scenario", keys: frozenset[str] = SCENARIO_KEYS
) -> dict[str, Any]:
    """Check ``scenario`` against 13 §Fakes, or raise :exc:`ScenarioError`.

    Every key is checked, and so is the shape under it: the elements of
    ``permissions``, the fields of ``usage``, the keys of a
    ``session_file``. A misspelling anywhere in a scenario is a failure
    at the point it is written rather than a run that quietly did less.
    ``keys`` is the vocabulary allowed here — the whole of it for a
    scenario, :data:`PROMPT_KEYS` for an element of ``prompts``.
    """

    if not isinstance(scenario, dict):
        raise ScenarioError(f"{where}: expected a JSON object, got {_kind(scenario)}")
    unknown = sorted(key for key in scenario if key not in keys)
    if unknown:
        raise ScenarioError(
            f"{where}: unknown key(s) {', '.join(unknown)}; "
            f"the vocabulary is {', '.join(sorted(keys))}"
        )

    for key in ("text", "thoughts"):
        if key in scenario:
            _strings(scenario[key], f"{where}.{key}")
    if "reject_config" in scenario:
        _strings(scenario["reject_config"], f"{where}.reject_config")
    for key in ("log", "request_log", "response_log"):
        if key in scenario and not isinstance(scenario[key], str):
            raise ScenarioError(f"{where}.{key}: expected a string")
    for key in ("env_echo", "advertise_mcp"):
        if key in scenario and not isinstance(scenario[key], bool):
            raise ScenarioError(f"{where}.{key}: expected true or false")
    if "sleep_s" in scenario and not _is_number(scenario["sleep_s"]):
        raise ScenarioError(f"{where}.sleep_s: expected a number")
    if "stop_reason" in scenario and scenario["stop_reason"] not in STOP_REASONS:
        raise ScenarioError(
            f"{where}.stop_reason: expected one of {', '.join(STOP_REASONS)}"
        )

    _validate_tool_calls(scenario.get("tool_calls"), where)
    _validate_permissions(scenario.get("permissions"), where)
    _validate_elicitations(scenario.get("elicitations"), where)
    _validate_config_options(scenario.get("config_options"), where)
    _validate_usage(scenario.get("usage"), where)
    _validate_session_file(scenario.get("session_file"), where)
    _validate_mcp_calls(scenario.get("mcp_calls"), where)
    _validate_sessions(scenario.get("sessions"), where)
    _validate_prompts(scenario.get("prompts"), where)
    return scenario


def _validate_tool_calls(value: Any, where: str) -> None:
    if value is None or isinstance(value, int) and not isinstance(value, bool):
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.tool_calls: expected an integer or a list")
    for index, call in enumerate(value):
        _fields(
            call, {"title", "kind", "raw_input"}, set(), f"{where}.tool_calls[{index}]"
        )


def _validate_permissions(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.permissions: expected a list")
    for index, request in enumerate(value):
        at = f"{where}.permissions[{index}]"
        if request == "reject_first":
            continue
        _fields(request, {"options", "title"}, {"options"}, at)
        options = request["options"]
        if not isinstance(options, list) or not options:
            raise ScenarioError(f"{at}.options: expected a non-empty list")
        for spot, option in enumerate(options):
            _fields(
                option,
                {"kind", "option_id", "name"},
                {"kind"},
                f"{at}.options[{spot}]",
            )


def _validate_elicitations(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.elicitations: expected a list")
    for index, elicitation in enumerate(value):
        at = f"{where}.elicitations[{index}]"
        _fields(elicitation, {"schema", "mode"}, set(), at)
        mode = elicitation.get("mode", "form")
        if mode not in ("form", "url"):
            raise ScenarioError(f"{at}.mode: expected 'form' or 'url'")
        if mode == "form" and not isinstance(elicitation.get("schema"), dict):
            raise ScenarioError(f"{at}.schema: a form elicitation needs a schema")


def _validate_config_options(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.config_options: expected a list")
    for index, option in enumerate(value):
        at = f"{where}.config_options[{index}]"
        _fields(option, {"id", "category", "values"}, {"id", "category", "values"}, at)
        _strings(option["values"], f"{at}.values")
        if not option["values"]:
            raise ScenarioError(f"{at}.values: expected at least one value")


def _validate_usage(value: Any, where: str) -> None:
    if value is None:
        return
    at = f"{where}.usage"
    _fields(
        value, {"input", "output", "thought", "cache_read"}, {"input", "output"}, at
    )
    for key, number in value.items():
        if isinstance(number, bool) or not isinstance(number, int):
            raise ScenarioError(f"{at}.{key}: expected an integer")


def _validate_session_file(value: Any, where: str) -> None:
    if value is None:
        return
    at = f"{where}.session_file"
    _fields(value, {"dir", "cost", "stop_reason", "model"}, {"dir"}, at)
    if not isinstance(value["dir"], str):
        raise ScenarioError(f"{at}.dir: expected a string")
    if "cost" in value and not _is_number(value["cost"]):
        raise ScenarioError(f"{at}.cost: expected a number")


def _validate_sessions(value: Any, where: str) -> None:
    if value is None:
        return
    at = f"{where}.sessions"
    _fields(value, {"dir", "resume"}, {"dir"}, at)
    if not isinstance(value["dir"], str):
        raise ScenarioError(f"{at}.dir: expected a string")
    if "resume" in value and not isinstance(value["resume"], bool):
        raise ScenarioError(f"{at}.resume: expected true or false")


def _validate_prompts(value: Any, where: str) -> None:
    """``prompts`` is a non-empty list of per-prompt scenarios (23 §The fake)."""

    if value is None:
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.prompts: expected a list")
    if not value:
        raise ScenarioError(f"{where}.prompts: expected at least one scenario")
    for index, item in enumerate(value):
        validate_scenario(item, where=f"{where}.prompts[{index}]", keys=PROMPT_KEYS)


def _validate_mcp_calls(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ScenarioError(f"{where}.mcp_calls: expected a list")
    for index, call in enumerate(value):
        at = f"{where}.mcp_calls[{index}]"
        _fields(call, {"tool", "args"}, {"tool"}, at)
        if not isinstance(call["tool"], str):
            raise ScenarioError(f"{at}.tool: expected a string")
        if not isinstance(call.get("args", {}), dict):
            raise ScenarioError(f"{at}.args: expected a JSON object")


def _fields(value: Any, allowed: set[str], required: set[str], at: str) -> None:
    """``value`` is an object whose keys are in ``allowed`` and cover ``required``."""

    if not isinstance(value, dict):
        raise ScenarioError(f"{at}: expected a JSON object, got {_kind(value)}")
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise ScenarioError(
            f"{at}: unknown key(s) {', '.join(unknown)}; "
            f"expected {', '.join(sorted(allowed))}"
        )
    missing = sorted(key for key in required if key not in value)
    if missing:
        raise ScenarioError(f"{at}: missing key(s) {', '.join(missing)}")


def _strings(value: Any, at: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ScenarioError(f"{at}: expected a list of strings")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _kind(value: Any) -> str:
    return type(value).__name__


def load_scenario(path: str) -> dict[str, Any]:
    """Read and validate one scenario file."""

    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise ScenarioError(f"scenario {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"scenario {path}: not JSON ({exc})") from exc
    return validate_scenario(raw, where=f"scenario {path}")


def resolve_scenario(directory: str, workflow: str, node: str) -> dict[str, Any]:
    """The per-node scenario of 13 §Running examples on the fake.

    ``<workflow>.<node>.json``, then ``<node>.json``, then
    ``default.json``. A directory with none of the three is an empty
    scenario: an agent that says nothing and ends its turn.
    """

    for name in (f"{workflow}.{node}.json", f"{node}.json", "default.json"):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return load_scenario(candidate)
    return {}


# --------------------------------------------------------------------------
# The pi session file, so `examples/pi/stats.py` has something real to read.
# --------------------------------------------------------------------------


def write_session_file(spec: Mapping[str, Any], session_id: str, text: str) -> str:
    """Write a pi-layout session JSONL and return its path (D27, 05).

    The real layout is ``<root>/<encoded-cwd>/<ts>_<sessionId>.jsonl``,
    and the header's ``id`` is the session id the fake returned from
    ``session/new`` — that is what a provider matches on. It is written
    at **startup**, before any prompt, so a run that timed out or was
    killed still leaves a real file behind for the stats path to read.

    ``cost`` absent from the scenario means the file carries no cost key,
    which is the case a provider must report as *unknown* rather than as
    zero (`AGENTS.md` §Real data only).
    """

    directory = os.path.join(spec["dir"], "--fake-cwd--")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"2026-01-01T00-00-00Z_{session_id}.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    model = spec.get("model", "fake/fake-model")
    provider, _, model_id = str(model).partition("/")
    usage: dict[str, Any] = {
        "input": SESSION_INPUT_TOKENS,
        "output": SESSION_OUTPUT_TOKENS,
        "cacheRead": 0,
        "cacheWrite": 0,
        "reasoning": 0,
        "totalTokens": SESSION_INPUT_TOKENS + SESSION_OUTPUT_TOKENS,
    }
    if "cost" in spec:
        cost = spec["cost"]
        usage["cost"] = {
            "input": cost,
            "output": cost,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": cost,
        }
    lines: list[dict[str, Any]] = [
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": now,
            "cwd": "/fake-cwd",
        },
        {
            "type": "model_change",
            "id": "mc1",
            "parentId": None,
            "timestamp": now,
            "provider": provider,
            "modelId": model_id,
        },
        {
            "type": "message",
            "id": "m1",
            "parentId": "mc1",
            "timestamp": now,
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text or "fake agent"}],
                "provider": provider,
                "model": model,
                "usage": usage,
                "stopReason": spec.get("stop_reason", "endTurn"),
                "timestamp": time.time() * 1000,
            },
        },
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


# --------------------------------------------------------------------------
# The agent.
# --------------------------------------------------------------------------


class FakeACPAgent:
    """One process, one session, one scenario at a time.

    The methods are the ACP methods. ``run()`` is the read loop; a
    request the fake itself initiates (a permission, an elicitation)
    blocks inside :meth:`request` on a nested read of the same stdin,
    which is exactly what a real adapter does and what makes the client's
    answer observable in ``response_log``.
    """

    def __init__(self, scenario: Mapping[str, Any], scenarios_dir: str | None) -> None:
        self.scenario: dict[str, Any] = dict(scenario)
        self.scenarios_dir = scenarios_dir
        self.session_id = str(uuid.uuid4())
        #: ``session/prompt``s received, repair turns included.
        self.turn = 0
        #: Body prompts answered under ``prompts`` — the index into it.
        self.prompted = 0
        #: The scenario the current turn is scripted by: the outer one,
        #: or the ``prompts`` element this prompt (or its repair) is on.
        self.script: dict[str, Any] = self.scenario
        self.session_file_written = False
        self.mcp_servers: list[dict[str, Any]] = []
        self.config: list[dict[str, Any]] = []
        # The session's file and its content (23 §The fake). Held here and
        # not in `self.scenario`, which select_scenario() replaces on the
        # first prompt in directory mode: a swap must not stop a recording.
        self.session_path: str | None = None
        self.history: list[dict[str, Any]] = []
        self._next_id = 1000

    # -- framing ---------------------------------------------------------

    def send(self, message: Mapping[str, Any]) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def reply(self, request_id: Any, result: Mapping[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def fail(self, request_id: Any, code: int, message: str) -> None:
        print(f"fake_acp: {message}", file=sys.stderr, flush=True)
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    def update(self, update: Mapping[str, Any]) -> None:
        self.send(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": self.session_id, "update": dict(update)},
            }
        )
        if self.session_path is not None:
            self._record(update)

    # -- the session file (23 §The fake, D257) ------------------------------

    def _record(self, update: Mapping[str, Any]) -> None:
        """Append one update object to the session's file."""

        self.history.append(dict(update))
        self._flush()

    def _flush(self) -> None:
        """Rewrite the file from `history`, atomically.

        The in-memory list is the truth and a session in CI is a few dozen
        entries, so a full rewrite is simpler than patching a JSON list in
        place; the rename is what keeps a reader in another process from
        ever seeing half of one.
        """

        assert self.session_path is not None
        tmp = f"{self.session_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.history, handle)
        os.replace(tmp, self.session_path)

    def _start_recording(self, sessions: Mapping[str, Any]) -> None:
        """`session/new` under `sessions`: the file exists, empty, from here."""

        os.makedirs(sessions["dir"], exist_ok=True)
        self.session_path = os.path.join(sessions["dir"], f"{self.session_id}.json")
        self.history = []
        self._flush()

    def chunk(self, kind: str, text: str) -> None:
        self.update({"sessionUpdate": kind, "content": {"type": "text", "text": text}})

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Send an agent-initiated request and block for the client's answer.

        A nested read on the same stdin: the client answers this id before
        it answers anything else, because that is the only thing the
        agent is waiting for. Messages that are not this answer are
        dropped — a client that cancels a turn mid-permission is a T039a
        path, and there is nothing useful for the fake to do with them.
        """

        request_id = self._next_id
        self._next_id += 1
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        while True:
            line = sys.stdin.readline()
            if not line:
                raise RuntimeError(f"stdin closed while awaiting {method}")
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                self._log_line("response_log", message)
                return message

    def _log_line(self, key: str, entry: Mapping[str, Any]) -> None:
        path = self.scenario.get(key)
        if not path:
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    # -- lifecycle -------------------------------------------------------

    def run(self) -> None:
        if "session_file" in self.scenario:
            self.write_session_file()
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in message or "error" in message:
                # An answer to a request this process initiated, already
                # taken by request(). Never answer an answer.
                continue
            request_id = message.get("id")
            method = message.get("method")
            self._log_line(
                "request_log", {"method": method, "params": message.get("params")}
            )
            if request_id is None:
                continue  # a notification: session/cancel and friends
            self.dispatch(request_id, str(method), message.get("params") or {})

    def dispatch(self, request_id: Any, method: str, params: Mapping[str, Any]) -> None:
        if method == "initialize":
            self.reply(request_id, self.initialize())
        elif method == "session/new":
            self.reply(request_id, self.new_session(params))
        elif method == "session/set_config_option":
            self.set_config_option(request_id, params)
        elif method == "session/prompt":
            self.prompt(request_id, params)
        elif method in ("session/load", "session/resume"):
            self.load_session(request_id, method, params)
        else:
            self.fail(request_id, -32601, f"method not found: {method}")

    def initialize(self) -> dict[str, Any]:
        advertised = bool(self.scenario.get("advertise_mcp"))
        sessions = self.scenario.get("sessions")
        capabilities: dict[str, Any] = {
            "loadSession": sessions is not None,
            "promptCapabilities": {},
            "mcpCapabilities": {"http": advertised, "sse": False},
        }
        if sessions is not None and sessions.get("resume"):
            # `SessionResumeCapabilities` is an empty object in the SDK.
            capabilities["sessionCapabilities"] = {"resume": {}}
        return {
            "protocolVersion": 1,
            "agentCapabilities": capabilities,
            "agentInfo": {"name": "fake-acp", "version": "1"},
        }

    def _open(self, params: Mapping[str, Any]) -> None:
        """What `session/new`, `session/load` and `session/resume` share.

        The `mcpServers` carried are what `mcp_calls` connects to, and the
        config options are the scenario's, whichever method opened the
        session (23 §The fake).
        """

        servers = params.get("mcpServers") or []
        self.mcp_servers = [server for server in servers if isinstance(server, dict)]
        self.config = [
            _config_option(spec)
            for spec in self.scenario.get("config_options", DEFAULT_CONFIG_OPTIONS)
        ]

    def new_session(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._open(params)
        sessions = self.scenario.get("sessions")
        if sessions is not None:
            self._start_recording(sessions)
        return {"sessionId": self.session_id, "configOptions": self.config}

    def load_session(
        self, request_id: Any, method: str, params: Mapping[str, Any]
    ) -> None:
        """`session/load` and `session/resume` (23 §The fake, D257).

        Both adopt the id and open the session as `session/new` would;
        only `load` re-sends the file first. The replay goes through
        :meth:`send` and never :meth:`update`, or it would append itself
        to the file it is replaying.
        """

        replay = method == "session/load"
        sessions = self.scenario.get("sessions")
        if sessions is None or (not replay and not sessions.get("resume")):
            # Unadvertised is not found: the same fact, the same message.
            self.fail(request_id, -32601, f"method not found: {method}")
            return
        session_id = params.get("sessionId")
        if not isinstance(session_id, str):
            self.fail(request_id, -32602, "sessionId: expected a string")
            return
        path = os.path.join(sessions["dir"], f"{session_id}.json")
        if not os.path.isfile(path):
            self.fail(request_id, -32602, f"no such session: {session_id}")
            return
        try:
            with open(path, encoding="utf-8") as handle:
                history = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            self.fail(request_id, -32603, f"session {path}: {exc}")
            return
        if not isinstance(history, list) or not all(
            isinstance(entry, dict) for entry in history
        ):
            self.fail(request_id, -32603, f"session {path}: not a list of updates")
            return
        # Adopted before any replay, so the re-sent updates carry this id.
        self.session_id = session_id
        self.session_path = path
        self.history = list(history)
        self._open(params)
        if replay:
            for entry in self.history:
                self.send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {"sessionId": self.session_id, "update": entry},
                    }
                )
        self.reply(request_id, {"configOptions": self.config})

    def set_config_option(self, request_id: Any, params: Mapping[str, Any]) -> None:
        config_id = params.get("configId")
        if config_id in self.scenario.get("reject_config", []):
            self.fail(request_id, -32602, f"cannot set {config_id}")
            return
        for option in self.config:
            if option["id"] == config_id:
                option["currentValue"] = params.get("value")
                break
        else:
            self.fail(request_id, -32602, f"no such config option: {config_id}")
            return
        self.reply(request_id, {"configOptions": self.config})

    # -- the turn --------------------------------------------------------

    def prompt(self, request_id: Any, params: Mapping[str, Any]) -> None:
        text = "".join(
            block.get("text", "")
            for block in params.get("prompt") or []
            if isinstance(block, dict)
        )
        if self.session_path is not None:
            # Recorded, not sent: a live turn does not echo the user's
            # message, but a replay carries it, as pi's and Claude's do.
            self._record(
                {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": text},
                }
            )
        if self.scenarios_dir is not None:
            try:
                self.scenario = self.select_scenario(text)
            except ScenarioError as exc:
                self.fail(request_id, -32603, str(exc))
                return
        turn = self.turn
        self.turn += 1
        prompts = self.scenario.get("prompts")
        if prompts is None:
            # One run, one script: the first turn is content, every later
            # one a repair (D122).
            self.script, first = self.scenario, turn == 0
        elif text.startswith(REPAIR_MARKER) and self.prompted:
            # A repair of the prompt `self.script` is on; the list stands.
            first = False
        else:
            # The next body prompt: the next script, the last repeating.
            self.script = prompts[min(self.prompted, len(prompts) - 1)]
            self.prompted += 1
            first = True

        sleep_s = self.script.get("sleep_s")
        if sleep_s:
            time.sleep(float(sleep_s))

        try:
            if first:
                self.first_turn()
            elif "repair_submit" in self.script:
                self.post("submit", self.script["repair_submit"])
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self.fail(request_id, -32603, f"{type(exc).__name__}: {exc}")
            return

        result: dict[str, Any] = {
            "stopReason": self.script.get("stop_reason", "end_turn")
        }
        usage = self.script.get("usage")
        if usage is not None:
            result["usage"] = _usage(usage)
        self.reply(request_id, result)

    def select_scenario(self, prompt_text: str) -> dict[str, Any]:
        """The per-node scenario for the node this prompt names (13)."""

        assert self.scenarios_dir is not None
        match = _KICKOFF_RE.search(prompt_text)
        node, workflow = (match.group(1), match.group(2)) if match else ("", "")
        scenario = resolve_scenario(self.scenarios_dir, workflow, node)
        if "session_file" in scenario and not self.session_file_written:
            write_session_file(
                scenario["session_file"],
                self.session_id,
                " ".join(scenario.get("text", [])) or "fake agent",
            )
            self.session_file_written = True
        return scenario

    def first_turn(self) -> None:
        """Everything a script says for one prompt, once (D122, 23 §The fake)."""

        if "log" in self.script:
            self.post("log", {"text": self.script["log"]})
        if "submit" in self.script:
            submissions = self.script["submit"]
            if not isinstance(submissions, list):
                submissions = [submissions]
            for payload in submissions:
                self.post("submit", payload)
        self.ask_permissions()
        self.ask_elicitations()
        for thought in self.script.get("thoughts", []):
            self.chunk("agent_thought_chunk", thought)
        for text in self.script.get("text", []):
            self.chunk("agent_message_chunk", text)
        if self.script.get("env_echo"):
            self.echo_env()
        self.emit_tool_calls()
        self.call_mcp_tools()

    def ask_permissions(self) -> None:
        for index, spec in enumerate(self.script.get("permissions", [])):
            if spec == "reject_first":
                title, options = f"fake tool {index + 1}", list(REJECT_FIRST)
            else:
                title = spec.get("title", f"fake tool {index + 1}")
                options = [_option(option) for option in spec["options"]]
            self.request(
                "session/request_permission",
                {
                    "sessionId": self.session_id,
                    "toolCall": {
                        "toolCallId": f"perm_{index}",
                        "title": title,
                        "kind": "execute",
                        "rawInput": {"command": f"echo {index + 1}"},
                    },
                    "options": options,
                },
            )

    def ask_elicitations(self) -> None:
        for index, spec in enumerate(self.script.get("elicitations", [])):
            message = f"fake question {index + 1}"
            if spec.get("mode", "form") == "url":
                self.request(
                    "elicitation/create",
                    {
                        "sessionId": self.session_id,
                        "message": message,
                        "mode": "url",
                        "elicitationId": f"elicit_{index}",
                        "url": f"https://example.invalid/elicitation/{index}",
                    },
                )
            else:
                self.request(
                    "elicitation/create",
                    {
                        "sessionId": self.session_id,
                        "message": message,
                        "mode": "form",
                        "requestedSchema": spec["schema"],
                    },
                )

    def echo_env(self) -> None:
        """List the environment, for the scrub assertions of 05 and T039."""

        listing = "\n".join(
            f"{name}={value}" for name, value in sorted(os.environ.items())
        )
        self.chunk("agent_message_chunk", f"{ENV_MARKER}\n{listing}")

    def emit_tool_calls(self) -> None:
        for index, call in enumerate(_tool_calls(self.script.get("tool_calls"))):
            call_id = f"call_{index}"
            start: dict[str, Any] = {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "title": call.get("title", f"fake tool {index + 1}"),
                "kind": call.get("kind", "other"),
                "status": "in_progress",
            }
            if "raw_input" in call:
                start["rawInput"] = call["raw_input"]
            self.update(start)
            self.update(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "status": "completed",
                }
            )

    def call_mcp_tools(self) -> None:
        """Call each named tool on the MCP server ``session/new`` carried.

        The ``mcp`` tier of 05, end to end: the façade passed a server, an
        agent that can speak MCP connects to it and reaches its task
        through the tools rather than through curl. The results come back
        as tool-call updates, which is the transcript's ``tool_result``.
        """

        calls = self.script.get("mcp_calls")
        if not calls:
            return
        server = next(
            (s for s in self.mcp_servers if s.get("type", "http") == "http"), None
        )
        if server is None:
            raise RuntimeError("mcp_calls: session/new carried no HTTP MCP server")
        outputs = _mcp_results(server, calls)
        for index, (call, output) in enumerate(zip(calls, outputs, strict=True)):
            call_id = f"mcp_{index}"
            self.update(
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": call_id,
                    "title": call["tool"],
                    "kind": "other",
                    "status": "in_progress",
                    "rawInput": call.get("args", {}),
                }
            )
            self.update(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "status": "completed",
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": output},
                        }
                    ],
                }
            )

    # -- the task API ----------------------------------------------------

    def post(self, path: str, payload: Any) -> None:
        """POST ``payload`` to ``$ATHANORE_TASK_URL/<path>`` (13, 19).

        The token and the base come from the environment 19 §Environment
        guarantees, not from the prompt: the ``mcp`` and ``native`` tiers
        put neither in the text, and a fake that parsed the curl lines
        could only ever exercise one tier. The HTTP status lands in
        ``response_log`` so a test can assert the 422 that drives a
        repair turn.
        """

        base = os.environ.get("ATHANORE_TASK_URL")
        token = os.environ.get("ATHANORE_TASK_TOKEN")
        if not base or not token:
            self._log_line(
                "response_log",
                {path: None, "error": "ATHANORE_TASK_URL/TOKEN are not set"},
            )
            print(
                f"fake_acp: cannot {path}: ATHANORE_TASK_URL/TOKEN are not set",
                file=sys.stderr,
                flush=True,
            )
            return
        request = urllib.request.Request(
            f"{base.rstrip('/')}/{path}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Athanore-Token": token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except urllib.error.URLError as exc:
            self._log_line("response_log", {path: None, "error": str(exc.reason)})
            print(f"fake_acp: {path} failed: {exc.reason}", file=sys.stderr, flush=True)
            return
        self._log_line("response_log", {path: status})

    def write_session_file(self) -> None:
        text = " ".join(self.scenario.get("text", [])) or "fake agent"
        write_session_file(self.scenario["session_file"], self.session_id, text)
        self.session_file_written = True


def _config_option(spec: Mapping[str, Any]) -> dict[str, Any]:
    """One advertised ``session/new`` config option, ACP's select shape.

    A selectable value is ``{value, name}``: that is
    ``SessionConfigSelectOption`` in the SDK, and ``configOptions`` is
    parsed with ``skip_invalid_items``, so an option spelled any other
    way is silently dropped by a real client rather than refused — and a
    façade resolving an id by category would find nothing to resolve.
    """

    values = list(spec["values"])
    return {
        "type": "select",
        "id": spec["id"],
        "name": spec["id"],
        "category": spec["category"],
        "currentValue": values[0],
        "options": [{"value": value, "name": value} for value in values],
    }


def _option(spec: Mapping[str, Any]) -> dict[str, Any]:
    """One permission option: ``kind`` is required, the rest is derived."""

    kind = spec["kind"]
    return {
        "optionId": spec.get("option_id", kind),
        "name": spec.get("name", kind.replace("_", " ").title()),
        "kind": kind,
    }


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, int):
        return [{} for _ in range(value)]
    return list(value)


def _usage(usage: Mapping[str, Any]) -> dict[str, int]:
    """13's ``usage`` in the SDK's ``PromptResponse.usage`` spelling."""

    out = {
        "inputTokens": usage["input"],
        "outputTokens": usage["output"],
        "totalTokens": usage["input"] + usage["output"],
    }
    if "thought" in usage:
        out["thoughtTokens"] = usage["thought"]
    if "cache_read" in usage:
        out["cachedReadTokens"] = usage["cache_read"]
    return out


def _mcp_results(
    server: Mapping[str, Any], calls: Iterable[Mapping[str, Any]]
) -> list[str]:
    """Call each tool on ``server`` with the real ``mcp`` client.

    Imported here and nowhere else: the fake is spawned per agent run and
    an MCP client is worth its import only in the scenarios that ask for
    one.
    """

    import asyncio

    from mcp import ClientSession

    # `create_mcp_http_client` is re-exported here at runtime but is not in
    # the module's `__all__`; the alternative is the SDK's private
    # `mcp.shared._httpx_utils`, which is a worse thing to depend on.
    from mcp.client.streamable_http import (
        create_mcp_http_client,  # pyright: ignore[reportPrivateImportUsage]
        streamable_http_client,
    )

    headers = {
        header["name"]: header["value"] for header in server.get("headers") or []
    }

    async def call_all() -> list[str]:
        results: list[str] = []
        async with create_mcp_http_client(headers=headers) as http_client:
            async with streamable_http_client(
                server["url"], http_client=http_client
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for call in calls:
                        result = await session.call_tool(
                            call["tool"], dict(call.get("args") or {})
                        )
                        results.append(_result_text(result))
        return results

    return asyncio.run(call_all())


def _result_text(result: Any) -> str:
    """The text of an MCP tool result, whatever the content shape."""

    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
    if not parts:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return json.dumps(structured)
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A fake ACP agent (13 §Fakes).")
    parser.add_argument("--scenario", default=None, help="a scenario JSON file")
    args = parser.parse_args(argv)

    path = args.scenario or os.environ.get("ATHANORE_FAKE_SCENARIO")
    directory = os.environ.get("ATHANORE_FAKE_SCENARIOS")
    try:
        if path:
            scenario = load_scenario(path)
        elif directory and os.path.isfile(os.path.join(directory, "default.json")):
            # Nothing has named a node yet: `initialize` and `session/new`
            # land before the first prompt, and `default.json` is the only
            # scenario that exists at that point (13).
            scenario = load_scenario(os.path.join(directory, "default.json"))
        else:
            scenario = {}
    except ScenarioError as exc:
        print(f"fake_acp: {exc}", file=sys.stderr, flush=True)
        return 2
    FakeACPAgent(scenario, directory if not path else None).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
