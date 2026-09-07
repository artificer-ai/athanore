"""The CLI's end of the one wire contract (11 §Client connection).

Everything the CLI knows about Athanore it learns over HTTP. There is no
second path: the CLI does not import the engine, does not open the
database, and does not read a run out of a file. That is what makes it a
useful test of the API — a verb that cannot be written here is a gap in
the wire contract rather than something to reach around (02 §One wire
contract).

Three things live here, and nothing else:

- **Where the server is.** :func:`resolve` is the whole of 11 §Client
  connection's precedence — ``--url``/``--token``, then ``ATHANORE_URL``/
  ``ATHANORE_TOKEN``, then ``~/.config/athanore/config.toml``, then the
  loopback default — resolved per field, so a ``--url`` on the command
  line and a token from the file are an ordinary combination.
- **How it is asked.** :class:`Client` is httpx with the bearer header,
  a timeout, and ``HTTPTransport(retries=2)``. That transport is the
  *ceiling*: retries belong to the engine (rule 3), and what httpx
  retries here is establishing a connection, never a request the server
  may already have acted on.
- **What a refusal means.** Every non-2xx answer becomes an
  :class:`ApiClientError` carrying the ``error`` message, the stable
  ``code`` and the body (08 §Conventions), which
  :func:`athanore.cli.output.dispatch` turns into exit status 1. A
  connection that could not be made stays an :class:`httpx.TransportError`
  and becomes exit status 3: "the server refused you" and "there is no
  server there" are different answers and the CLI never conflates them.

:meth:`Client.events` is the SSE half of the same contract, and it is
the one the tests read the stream through too — ``athanore logs -f`` and
a test that asserts what the stream carried parse frames with the same
code, so a bug in that parser cannot hide behind a second implementation.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx

__all__ = [
    "CONFIG_KEYS",
    "DEFAULT_URL",
    "RETRIES",
    "TIMEOUT",
    "ApiClientError",
    "Client",
    "Config",
    "ServerEvent",
    "config_path",
    "is_http_url",
    "read_config",
    "resolve",
]

#: Where a server is when nobody said otherwise: the loopback bind
#: `AthanoreSettings` defaults to, which needs no operator token (11).
DEFAULT_URL: Final = "http://127.0.0.1:4002"

#: Connection-level retries, and the only retries a client of this API
#: performs (02 §Library choices, AGENTS.md §Retries belong to the
#: engine). httpx retries the *connect*, so a request the server has
#: already seen is never sent twice.
RETRIES: Final = 2

#: How long a single request may take. Generous for a local server, and
#: short enough that a hung one is an error rather than a hang. The
#: event stream overrides the read half of it: an idle SSE connection is
#: the normal case, not a stall.
TIMEOUT: Final = 30.0

#: What ``~/.config/athanore/config.toml`` may hold. An unknown key is
#: refused for the reason `athanore.toml`'s are (`settings._TomlSource`):
#: a typo that silently fell back to a default would look like the
#: server ignoring a token that was there all along.
CONFIG_KEYS: Final = frozenset({"url", "token"})

#: The schemes the API is reachable over. A ``--url`` that names another
#: one (or none at all) is refused where it was typed, rather than
#: surfacing as an unreachable server.
_SCHEMES: Final = frozenset({"http", "https"})


class ApiClientError(RuntimeError):
    """The server answered, and the answer was a refusal (08 §Conventions).

    ``str(exc)`` is the ``error`` field — the human sentence the API
    wrote — because that is what 11 §Exit codes says the CLI prints. The
    rest of the body is kept rather than flattened into the message: a
    verb that wants to branch on ``code`` can, and :attr:`details`
    renders the per-field ``errors`` of a 422 without the caller having
    to know the shape.

    A body that is not the documented shape (a proxy's HTML, an empty
    502) still produces one of these, with a message built from the
    status: a client that raised something else there would make "the
    server said no" depend on who was in front of the server.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body

    @property
    def details(self) -> list[str]:
        """The ``errors`` of a validation failure as ``loc: msg`` lines.

        Empty for every other refusal. A 422's message is "validation
        failed" and the useful half is in ``errors`` (08 §Conventions),
        so the CLI prints these underneath it.
        """

        body = self.body
        if not isinstance(body, Mapping):
            return []
        errors = body.get("errors")
        if not isinstance(errors, list):
            return []
        lines: list[str] = []
        for error in errors:
            if not isinstance(error, Mapping):
                lines.append(str(error))
                continue
            loc = error.get("loc")
            where = ".".join(str(part) for part in loc) if isinstance(loc, list) else ""
            message = str(error.get("msg", "")).strip()
            lines.append(f"{where}: {message}" if where else message)
        return [line for line in lines if line]


