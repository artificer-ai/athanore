# T050 — Builtin plugin declarations

**Task.** `docs/v1/17-serial-task-plan.md` § `### T050`.
**Specs.** `docs/v1/09-plugins.md` §Builtins; `docs/v1/10-frontend.md`
§Panels (the slots and elements these declare).

## What this task is

The five panes the SPA shows for every run, declared through the same
plugin system third parties use. That is the point: if the builtins need
something the declaration vocabulary cannot express, the vocabulary is
wrong (T049), not the builtin.

## What this task is not

- No SPA components — T060s. This task declares `<ath-agent-stream>` and
  friends; the elements themselves come later.
- No privileged access. A builtin uses `PluginContext` like anything
  else.

## Steps

Each of `athanore/plugins/builtin/{overview,log,agent,requests,graph}.py`
exposes `declare(wf_host)` registering on an internal `BuiltinWorkflow`
scope that applies to every run:

- **overview** — a `dashboard` run pane, plus a `source` route returning
  `{note, metrics: [TOKENS, COST, DURATION, POSITION], table: nodes}`
  and `kv` meta. Metrics omit what is unknown (`AGENTS.md` real data
  only) — a run with no stats shows fewer tiles, not zeros.
- **log** — a `log` run pane whose source merges `log_entries` and
  lifecycle events **by time**, with `refresh_on=["log.appended",
  "task.*"]`.
- **agent** — a `custom` pane rendering `<ath-agent-stream>`.
- **requests** — a `custom` `<ath-requests>` run pane plus a `global`
  pane (the inbox).
- **graph** — a `custom` `<ath-run-graph>`.

The manifest lists them under `workflow: "_builtin"`, first, in that
order.

## Verification

`tests/plugins/test_builtin.py`:

- manifest order is exactly the five above, before any user plugin;
- the overview source's totals **equal `RunDetail.stats`** — two paths
  to the same numbers must agree, or the dashboard quietly disagrees
  with the run page;
- the log source interleaves entries and events by time.

## Done

- Tests pass; snapshot updated.
- `**Status.** Done.` on `### T050`, in the same commit.

## Files

```
athanore/plugins/builtin/{overview,log,agent,requests,graph}.py
tests/plugins/test_builtin.py
tests/snapshots/openapi.json
docs/v1/17-serial-task-plan.md
```
