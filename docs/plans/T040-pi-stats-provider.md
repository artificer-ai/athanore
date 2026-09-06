# T040 — Pi stats provider in `examples/` and the remaining agent tests

**Task.** `docs/v1/17-serial-task-plan.md` § `### T040`.
**Specs.** `docs/v1/05-agents.md` §Stats; `AGENTS.md` §Architecture rules
— "small core: nothing in `athanore/` depends on pi, Claude, or Docker;
vendor adapters and example workflows live in `examples/`".
**Reference.** v0's `test_stats.py` (session-file parts),
`test_stats_workflow.py`, `test_agents.py`.

## What this task is

The first vendor adapter, deliberately outside the package: pi's session
files parsed into `SessionStats`, plus the last of the agent tests moved
into the v1 layout.

## What this task is not

- **Nothing lands in `athanore/`.** If a helper feels too general to
  live in `examples/pi`, that is a signal to check whether T036's
  Protocol is missing something — not to import pi from the core.
- No deletion of MVP modules: they were never in this repository (D65).
  "Delete" in the task text means tick the ledger row.

## Steps

1. `examples/pi/__init__.py` and `examples/pi/stats.py`:
   `class PiSessionStats(SessionStatsProvider)` wrapping v0's
   `find_session_file`, `parse_session_file` and
   `final_assistant_stop_reason` — reimplemented here from the sibling
   checkout as the behavioural reference.
2. `examples/tests/test_pi_stats.py` receives the session-file tests.
3. Port `test_stats_workflow.py` and the remainder of `test_agents.py`
   and `test_stats.py` into `tests/agents/`.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q examples tests"
./scripts/dev.sh "uv run lint-imports"     # nothing in athanore/ imports examples
./scripts/dev.sh "grep -rn 'import pi\|from pi' athanore/ || echo clean"
```

The grep is the point of the task: a vendor import that sneaks into the
core is exactly what the small-core rule exists to stop, and it is
cheap to prove absent.

## Done

- `uv run pytest examples` and `tests/` green.
- Ledger rows for `test_stats.py`, `test_stats_workflow.py`,
  `test_agents.py` ticked.
- `**Status.** Done.` on `### T040`, in the same commit.

## Files

```
examples/pi/{__init__.py,stats.py}
examples/tests/test_pi_stats.py
tests/agents/**
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
