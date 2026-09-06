# T012 — Alembic environment and the initial migration

**Task.** `docs/v1/17-serial-task-plan.md` § `### T012`.
**Specs.** `docs/v1/07-storage.md` §Migrations; `docs/v1/14-migration-and-phasing.md`
(why a v0 database must be detectable).

## What this task is

Alembic, living inside the package so a shipped wheel can migrate its
own database, plus the one migration that creates T011's schema.

## What this task is not

- **T018** writes the v0 importer. This task only adds
  `is_v0_database()`, the detection predicate — no reading of v0 data.
- No schema changes. If the migration and `tables.py` disagree, the
  migration is wrong: 07 §Schema is the source and T011 already
  transcribed it.
- No automatic migration on startup. `run_migrations` is a setting T004
  defined and T031 acts on.

## Steps

1. `athanore/store/migrations/{env.py, script.py.mako, alembic.ini,
   versions/0001_v1_schema.py}` — inside the package, because
   `script_location` has to resolve from an installed wheel, not from a
   source checkout.
2. `env.py`: drive the async engine with `run_sync`,
   `target_metadata = tables.metadata`, and `render_as_batch=True` so
   SQLite ALTERs work in later migrations.
3. `athanore/store/migrate.py`:
   - `alembic_config(db_url) -> Config`, built programmatically with
     `script_location` pointing inside the package;
   - `async def upgrade(db_url, rev="head")`;
   - `async def current(db_url) -> str | None`;
   - `async def is_v0_database(db_url) -> bool` — has a `runs` table and
     no `alembic_version`.

## Verification

`tests/store/test_migrations.py`:

- upgrade an empty tmp file, then
  `alembic.autogenerate.compare_metadata(...)` returns `[]`. This is the
  test that matters: it proves the migration and `tables.py` cannot
  drift, and it is why T011's naming convention exists;
- `current()` returns `"0001"`;
- `is_v0_database` is true for a v0-shaped database. T018 brings the
  real fixture; until then create a three-table stub inline (a `runs`
  table and no `alembic_version`) rather than marking the test `xfail` —
  an inline stub tests the predicate now, an xfail tests nothing.

```sh
./scripts/dev.sh "uv run pytest -q tests/store/test_migrations.py"
./scripts/dev.sh "grep -rn 'CREATE TABLE' athanore/ | grep -v migrations/"   # must be empty
```

## Done

- Tests pass, `compare_metadata` empty.
- No `CREATE TABLE` anywhere outside the migration.
- `**Status.** Done.` on `### T012`, in the same commit.

## Files

```
athanore/store/migrations/{env.py,script.py.mako,alembic.ini,versions/0001_v1_schema.py}
athanore/store/migrate.py
tests/store/test_migrations.py
docs/v1/17-serial-task-plan.md
```
