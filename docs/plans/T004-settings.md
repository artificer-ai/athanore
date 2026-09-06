# T004 — `AthanoreSettings`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T004`.
**Specs.** `docs/v1/02-architecture.md` §Configuration (every field and
default), §Library choices (pydantic-settings); `docs/v1/12-security.md`
§Auth (`operator_token`, `require_token`, loopback).

## What this task is

One module, `athanore/settings.py`, and its test file. It is the first
task in the repository to add `tests/`, which turns on the gate's pytest
step — `./scripts/test.sh` runs `uv run pytest -q` as soon as the
directory exists, so the suite has to be green, not merely written.

## What this task is not

- **T005** writes `athanore/logging.py` and the `ruff` / `pyright` /
  `import-linter` config. Add no tool config here.
- Nothing consumes settings yet: no engine, no server, no CLI wiring.
  `AthanoreSettings` is constructed by tests and nothing else. Wiring is
  T031's (`Server`) and T011's (CLI).
- No `.athanore/` directory creation, no token generation. `token_file`
  is a path property; `athanore token rotate` is the CLI's job later.

## Steps

1. `class AthanoreSettings(BaseSettings)` with
   `model_config = SettingsConfigDict(env_prefix="ATHANORE_",
   toml_file="athanore.toml", extra="ignore")`.
2. Override `settings_customise_sources` so precedence is **init kwargs
   (CLI) > env > TOML > defaults**, with the TOML path resolved against
   `root_path`. This ordering is the part most easily got backwards;
   the test for it is the acceptance criterion.
3. Fields and defaults exactly as 02 §Configuration lists them —
   `root_path`, `db_url` (computed
   `sqlite+aiosqlite:///{root}/athanore.db` when unset), `host`, `port`,
   `public_url` (computed `http://{host}:{port}`), `operator_token:
   SecretStr | None`, `require_token`, `body_limit`, `sse_replay_cap`,
   `workers`, `max_retries`, `agent_timeout`, `permission_policy`,
   `cors_origins`, `log_format`, `stream_flush_interval`,
   `run_migrations`, `forwarded_allow_ips`, `retention: Retention`
   (`events_days=30`, `stream_days=14`).
4. Properties: `is_loopback`
   (`ipaddress.ip_address(host).is_loopback` or `host == "localhost"`),
   `token_file` (`root/.athanore/token`), `effective_operator_token`
   (the setting, else the file's contents when it exists).
5. Legacy shim: read `ARTIFICER_PORT` / `ARTIFICER_DB` / `ARTIFICER_HOST`
   when the `ATHANORE_` name is unset, and emit a `DeprecationWarning`.
   A warning that is not emitted is a silently ignored config — test it.

## Verification

`tests/test_settings.py` covers, at minimum:

- precedence: kwargs beat env beat TOML beat defaults, using `tmp_path`
  for the TOML file and `monkeypatch.setenv` for the environment;
- computed `db_url` and `public_url`, including that an explicit value
  wins over the computed one;
- `is_loopback` for `127.0.0.1`, `::1`, `localhost` (true) and `0.0.0.0`
  (false);
- the legacy env vars, asserting the `DeprecationWarning` with
  `pytest.warns`;
- `effective_operator_token` with the file present and absent.

`SecretStr` must not leak: assert `repr(settings)` does not contain the
token value.

## Done

- `uv run pytest -q` green — and note this is the run that turns pytest
  on in the gate for every later task.
- `AthanoreSettings()` with no env and no file yields the documented
  defaults.
- `**Status.** Done.` on `### T004`, in the same commit.

## Files

```
athanore/settings.py
tests/test_settings.py
docs/v1/17-serial-task-plan.md
```
