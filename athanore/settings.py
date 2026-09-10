"""Configuration via :class:`AthanoreSettings` (pydantic-settings).

Precedence is CLI kwargs > environment (``ATHANORE_*``) > ``athanore.toml``
in the root path > defaults. The legacy ``ARTIFICER_*`` names are still
read as a fallback to the ``ATHANORE_*`` names, with a deprecation
warning, for one minor version (02 §Configuration).
"""

from __future__ import annotations

import ipaddress
import os
import re
import tomllib
import warnings
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

# Deprecated env names mapped to ``(field name, modern env name)``. Read
# only when the ``ATHANORE_*`` name is unset (02 §Configuration).
_LEGACY_ENV = {
    "ARTIFICER_HOST": ("host", "ATHANORE_HOST"),
    "ARTIFICER_PORT": ("port", "ATHANORE_PORT"),
    "ARTIFICER_DB": ("db_url", "ATHANORE_DB_URL"),
}


def _translate_legacy_db_url(value: str) -> str:
    """Translate a legacy ``ARTIFICER_DB`` value to a SQLAlchemy URL.

    v0 treated ``ARTIFICER_DB`` as a filesystem path
    (``athanore/server.py:139``), so a bare path must become
    ``sqlite+aiosqlite:///{path}``. A value that already carries a URL
    scheme is left untouched (D72).
    """
    if "://" in value:
        return value
    return f"sqlite+aiosqlite:///{value}"


class Retention(BaseModel):
    """Retention windows, pruned by a background job (07 §Retention).

    Every field carries a ``description``. It is what the published
    settings reference renders (`docs/site/src/reference/settings.md`),
    so the table in 02 §Configuration and the wording here are edited
    together (D214).
    """

    events_days: int = Field(
        default=30,
        description="How many days an event is kept before the retention job "
        "prunes it.",
    )
    stream_days: int = Field(
        default=14,
        description="How many days a stream chunk is kept before the retention "
        "job prunes it.",
    )


class _LegacyEnvSource(PydanticBaseSettingsSource):
    """Reads the deprecated ``ARTIFICER_*`` env names as a fallback.

    Sits just below the ``ATHANORE_*`` env source, so a modern name always
    wins; the warning is emitted only when a legacy value is actually used.
    """

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for legacy, (field_name, modern) in _LEGACY_ENV.items():
            if field_name in self.current_state:
                continue
            value = os.environ.get(legacy)
            if value is None:
                continue
            warnings.warn(
                f"`{legacy}` is deprecated; use `{modern}` instead.",
                DeprecationWarning,
                stacklevel=3,
            )
            if field_name == "db_url":
                values[field_name] = _translate_legacy_db_url(value)
            else:
                values[field_name] = value
        return values


