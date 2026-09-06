"""Tests for :mod:`athanore.settings`."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import pytest

from athanore.settings import AthanoreSettings, Retention


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ``ATHANORE_*`` and ``ARTIFICER_*`` so tests are deterministic.

    The dev container carries ``ATHANORE_HOST`` / ``ATHANORE_PORT``, which
    would otherwise shadow the documented defaults and make the legacy-shim
    tests environment-dependent.
    """
    for key in list(os.environ):
        if key.startswith(("ATHANORE_", "ARTIFICER_")):
            monkeypatch.delenv(key, raising=False)


def test_defaults() -> None:
    settings = AthanoreSettings()
    assert settings.root_path == Path.cwd()
    assert settings.db_url == f"sqlite+aiosqlite:///{Path.cwd()}/athanore.db"
    assert settings.host == "127.0.0.1"
    assert settings.port == 4002
    assert settings.public_url == "http://127.0.0.1:4002"
    assert settings.operator_token is None
    assert settings.require_token is False
    assert settings.body_limit == 1_048_576
    assert settings.sse_replay_cap == 5000
    assert settings.workers == 1
    assert settings.max_retries == 3
    assert settings.agent_timeout == 10800
    assert settings.permission_policy is None
    assert settings.cors_origins == []
    assert settings.log_format is None
    assert settings.stream_flush_interval == 0.4
    assert settings.run_migrations is True
    assert settings.forwarded_allow_ips is None
    assert settings.retention == Retention(events_days=30, stream_days=14)


def test_kwargs_beat_env_beat_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "athanore.toml"
    toml_path.write_text(
        'host = "toml-host"\nport = 1111\nmax_retries = 9\n'
        "[retention]\nevents_days = 7\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATHANORE_HOST", "env-host")
    monkeypatch.setenv("ATHANORE_PORT", "2222")

    # env beats toml.
    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.host == "env-host"
    assert settings.port == 2222
    # toml fills what env left unset.
    assert settings.max_retries == 9
    assert settings.retention.events_days == 7

    # kwargs beat env and toml.
    settings = AthanoreSettings(root_path=tmp_path, host="kwarg-host", port=3333)
    assert settings.host == "kwarg-host"
    assert settings.port == 3333
    assert settings.max_retries == 9


def test_toml_path_resolved_against_root_path(tmp_path: Path) -> None:
    toml_path = tmp_path / "athanore.toml"
    toml_path.write_text("workers = 7\n", encoding="utf-8")
    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.workers == 7


def test_computed_public_url_and_db_url() -> None:
    settings = AthanoreSettings(host="0.0.0.0", port=8080, root_path=Path("/tmp/root"))
    assert settings.public_url == "http://0.0.0.0:8080"
    assert settings.db_url == "sqlite+aiosqlite:////tmp/root/athanore.db"


def test_explicit_db_url_and_public_url_win(tmp_path: Path) -> None:
    toml_path = tmp_path / "athanore.toml"
    toml_path.write_text(
        'db_url = "postgresql+asyncpg://u:p@h/db"\n'
        'public_url = "https://example.com"\n',
        encoding="utf-8",
    )
    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.db_url == "postgresql+asyncpg://u:p@h/db"
    assert settings.public_url == "https://example.com"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert AthanoreSettings(host=host).is_loopback is expected


def test_legacy_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICER_PORT", "4321")
    monkeypatch.setenv("ARTIFICER_HOST", "0.0.0.0")
    monkeypatch.setenv("ARTIFICER_DB", "sqlite+aiosqlite:///legacy.db")

    with pytest.warns(DeprecationWarning) as records:
        settings = AthanoreSettings()
    messages = {str(record.message) for record in records}
    assert any("ARTIFICER_PORT" in message for message in messages)
    assert any("ARTIFICER_HOST" in message for message in messages)
    assert any("ARTIFICER_DB" in message for message in messages)
    assert settings.port == 4321
    assert settings.host == "0.0.0.0"
    assert settings.db_url == "sqlite+aiosqlite:///legacy.db"


def test_legacy_env_does_not_override_modern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICER_PORT", "4321")
    monkeypatch.setenv("ATHANORE_PORT", "9999")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        settings = AthanoreSettings()
    assert settings.port == 9999


def test_legacy_env_unset_emits_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    for legacy in ("ARTIFICER_PORT", "ARTIFICER_DB", "ARTIFICER_HOST"):
        monkeypatch.delenv(legacy, raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        AthanoreSettings()


def test_effective_operator_token_from_setting(tmp_path: Path) -> None:
    settings = AthanoreSettings(root_path=tmp_path, operator_token="secret-value")
    assert settings.effective_operator_token is not None
    assert settings.effective_operator_token.get_secret_value() == "secret-value"


def test_effective_operator_token_from_file(tmp_path: Path) -> None:
    token_dir = tmp_path / ".athanore"
    token_dir.mkdir()
    (token_dir / "token").write_text("file-secret\n", encoding="utf-8")
    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.effective_operator_token is not None
    assert settings.effective_operator_token.get_secret_value() == "file-secret"


def test_effective_operator_token_absent(tmp_path: Path) -> None:
    settings = AthanoreSettings(root_path=tmp_path)
    assert settings.effective_operator_token is None


def test_token_file_path(tmp_path: Path) -> None:
    assert (
        AthanoreSettings(root_path=tmp_path).token_file
        == tmp_path / ".athanore" / "token"
    )


def test_secret_does_not_leak_in_repr(tmp_path: Path) -> None:
    settings = AthanoreSettings(root_path=tmp_path, operator_token="do-not-leak")
    assert "do-not-leak" not in repr(settings)
    assert "do-not-leak" not in str(settings)
