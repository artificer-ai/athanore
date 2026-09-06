"""Configuration via :class:`AthanoreSettings` (pydantic-settings).

Precedence is CLI kwargs > environment (``ATHANORE_*``) > ``athanore.toml``
in the root path > defaults. The legacy ``ARTIFICER_*`` names are still
read as a fallback to the ``ATHANORE_*`` names, with a deprecation
warning, for one minor version (02 §Configuration).
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
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
    scheme is left untouched (D71).
    """
    if "://" in value:
        return value
    return f"sqlite+aiosqlite:///{value}"


class Retention(BaseModel):
    """Retention windows, pruned by a background job (07 §Retention)."""

    events_days: int = 30
    stream_days: int = 14


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


class AthanoreSettings(BaseSettings):
    """Typed configuration with documented defaults (02 §Configuration)."""

    model_config = SettingsConfigDict(
        env_prefix="ATHANORE_",
        toml_file="athanore.toml",
        extra="ignore",
    )

    root_path: Path = Field(default_factory=Path.cwd)
    db_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 4002
    public_url: str | None = None
    operator_token: SecretStr | None = None
    require_token: bool = False
    body_limit: int = 1_048_576
    sse_replay_cap: int = 5000
    workers: int = 1
    max_retries: int = 3
    agent_timeout: float = 10800
    permission_policy: Literal["ask", "auto_allow", "auto_deny"] | None = None
    agent_command: str | list[str] | None = None
    cors_origins: list[str] = Field(default_factory=list)
    log_format: Literal["pretty", "json"] | None = None
    stream_flush_interval: float = 0.4
    run_migrations: bool = True
    forwarded_allow_ips: str | None = None
    retention: Retention = Field(default_factory=Retention)

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