@dataclass(frozen=True, slots=True)
class Config:
    """A resolved connection: where the server is, and what proves who you are."""

    url: str
    token: str | None = None


@dataclass(frozen=True, slots=True)
class ServerEvent:
    """One frame of ``GET /api/events`` (08 §Events).

    ``id`` is ``None`` exactly when the frame carried no ``id:`` line —
    an ephemeral ``task.stream``, or the ``resync`` control frame — which
    is what makes it usable as a reconnect cursor: the caller keeps the
    last ``id`` it saw and passes it back as ``after``.
    """

    name: str
    data: Any
    id: int | None = None


def config_path() -> Path:
    """``~/.config/athanore/config.toml``, or its ``XDG_CONFIG_HOME`` form.

    11 spells the path with ``~/.config`` because that is where it is on
    a machine that has not moved it; ``XDG_CONFIG_HOME`` is what "there"
    means when it has, and honouring it is the difference between a file
    the operator can find and one the CLI insists on.
    """

    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "athanore" / "config.toml"


def read_config(path: Path | None = None) -> dict[str, str]:
    """The ``url`` and ``token`` of the config file, or ``{}`` if there is none.

    A file that is not there is not an error — the common case is no
    file at all. A file that is there and cannot be read as this is:
    unparseable TOML, an unknown key, a value that is not a string.
    Reporting it beats treating a broken config as an absent one, which
    is how an operator ends up debugging the server for a typo in their
    own file.
    """

    path = config_path() if path is None else path
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ApiClientError(f"{path} could not be read: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ApiClientError(f"{path} is not valid TOML: {exc}") from exc
    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise ApiClientError(
            f"unknown key {unknown[0]!r} in {path}; it holds "
            f"{' and '.join(sorted(CONFIG_KEYS))} and nothing else."
        )
    for key, value in data.items():
        if not isinstance(value, str):
            raise ApiClientError(f"`{key}` in {path} must be a string.")
    return {key: str(value) for key, value in data.items()}


def is_http_url(value: str) -> bool:
    """Whether ``value`` is a URL this client could reach a server at."""

    scheme, separator, rest = value.partition("://")
    return bool(separator) and scheme.lower() in _SCHEMES and bool(rest.strip("/"))


def resolve(
    url: str | None = None,
    token: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    config_file: Path | None = None,
) -> Config:
    """The connection, from the highest source that names each half (11).

    Per field, not per source: ``--url`` with a token in the config file
    is the ordinary way to talk to a second server, and a resolution that
    took both from whichever source spoke first would silently drop the
    token. The config file is read only when something is still
    unresolved, so a run that was told everything never touches the disk.
    """

    environment = os.environ if env is None else env
    if url is None:
        url = environment.get("ATHANORE_URL") or None
    if token is None:
        token = environment.get("ATHANORE_TOKEN") or None
    if url is None or token is None:
        stored = read_config(config_file)
        if url is None:
            url = stored.get("url") or None
        if token is None:
            token = stored.get("token") or None
    if url is None:
        url = DEFAULT_URL
    elif not is_http_url(url):
        raise ApiClientError(
            f"{url!r} is not an http(s) URL; the server is named as e.g. {DEFAULT_URL}."
        )
    return Config(url=url, token=token)


def _error(response: httpx.Response) -> ApiClientError:
    """The refusal ``response`` reports, as this module's exception."""

    body: Any = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None
    message: str | None = None
    code: str | None = None
    if isinstance(body, Mapping):
        raw_message = body.get("error")
        raw_code = body.get("code")
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
        if isinstance(raw_code, str):
            code = raw_code
    if message is None:
        # Not the documented shape: a proxy, a bare 502, a body that is
        # not JSON at all. The status is then the only true thing there
        # is to say, so it is what gets said.
        reason = response.reason_phrase or "error"
        message = f"the server answered {response.status_code} {reason}".rstrip()
    return ApiClientError(message, status=response.status_code, code=code, body=body)


def _result(response: httpx.Response) -> Any:
    """The decoded body of a successful response, or the refusal it was."""

    if not response.is_success:
        raise _error(response)
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise ApiClientError(
            f"the server answered {response.status_code} with a body that is not JSON",
            status=response.status_code,
        ) from exc


def _parse_sse(lines: Iterable[str]) -> Iterator[ServerEvent]:
    """The SSE lines of 08 §Events as :class:`ServerEvent`s.

    Field parsing is the wire format's: ``:`` opens a comment (the
    keep-alive, which carries nothing and dispatches nothing), one
    optional space after the colon is part of the framing rather than of
    the value, and a blank line dispatches what has accumulated.

    The id is reset with the rest of the buffer rather than carried
    forward as a browser's ``EventSource`` carries it. That is what makes
    ``ServerEvent.id is None`` mean "this frame had no ``id:``", which is
    precisely the distinction 08 relies on for ephemeral events.
    """

    name: str | None = None
    data: list[str] = []
    event_id: int | None = None
    for line in lines:
        if not line:
            if name is not None or data:
                yield ServerEvent(
                    name=name or "message", data=_frame_data(data), id=event_id
                )
            name, data, event_id = None, [], None
            continue
        if line.startswith(":"):
            continue
        # `partition` is the wire format's own rule: a line with no
        # colon is a field with an empty value.
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            try:
                event_id = int(value)
            except ValueError:
                # Ids ascend as integers (`EventRepo`); anything else did
                # not come from this API, and inventing a cursor from it
                # would replay from the wrong place on the next connect.
                raise ApiClientError(
                    f"the event stream sent {value!r} as an event id"
                ) from None
        # Any other field name is ignored, as the wire format requires.


def _frame_data(data: list[str]) -> Any:
    """The ``data:`` lines of one frame, decoded.

    Every frame this API sends carries JSON — an ``EventEnvelope``, or
    the ``resync`` reason (08 §Events) — so anything else is a server
    that is not Athanore, and saying so beats handing a verb a string
    where it expects an event.
    """

    text = "\n".join(data)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ApiClientError(
            "the event stream sent a frame whose data is not JSON"
        ) from exc


class Client:
    """The API, as the CLI and its tests call it.

    ``Client()`` resolves its connection from the environment and the
    config file; ``Client(url, token)`` is what a verb builds from its
    ``--url`` and ``--token``. Either way the resolution is
    :func:`resolve`'s and happens once, so ``client.url`` is the address
    a verb can print.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = TIMEOUT,
        env: Mapping[str, str] | None = None,
        config_file: Path | None = None,
    ) -> None:
        config = resolve(url, token, env=env, config_file=config_file)
        self.url = config.url
        self.token = config.token
        headers = {"accept": "application/json"}
        if config.token is not None:
            headers["authorization"] = f"Bearer {config.token}"
        self._http = httpx.Client(
            base_url=config.url,
            headers=headers,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=RETRIES),
            follow_redirects=True,
        )

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection pool."""

        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        """One call, decoded, or the refusal it was.

        ``params`` drops its ``None`` values, so a verb passes its
        optional filters straight through without assembling a dict of
        the ones the operator happened to give.
        """

        response = self._http.request(
            method.upper(), path, params=_params(params), json=body
        )
        return _result(response)

    def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        body: Any = None,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.request("POST", path, params=params, body=body)

    def patch(
        self,
        path: str,
        body: Any = None,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.request("PATCH", path, params=params, body=body)

    def delete(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, params=params)

    def events(
        self,
        after: int | None = None,
        names: str | Sequence[str] | None = None,
        *,
        run: str | None = None,
    ) -> Iterator[ServerEvent]:
        """``GET /api/events``, frame by frame, until the server closes it.

        ``after`` replays what was missed and then goes live; ``names``
        and ``run`` are the server-side filters of 08 §Events, so a
        follower of one run reads one run's events rather than filtering
        the whole feed itself.

        The read timeout is dropped for the length of the stream: an idle
        connection is what a healthy stream looks like between events,
        and the server's own keep-alive is what says it is still there.
        """

        selected = names if names is None or isinstance(names, str) else ",".join(names)
        params = _params({"after": after, "run": run, "names": selected})
        with self._http.stream(
            "GET",
            "/api/events",
            params=params,
            timeout=httpx.Timeout(TIMEOUT, read=None),
        ) as response:
            if not response.is_success:
                response.read()
                raise _error(response)
            yield from _parse_sse(response.iter_lines())


def _params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """``params`` without the keys nobody set."""

    if not params:
        return {}
    return {key: value for key, value in params.items() if value is not None}