class _TomlSource(TomlConfigSettingsSource):
    """Reads ``athanore.toml`` resolved against ``root_path``.

    ``root_path`` is known from the init and env sources that run before
    this one; the file therefore lives next to the root path rather than
    the process cwd when the two differ. Subclasses
    ``TomlConfigSettingsSource`` so the ``toml_file`` config key is not
    reported as unused, but skips the base class's eager cwd-relative read.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        PydanticBaseSettingsSource.__init__(self, settings_cls)
        configured = settings_cls.model_config.get("toml_file") or "athanore.toml"
        if isinstance(configured, (str, Path)):
            self.toml_file_name = Path(configured)
        else:
            self.toml_file_name = Path("athanore.toml")

    # Read by ``athanore serve``, not settings (02 §athanore.toml layout).
    _IGNORED_TABLES = frozenset({"pools", "workflows"})
    # Never settable in TOML: the token is a secret (12), the command is a
    # test hook (05) (02 §athanore.toml layout).
    _REFUSED_KEYS = frozenset({"operator_token", "agent_command"})

    def __call__(self) -> dict[str, Any]:
        root = self.current_state.get("root_path")
        root_path = Path(root) if root is not None else Path.cwd()
        toml_path = root_path / self.toml_file_name
        if not toml_path.is_file():
            return {}
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)

        known = frozenset(self.settings_cls.model_fields)
        for key in data:
            if key in self._IGNORED_TABLES:
                continue
            if key in self._REFUSED_KEYS:
                raise SettingsError(
                    f"`{key}` is refused in {toml_path}; set it via the "
                    "environment or the CLI, never TOML."
                )
            if key not in known:
                raise SettingsError(
                    f"unknown top-level key `{key}` in {toml_path} "
                    "(a typo must not silently fall back to a default)."
                )
        return {
            key: value for key, value in data.items() if key not in self._IGNORED_TABLES
        }


#: A bare host with an optional port: letters, digits, dots, dashes.
#: Deliberately no `_`, no userinfo and no brackets — a CSP source is a
#: host, and everything else in that grammar is a way of smuggling one
#: directive inside another.
_HOST = re.compile(r"^[A-Za-z0-9.-]+(?::\d{1,5})?$")


class AthanoreSettings(BaseSettings):
    """Typed configuration with documented defaults (02 §Configuration).

    Every field carries a ``description``, worded from the Notes column
    of 02 §Configuration, and the two fields whose default is computed in
    :meth:`_compute_derived_defaults` say what leaving them unset
    resolves to. The descriptions are what the published settings
    reference renders (`docs/site/src/reference/settings.md`), which is
    why there is no second table to keep in step: 02 is the
    specification, this is what a reader is shown, and they are edited
    together (D214).
    """

    model_config = SettingsConfigDict(
        env_prefix="ATHANORE_",
        toml_file="athanore.toml",
        extra="ignore",
    )

    root_path: Path = Field(
        default_factory=Path.cwd,
        description="The directory everything else is anchored to: the "
        "database, the `.athanore/` state directory, `athanore.toml`, and a "
        "workflow's default project directories. Unset, it is the working "
        "directory the process was started in.",
    )
    db_url: str | None = Field(
        default=None,
        description="The SQLAlchemy URL of the store. Unset, it resolves to "
        "`sqlite+aiosqlite:///{root_path}/athanore.db`; a Postgres install "
        "sets `postgresql+asyncpg://...` and needs the `postgres` extra.",
    )
    host: str = Field(
        default="127.0.0.1",
        description="The interface to bind. A loopback bind needs no operator "
        "credential; binding anywhere else requires an operator token.",
    )
    port: int = Field(default=4002, description="The port to bind.")
    public_url: str | None = Field(
        default=None,
        description="The base URL agents and plugins are told to reach this "
        "server at. Unset, it resolves to `http://{host}:{port}`; set it when "
        "agents run in a container or on another machine.",
    )
    operator_token: SecretStr | None = Field(
        default=None,
        description="The operator credential, sent as a bearer token. Needed "
        "only for a non-loopback host or with `require_token`; `athanore token "
        "rotate` generates one into `.athanore/token`. Refused in "
        "`athanore.toml`.",
    )
    require_token: bool = Field(
        default=False,
        description="Force operator authentication even on a loopback bind — "
        "for a reverse proxy sitting in front of one.",
    )
    body_limit: int = Field(
        default=1_048_576,
        description="The largest request body accepted, in bytes. Beyond it "
        "the API answers 413.",
    )
    sse_replay_cap: int = Field(
        default=5000,
        description="The most events replayed to a client reconnecting with a "
        "cursor before it is told to resynchronise instead.",
    )
    workers: int = Field(
        default=1,
        description="The capacity of the default pool: how many attempts run "
        "at once when a workflow names no pool of its own.",
    )
    max_retries: int = Field(
        default=3,
        description="How many times a failed attempt is retried before the "
        "task is dead-lettered. A node overrides it per node.",
    )
    agent_timeout: float = Field(
        default=10800,
        description="How long one agent run may take, in seconds, before the "
        "engine cancels it. A node overrides it per node.",
    )
    permission_policy: Literal["ask", "auto_allow", "auto_deny"] | None = Field(
        default=None,
        description="A global override of every agent class's permission "
        "policy. Unset, each class keeps its own.",
    )
    agent_command: str | list[str] | None = Field(
        default=None,
        description="Replaces every `ACPAgent.command` at spawn — the hook "
        "that runs a workflow against a fake agent. Environment and CLI only; "
        "refused in `athanore.toml`.",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Browser origins allowed to call the API cross-site. For "
        "development; empty is the default and the right value in production.",
    )
    #: Origins a plugin's `custom` pane may load scripts, styles and
    #: fonts from, on top of ``'self'`` (09 §Escape hatch, D211).
    #:
    #: Three immutable, versioned CDNs by default, so a plugin author gets
    #: a library without a build step and without every install needing an
    #: `athanore.toml`. ``[]`` restores the airtight policy; a bare
    #: ``"https:"`` opens it to any origin, which is supported and not
    #: recommended — `'self'` plus these three is what keeps an injected
    #: ``<script src>`` from reaching code, and that backstop is worth
    #: more than the convenience of a fourth CDN.
    #:
    #: ``connect-src`` is deliberately never widened: a CDN script may
    #: run, but may only talk back to this server.
    plugin_cdns: list[str] = Field(
        default_factory=lambda: [
            "https://cdn.jsdelivr.net",
            "https://unpkg.com",
            "https://esm.sh",
        ],
        description="Origins a plugin's custom pane may load scripts, styles "
        "and fonts from, on top of `'self'`. An empty list is the airtight "
        'policy; `["https:"]` opens it to any origin over that scheme. '
        "`connect-src` is never widened, so a CDN script may run but may only "
        "talk back to this server.",
    )
    log_format: Literal["pretty", "json"] | None = Field(
        default=None,
        description="How the log is rendered. Unset, it resolves to `pretty` "
        "when stderr is a terminal and `json` when it is not.",
    )
    stream_flush_interval: float = Field(
        default=0.4,
        description="How long agent output is batched before it is flushed to "
        "the task stream, in seconds.",
    )
    run_migrations: bool = Field(
        default=True,
        description="Whether the server migrates the schema before it serves. "
        "False leaves that to `athanore db upgrade`.",
    )
    forwarded_allow_ips: str | None = Field(
        default=None,
        description="Which proxies' `X-Forwarded-*` headers uvicorn trusts, "
        "as a comma-separated list of addresses or `*`. Unset, none are "
        "trusted.",
    )
    retention: Retention = Field(
        default_factory=Retention,
        description="How long events and stream chunks are kept before the "
        "retention job prunes them.",
    )

    @field_validator("plugin_cdns")
    @classmethod
    def _origins_only(cls, values: list[str]) -> list[str]:
        """Each entry must be a bare ``https://host[:port]`` origin.

        A CSP is a header built by joining strings, so an entry carrying
        a space, a semicolon or a quote is a directive the operator did
        not write. Parsing it as a URL and rebuilding it from the parts
        is what makes that impossible rather than merely unlikely — and
        it refuses a path, which CSP would ignore and an author would
        assume was honoured.
        """

        cleaned: list[str] = []
        for value in values:
            bare = value.strip()
            # `https:` alone is a CSP *scheme source*: any origin over
            # that scheme. Supported so "allow everything" is one entry
            # rather than a fork of this function, and left un-parsed
            # because there is no host in it to check.
            if bare in ("https:", "http:"):
                cleaned.append(bare)
                continue
            parsed = urlparse(bare)
            if parsed.scheme not in ("https", "http") or not parsed.netloc:
                raise ValueError(
                    f"plugin_cdns entries are origins like "
                    f"'https://cdn.jsdelivr.net'; {value!r} is not one"
                )
            if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise ValueError(
                    f"a plugin_cdns entry is an origin, with no path: {value!r}"
                )
            # `urlparse` takes everything up to the first `/` as the
            # netloc, so `https://x.net; script-src *` parses "cleanly"
            # with the injection sitting inside the host. The host has to
            # be checked as a host.
            if not _HOST.match(parsed.netloc):
                raise ValueError(
                    f"{parsed.netloc!r} is not a host[:port]; a plugin_cdns "
                    f"entry may not carry a space, a quote or a semicolon"
                )
            cleaned.append(f"{parsed.scheme}://{parsed.netloc}")
        return cleaned

    @model_validator(mode="after")
    def _compute_derived_defaults(self) -> AthanoreSettings:
        if self.db_url is None:
            self.db_url = f"sqlite+aiosqlite:///{self.root_path}/athanore.db"
        if self.public_url is None:
            self.public_url = f"http://{self.host}:{self.port}"
        return self

    @property
    def is_loopback(self) -> bool:
        if self.host == "localhost":
            return True
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return False

    @property
    def token_file(self) -> Path:
        return self.root_path / ".athanore" / "token"

    @property
    def effective_operator_token(self) -> SecretStr | None:
        if self.operator_token is not None:
            return self.operator_token
        if self.token_file.is_file():
            return SecretStr(self.token_file.read_text().strip())
        return None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _LegacyEnvSource(settings_cls),
            _TomlSource(settings_cls),
            file_secret_settings,
        )
