# T055 — Port the end-to-end API tests and the public API surface

**Task.** `docs/v1/17-serial-task-plan.md` § `### T055`.
**Specs.** `docs/v1/02-architecture.md` §Public API surface (the exact
name list); `docs/v1/14-migration-and-phasing.md` §Compatibility (the
deprecated aliases).
**Reference.** v0's `tests/test_e2e.py`, `test_api_surface.py`.

## What this task is

The end-to-end suite through the real API, and `athanore/__init__.py`
finally becoming the package's front door — it has been deliberately
empty since T002.

## What this task is not

- **No MVP teardown** (D65): there are no flat modules to delete, no
  `textual` / `netext` / `textual-dev` to drop, no `ignore_imports`
  hatch to remove, and no TUI — it stays in v0 and retires with it
  (D13, D67). The task text's teardown steps are already-satisfied
  no-ops; say so rather than inventing work.
- No new endpoints or behaviour.

## Steps

1. `tests/api/test_e2e.py`: submit → `MockAgent` submits → completion
   observed through **both** the API and SSE; fan-out driven via the
   API; requests answered through the API.
2. `athanore/__init__.py`: the 02 §Public API surface, plus the
   deprecated aliases exposed through a module `__getattr__` that emits
   `warnings.warn` on access — so importing an old name works and tells
   you it is old.

## Verification

`tests/test_public_api.py`:

- every name listed in 02 is importable from `athanore`;
- each alias warns on access, and returns the right object;
- nothing extra is exported — iterate `__all__` against 02's list in
  both directions.

```sh
find athanore -maxdepth 1 -name "*.py"
# must list exactly: __init__.py settings.py logging.py workflow.py server.py
```

## Done

- Tests pass; the `find` above matches exactly.
- Ledger rows for `test_e2e.py`, `test_api_surface.py` and
  `test_tui.py` (retired) ticked.
- `**Status.** Done.` on `### T055`, in the same commit.

## Files

```
athanore/__init__.py
tests/api/test_e2e.py
tests/test_public_api.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
